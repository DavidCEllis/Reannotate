"""
This module extends some parts of Python 3.14's `annotationlib`

It adds a new unofficial Format in order to make creating new annotate functions possible
without having to rewrite complex internal logic to do so.

This adds support for a `Format.DEFERRED` option which allows annotations to be
collected in deferred form for easy reconstruction into new `__annotate__` functions.

Doing so requires reproducing some parts of `annotationlib` as doing so requires replacing
some parts in the middle of `call_annotate_function`.
"""

import ast
import builtins
import enum
import types
import sys


from annotationlib import (
    call_annotate_function as _annotationlib_call_annotate_function,
    get_annotations as _annotationlib_get_annotations,

    _SLOTS,
    _Template,
    _get_dunder_annotations,
    _stringify_single,
    _template_to_ast,
    ForwardRef,
    type_repr,
)


class _Sentinel:
    # Sentinel object for the case where None is valid
    def __repr__(self):
        return "<Sentinel Object>"

_sentinel = _Sentinel()


class Format(enum.IntEnum):
    VALUE = 1
    VALUE_WITH_FAKE_GLOBALS = 2
    FORWARDREF = 3
    STRING = 4

    # Hopefully there will never be 5000 formats for annotations
    # A high number is used in case new formats are added
    DEFERRED = 5000


# _Stringifier and _StringifierDict are vendored with slight modifications from annotationlib
# This is necessary to correctly support Format.DEFERRED
# We can't subclass and add methods due to name mangling :(
class _Stringifier:
    # Must match the slots on ForwardRef, so we can turn an instance of one into an
    # instance of the other in place.
    __slots__ = _SLOTS

    def __init__(
        self,
        node,
        globals=None,
        owner=None,
        is_class=False,
        cell=None,
        *,
        stringifier_dict,
        extra_names=None,
    ):
        # Either an AST node or a simple str (for the common case where a ForwardRef
        # represent a single name).
        assert isinstance(node, (ast.AST, str))
        self.__arg__ = None
        self.__forward_is_argument__ = False
        self.__forward_is_class__ = is_class
        self.__forward_module__ = None
        self.__code__ = None
        self.__ast_node__ = node
        self.__globals__ = globals
        self.__extra_names__ = extra_names
        self.__cell__ = cell
        self.__owner__ = owner
        self.__stringifier_dict__ = stringifier_dict

    def __convert_to_ast(self, other):
        if isinstance(other, _Stringifier):
            if isinstance(other.__ast_node__, str):
                return ast.Name(id=other.__ast_node__), other.__extra_names__
            return other.__ast_node__, other.__extra_names__
        elif type(other) is _Template:
            return _template_to_ast(other), None
        elif (
            # In STRING format we don't bother with the create_unique_name() dance;
            # it's better to emit the repr() of the object instead of an opaque name.
            # For the DEFERRED format similarly we should not be creating names.
            self.__stringifier_dict__.format in {Format.STRING, Format.DEFERRED}
            or other is None
            or type(other) in (str, int, float, bool, complex)
        ):
            return ast.Constant(value=other), None
        elif type(other) is dict:
            extra_names = {}
            keys = []
            values = []
            for key, value in other.items():
                new_key, new_extra_names = self.__convert_to_ast(key)
                if new_extra_names is not None:
                    extra_names.update(new_extra_names)
                keys.append(new_key)
                new_value, new_extra_names = self.__convert_to_ast(value)
                if new_extra_names is not None:
                    extra_names.update(new_extra_names)
                values.append(new_value)
            return ast.Dict(keys, values), extra_names
        elif type(other) in (list, tuple, set):
            extra_names = {}
            elts = []
            for elt in other:
                new_elt, new_extra_names = self.__convert_to_ast(elt)
                if new_extra_names is not None:
                    extra_names.update(new_extra_names)
                elts.append(new_elt)
            ast_class = {list: ast.List, tuple: ast.Tuple, set: ast.Set}[type(other)]
            return ast_class(elts), extra_names
        else:
            name = self.__stringifier_dict__.create_unique_name()
            return ast.Name(id=name), {name: other}

    def __convert_to_ast_getitem(self, other):
        if isinstance(other, slice):
            extra_names = {}

            def conv(obj):
                if obj is None:
                    return None
                new_obj, new_extra_names = self.__convert_to_ast(obj)
                if new_extra_names is not None:
                    extra_names.update(new_extra_names)
                return new_obj

            return ast.Slice(
                lower=conv(other.start),
                upper=conv(other.stop),
                step=conv(other.step),
            ), extra_names
        else:
            return self.__convert_to_ast(other)

    def __get_ast(self):
        node = self.__ast_node__
        if isinstance(node, str):
            return ast.Name(id=node)
        return node

    def __make_new(self, node, extra_names=None):
        new_extra_names = {}
        if self.__extra_names__ is not None:
            new_extra_names.update(self.__extra_names__)
        if extra_names is not None:
            new_extra_names.update(extra_names)
        stringifier = _Stringifier(
            node,
            self.__globals__,
            self.__owner__,
            self.__forward_is_class__,
            stringifier_dict=self.__stringifier_dict__,
            extra_names=new_extra_names or None,
        )
        self.__stringifier_dict__.stringifiers.append(stringifier)
        return stringifier

    # Must implement this since we set __eq__. We hash by identity so that
    # stringifiers in dict keys are kept separate.
    def __hash__(self):
        return id(self)

    def __getitem__(self, other):
        # Special case, to avoid stringifying references to class-scoped variables
        # as '__classdict__["x"]'.
        if self.__ast_node__ == "__classdict__":
            raise KeyError
        if isinstance(other, tuple):
            extra_names = {}
            elts = []
            for elt in other:
                new_elt, new_extra_names = self.__convert_to_ast_getitem(elt)
                if new_extra_names is not None:
                    extra_names.update(new_extra_names)
                elts.append(new_elt)
            other = ast.Tuple(elts)
        else:
            other, extra_names = self.__convert_to_ast_getitem(other)
        assert isinstance(other, ast.AST), repr(other)
        return self.__make_new(ast.Subscript(self.__get_ast(), other), extra_names)

    def __getattr__(self, attr):
        return self.__make_new(ast.Attribute(self.__get_ast(), attr))

    def __call__(self, *args, **kwargs):
        extra_names = {}
        ast_args = []
        for arg in args:
            new_arg, new_extra_names = self.__convert_to_ast(arg)
            if new_extra_names is not None:
                extra_names.update(new_extra_names)
            ast_args.append(new_arg)
        ast_kwargs = []
        for key, value in kwargs.items():
            new_value, new_extra_names = self.__convert_to_ast(value)
            if new_extra_names is not None:
                extra_names.update(new_extra_names)
            ast_kwargs.append(ast.keyword(key, new_value))
        return self.__make_new(ast.Call(self.__get_ast(), ast_args, ast_kwargs), extra_names)

    def __iter__(self):
        yield self.__make_new(ast.Starred(self.__get_ast()))

    def __repr__(self):
        if isinstance(self.__ast_node__, str):
            return self.__ast_node__
        return ast.unparse(self.__ast_node__)

    def __format__(self, format_spec):
        raise TypeError("Cannot stringify annotation containing string formatting")

    def _make_binop(op: ast.AST):
        def binop(self, other):
            rhs, extra_names = self.__convert_to_ast(other)
            return self.__make_new(
                ast.BinOp(self.__get_ast(), op, rhs), extra_names
            )

        return binop

    __add__ = _make_binop(ast.Add())
    __sub__ = _make_binop(ast.Sub())
    __mul__ = _make_binop(ast.Mult())
    __matmul__ = _make_binop(ast.MatMult())
    __truediv__ = _make_binop(ast.Div())
    __mod__ = _make_binop(ast.Mod())
    __lshift__ = _make_binop(ast.LShift())
    __rshift__ = _make_binop(ast.RShift())
    __or__ = _make_binop(ast.BitOr())
    __xor__ = _make_binop(ast.BitXor())
    __and__ = _make_binop(ast.BitAnd())
    __floordiv__ = _make_binop(ast.FloorDiv())
    __pow__ = _make_binop(ast.Pow())

    del _make_binop

    def _make_rbinop(op: ast.AST):
        def rbinop(self, other):
            new_other, extra_names = self.__convert_to_ast(other)
            return self.__make_new(
                ast.BinOp(new_other, op, self.__get_ast()), extra_names
            )

        return rbinop

    __radd__ = _make_rbinop(ast.Add())
    __rsub__ = _make_rbinop(ast.Sub())
    __rmul__ = _make_rbinop(ast.Mult())
    __rmatmul__ = _make_rbinop(ast.MatMult())
    __rtruediv__ = _make_rbinop(ast.Div())
    __rmod__ = _make_rbinop(ast.Mod())
    __rlshift__ = _make_rbinop(ast.LShift())
    __rrshift__ = _make_rbinop(ast.RShift())
    __ror__ = _make_rbinop(ast.BitOr())
    __rxor__ = _make_rbinop(ast.BitXor())
    __rand__ = _make_rbinop(ast.BitAnd())
    __rfloordiv__ = _make_rbinop(ast.FloorDiv())
    __rpow__ = _make_rbinop(ast.Pow())

    del _make_rbinop

    def _make_compare(op):
        def compare(self, other):
            rhs, extra_names = self.__convert_to_ast(other)
            return self.__make_new(
                ast.Compare(
                    left=self.__get_ast(),
                    ops=[op],
                    comparators=[rhs],
                ),
                extra_names,
            )

        return compare

    __lt__ = _make_compare(ast.Lt())
    __le__ = _make_compare(ast.LtE())
    __eq__ = _make_compare(ast.Eq())
    __ne__ = _make_compare(ast.NotEq())
    __gt__ = _make_compare(ast.Gt())
    __ge__ = _make_compare(ast.GtE())

    del _make_compare

    def _make_unary_op(op):
        def unary_op(self):
            return self.__make_new(ast.UnaryOp(op, self.__get_ast()))

        return unary_op

    __invert__ = _make_unary_op(ast.Invert())
    __pos__ = _make_unary_op(ast.UAdd())
    __neg__ = _make_unary_op(ast.USub())

    del _make_unary_op


class _StringifierDict(dict):
    def __init__(self, namespace, *, globals=None, owner=None, is_class=False, format):
        super().__init__(namespace)
        self.namespace = namespace
        self.globals = globals
        self.owner = owner
        self.is_class = is_class
        self.stringifiers = []
        self.next_id = 1
        self.format = format

    def __missing__(self, key):
        fwdref = _Stringifier(
            key,
            globals=self.globals,
            owner=self.owner,
            is_class=self.is_class,
            stringifier_dict=self,
        )
        self.stringifiers.append(fwdref)
        return fwdref

    def transmogrify(self, cell_dict):
        for obj in self.stringifiers:
            obj.__class__ = ForwardRef
            obj.__stringifier_dict__ = None  # not needed for ForwardRef
            if isinstance(obj.__ast_node__, str):
                obj.__arg__ = obj.__ast_node__
                obj.__ast_node__ = None
            if cell_dict is not None and obj.__cell__ is None:
                obj.__cell__ = cell_dict

    def create_unique_name(self):
        name = f"__annotationlib_name_{self.next_id}__"
        self.next_id += 1
        return name


# _build_closure is also vendored to use the new stringifier class
def _build_closure(annotate, owner, is_class, stringifier_dict, *, allow_evaluation):
    if not annotate.__closure__:
        return None, None
    new_closure = []
    cell_dict = {}
    for name, cell in zip(annotate.__code__.co_freevars, annotate.__closure__, strict=True):
        cell_dict[name] = cell
        new_cell = None
        if allow_evaluation:
            try:
                cell.cell_contents
            except ValueError:
                pass
            else:
                new_cell = cell
        if new_cell is None:
            fwdref = _Stringifier(
                name,
                cell=cell,
                owner=owner,
                globals=annotate.__globals__,
                is_class=is_class,
                stringifier_dict=stringifier_dict,
            )
            stringifier_dict.stringifiers.append(fwdref)
            new_cell = types.CellType(fwdref)
        new_closure.append(new_cell)
    return tuple(new_closure), cell_dict


def call_annotate_function(annotate, format, *, owner=None, _is_evaluate=False):
    """
    Extend annotationlib's `call_annotate_function` to support Format.DEFERRED
    """
    if format != Format.DEFERRED:
        return _annotationlib_call_annotate_function(annotate, format, owner=owner, _is_evaluate=_is_evaluate)

    try:
        return annotate(format)
    except NotImplementedError:
        pass

    # Handle the DEFERRED format
    try:
        # Used to cache value annotations for deferred if successful
        value_annotations = annotate(Format.VALUE_WITH_FAKE_GLOBALS)
    except NotImplementedError:
        # Both STRING and VALUE_WITH_FAKE_GLOBALS are not implemented: fallback to VALUE
        return {
            k: DeferredAnnotation(v)
            for k, v in annotate(Format.VALUE).items()
        }
    except Exception:
        value_annotations = _sentinel

    globals = _StringifierDict({}, format=format)
    is_class = isinstance(owner, type)
    closure, cell_dict = _build_closure(
        annotate, owner, is_class, globals, allow_evaluation=False
    )
    func = types.FunctionType(
        annotate.__code__,
        globals,
        closure=closure,
        argdefs=annotate.__defaults__,
        kwdefaults=annotate.__kwdefaults__,
    )
    annos = func(Format.VALUE_WITH_FAKE_GLOBALS)

    context = EvaluationContext(
        globals=annotate.__globals__,
        locals=None,
        owner=owner,
        is_class=is_class,
        cells=cell_dict,
    )

    if _is_evaluate:
        return DeferredAnnotation(
            annos.__ast_node__ if isinstance(annos, _Stringifier) else _stringify_single(annos),
            evaluation_context=context,
            resolved_value=value_annotations,
        )
    else:
        return {
            key: DeferredAnnotation(
                val.__ast_node__ if isinstance(val, _Stringifier) else _stringify_single(val),
                evaluation_context=context,
                resolved_value=value_annotations[key] if value_annotations is not _sentinel else _sentinel,
            )
            for key, val in annos.items()
        }


def _get_and_call_annotate(obj, format):
    # Copied from annotationlib.py
    # This is necessary to call our annotate function that supports DEFERRED and not the original
    annotate = getattr(obj, "__annotate__", None)
    if annotate is not None:
        ann = call_annotate_function(annotate, format, owner=obj)
        if not isinstance(ann, dict):
            raise ValueError(f"{obj!r}.__annotate__ returned a non-dict")
        return ann
    return None


def get_annotations(obj, *, globals=None, locals=None, eval_str=False, format=Format.VALUE):
    """
    Extend annotationlib.get_annotations to handle `Format.DEFERRED`
    """
    if format == Format.DEFERRED:
        ann = _get_and_call_annotate(obj, format)
        if ann is not None:
            return dict(ann)
        ann = _get_dunder_annotations(obj)

        if ann is not None:
            return {k: DeferredAnnotation(v) for k, v in ann.items()}
        elif isinstance(obj, type) or callable(obj):
            return {}

        raise TypeError(f"{obj!r} does not have annotations")

    return _annotationlib_get_annotations(obj, globals=globals, locals=locals, eval_str=eval_str, format=format)


# New classes and functions
class EvaluationContext:
    # This class handles creating a "locals" dictionary for the evaluation
    # of annotations.
    # The class namespace, cells and type parameters are merged into one
    # dict for evaluation only when evaluation occurs in order to propagate
    # changes that occur *after* the annotation is retrieved.

    __slots__ = (
        "globals",
        "_locals",
        "_owner",
        "_is_class",
        "_cells",
        "_type_params",
    )

    def __init__(
        self,
        *,
        globals,
        locals=None,
        owner=None,
        is_class=False,
        cells=None,
        type_params=None
    ):
        self.globals = globals
        self._locals = locals
        self._owner = owner
        self._is_class = is_class
        self._cells = cells
        self._type_params = type_params

    def _compare_cells(self, other: object) -> bool:
        # Needed for `__eq__`
        if self._cells is other._cells:
            return True
        elif self._cells is None or other._cells is None:
            return False

        return (
            self._cells.keys() == other._cells.keys()
            and all(self._cells[k] is other._cells[k] for k in self._cells)
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, EvaluationContext):
            return NotImplemented

        # Contexts are only equal if they hold the same references
        # not if the references happen to be equal when checked
        return (
            self.globals is other.globals
            and self._locals is other._locals
            and self._owner is other._owner
            and self._is_class == other._is_class
            and self._type_params is other._type_params
            and self._compare_cells(other)
        )

    @property
    def locals(self):
        if self._locals is None:
            locals = {}
            if isinstance(self._owner, type):
                locals.update(vars(self._owner))
        else:
            locals = dict(self._locals)

        # Handle type params
        if self._type_params is None and self._owner is not None:
            type_params = getattr(self._owner, "__type_params__", None)
        else:
            type_params = self._type_params

        # "Inject" type parameters into the local namespace
        # (unless they are shadowed by assignments *in* the local namespace),
        # as a way of emulating annotation scopes when calling `eval()`
        if type_params is not None:
            for param in type_params:
                locals.setdefault(param.__name__, param)

        # Add cell contents
        if isinstance(self._cells, dict):
            for cell_name, cell in self._cells.items():
                try:
                    cell_value = cell.cell_contents
                except ValueError:
                    pass
                else:
                    locals.setdefault(cell_name, cell_value)
        return locals

    def evaluate(self, obj, use_forwardref=False, extra_names=None):
        # returns the evaluated value and a boolean to indicate if ForwardRef was required
        if isinstance(obj, ast.AST):
            expr = ast.fix_missing_locations(ast.Expression(body=obj))
            code = compile(expr, "<annotate>", "eval")
        elif isinstance(obj, str):
            code = compile(obj, "<annotate>", "eval")
        elif isinstance(obj, types.CodeType):
            code = obj
        elif isinstance(obj, ForwardRef):
            code = obj.__forward_code__
        else:
            raise TypeError("'obj' must be a string, ast expression, ForwardRef or code object")

        locals = dict(self.locals)
        if extra_names is not None:
            locals.update(extra_names)

        try:
            return eval(code, globals=self.globals, locals=locals), False
        except Exception:
            if not use_forwardref:
                raise

        new_locals = _StringifierDict(
            {**builtins.__dict__, **self.globals, **locals},
            globals=self.globals,
            owner=self._owner,
            is_class=self._is_class,
            format=Format.FORWARDREF,
        )

        result = eval(code, globals=self.globals, locals=new_locals)
        new_locals.transmogrify(self._cells)
        return result, True


# This function would be added to `ForwardRef`, but this is not otherwise possible
def get_forwardref_evaluation_context(self, globals=None, locals=None, type_params=None, owner=None):
    # Get the globals and locals contexts for reference evaluation
    if owner is None:
        owner = self.__owner__

    if globals is None and self.__forward_module__ is not None:
        globals = getattr(
            sys.modules.get(self.__forward_module__, None), "__dict__", None
        )
    if globals is None:
        globals = self.__globals__
    if globals is None:
        if isinstance(owner, type):
            module_name = getattr(owner, "__module__", None)
            if module_name:
                module = sys.modules.get(module_name, None)
                if module:
                    globals = getattr(module, "__dict__", None)
        elif isinstance(owner, types.ModuleType):
            globals = getattr(owner, "__dict__", None)
        elif callable(owner):
            globals = getattr(owner, "__globals__", None)

    # If we pass None to eval() below, the globals of this module are used.
    if globals is None:
        globals = {}

    # Convert a single `cell` into a dict
    # The context may evaluate additional names
    if isinstance(self.__cell__, types.CellType):
        cells = {self.__forward_arg__: self.__cell__}
    else:
        cells = self.__cell__

    return EvaluationContext(
        globals=globals,
        locals=locals,
        owner=owner,
        is_class=self.__forward_is_class__,
        cells=cells,
        type_params=type_params,
    )


class DeferredAnnotation:
    """
    This exists to handle evaluating objects that have already been evaluated
    in the required formats.

    'obj' can be any object

    Internally if obj is a string or an AST object and an evaluation context
    is provided, the context can be used to evaluate the annotation later.

    If obj is a ForwardRef, the evaluation context can be retrieved from the reference
    and does not need to be provided separately.

    Otherwise the object is treated as having already been evaluated, trying to
    evaluate as VALUE or FORWARDREF will return the original object, STRING will
    return type_repr of the object.
    """
    __slots__ = ("_obj", "_evaluation_context", "_as_str", "_resolved_value")

    def __init__(self, obj, *, evaluation_context=None, resolved_value=_sentinel):
        self._obj = obj
        self._evaluation_context = evaluation_context

        self._as_str = None
        self._resolved_value = resolved_value

    def __eq__(self, other):
        if not isinstance(other, DeferredAnnotation):
            return NotImplemented

        # AST objects need to be compared as strings for equality
        self_obj = self._obj if not isinstance(self._obj, ast.AST) else self.as_str
        other_obj = other._obj if not isinstance(other._obj, ast.AST) else other.as_str

        # Compare property to correctly handle ForwardRef cases
        return (
            self_obj == other_obj
            and self.evaluation_context == other.evaluation_context
        )

    def __repr__(self):
        return f"{self.__class__.__name__}({self.as_str!r})"

    @property
    def is_evaluated(self):
        return self._resolved_value is not _sentinel

    @property
    def as_str(self):
        if self._as_str is None:
            if isinstance(self._obj, str):
                self._as_str = self._obj
            elif isinstance(self._obj, ForwardRef):
                self._as_str = self._obj.__forward_arg__
            elif isinstance(self._obj, ast.AST):
                self._as_str = ast.unparse(self._obj)
            else:
                self._as_str = type_repr(self._obj)
        return self._as_str

    @property
    def evaluation_context(self):
        if self._evaluation_context is None:
            if isinstance(self._obj, ForwardRef):
                self._evaluation_context = get_forwardref_evaluation_context(self._obj)

        return self._evaluation_context

    def evaluate(self, format=Format.VALUE, extra_names=None):
        match format:
            case Format.DEFERRED:
                return self
            case Format.VALUE | Format.FORWARDREF:
                if self._resolved_value is not _sentinel:
                    return self._resolved_value

                if isinstance(self._obj, ForwardRef):
                    return self._obj.evaluate(format=format)

                use_forwardref = (format == Format.FORWARDREF)

                if (
                    (context := self.evaluation_context)
                    and (isinstance(self._obj, (str, ast.AST)))
                ):
                    try:
                        result = context.evaluate(
                            self._obj,
                            use_forwardref,
                            extra_names,
                        )
                    except Exception:
                        if not use_forwardref:
                            raise
                    else:
                        if not result[1]:
                            self._resolved_value = result[0]
                        return result[0]

                    # Try to construct a forwardref
                    ref = ForwardRef(
                        self.as_str,
                        owner=context._owner,
                        is_class=context._is_class,
                    )
                    # Patch in cell/globals
                    ref.__globals__ = context.globals
                    ref.__cell__ = context._cells

                    return ref

                elif isinstance(self._obj, ast.AST):
                    # AST object with no evaluation context - return as string
                    self._resolved_value = self.as_str
                    return self.as_str

                self._resolved_value = self._obj
                return self._obj
            case Format.STRING:
                return self.as_str
            case _:
                raise NotImplementedError(format)


def make_annotate_function(annos):
    """Create a new __annotate__ function from deferred annotations"""
    forward_annos = {
        k: v if isinstance(v, DeferredAnnotation) else DeferredAnnotation(v)
        for k, v in annos.items()
    }

    def __annotate__(format, /):
        match format:
            case Format.VALUE | Format.FORWARDREF | Format.STRING:
                return {k: v.evaluate(format=format) for k, v in forward_annos.items()}
            case Format.DEFERRED:
                return dict(forward_annos)
            case _:
                raise NotImplementedError(format)

    return __annotate__

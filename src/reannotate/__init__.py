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
import types
import sys


from annotationlib import (
    _build_closure,
    _get_dunder_annotations,
    _stringify_single,
    _Stringifier,
    _StringifierDict,
    Format,
    ForwardRef,
    type_repr,
)

# I don't want to import typing!
type _alias = str
_TypeAliasType = type(_alias)
del _alias


class _Sentinel:
    # Sentinel object for the case where None is valid
    def __repr__(self):
        return "<Sentinel Object>"

_sentinel = _Sentinel()


def call_annotate_deferred(annotate, *, owner=None, skip_globals_check=False, _is_evaluate=False):
    """
    Call an annotate function in a way to retrieve deferred annotations

    :param annotate: `__annotate__` function
    :param owner: The object thaat owns the annotate function, if it exists
    :param skip_globals_check: Skip the call to VALUE_WITH_FAKE_GLOBALS - assume it is supported
    """

    try:
        return annotate._deferred_annotations
    except AttributeError:
        pass

    value_annotations = _sentinel

    if not skip_globals_check:
        # If the globals check is done, try to use the globals it returns to cache if successful
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
            pass

    # Deferred annotations are built on STRING annotations
    globals = _StringifierDict({}, format=Format.STRING)
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


def get_deferred_annotations(obj, *, skip_globals_check=False):
    """
    Extend annotationlib.get_annotations to handle `Format.DEFERRED`
    """
    annotate = getattr(obj, "__annotate__", None)

    if annotate is not None:
        ann = call_annotate_deferred(annotate, owner=obj, skip_globals_check=skip_globals_check)
        if not isinstance(ann, dict):
            raise ValueError(f"{obj!r}.__annotate__ returned a non-dict")
        return dict(ann)

    # Fallback, try `__annotations__`
    ann = _get_dunder_annotations(obj)

    if ann is not None:
        return {k: DeferredAnnotation(v) for k, v in ann.items()}
    elif isinstance(obj, type) or callable(obj):
        return {}

    raise TypeError(f"{obj!r} does not have annotations")


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


# This is needed to convert a ForwardRef to a DeferredAnnotation
def get_forwardref_evaluation_context(ref, globals=None, locals=None, type_params=None, owner=None):
    # Get the globals and locals contexts for reference evaluation
    if owner is None:
        owner = ref.__owner__

    if globals is None and ref.__forward_module__ is not None:
        globals = getattr(
            sys.modules.get(ref.__forward_module__, None), "__dict__", None
        )
    if globals is None:
        globals = ref.__globals__
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
    if isinstance(ref.__cell__, types.CellType):
        cells = {ref.__forward_arg__: ref.__cell__}
    else:
        cells = ref.__cell__

    return EvaluationContext(
        globals=globals,
        locals=locals,
        owner=owner,
        is_class=ref.__forward_is_class__,
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

    @staticmethod
    def from_typealias(alias, *, owner=None):
        # Type aliases are not automatically converted
        # Using from_typealias will make them convert.
        return call_annotate_deferred(
            alias.evaluate_value,
            owner=owner,
            _is_evaluate=True
        )

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


class ReAnnotate:
    """
    Create a new `__annotate__` callable from existing annotations.

    If the annotations are DeferredAnnotation objects, these are used directly.
    Otherwise they will be converted
    """
    __slots__ = ("_deferred_annotations",)
    def __init__(self, annotations):
        new_annos = {}
        for k, v in annotations.items():
            if isinstance(v, DeferredAnnotation):
                new_annos[k] = v
            elif isinstance(v, _TypeAliasType):
                new_annos[k] = DeferredAnnotation.from_typealias(v)
            else:
                new_annos[k] = DeferredAnnotation(v)

        self._deferred_annotations = {
            k: v if isinstance(v, DeferredAnnotation) else DeferredAnnotation(v)
            for k, v in annotations.items()
        }

    def __call__(self, format, /):
        match format:
            case Format.VALUE | Format.FORWARDREF | Format.STRING:
                return {k: v.evaluate(format=format) for k, v in self._deferred_annotations.items()}
            case _:
                raise NotImplementedError(format)

    def __repr__(self):
        return f"{type(self).__name__}({self._deferred_annotations!r})"

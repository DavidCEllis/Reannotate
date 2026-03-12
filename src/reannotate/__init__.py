"""
This module extends some parts of Python 3.14+ `annotationlib`

This adds a way to extract annotations as `DeferredAnnotation` objects
which can be individually evaluated at a later point.

It also includes a helper `ReAnnotate` class to be used to act as the new
`__annotate__` callable on objects.
"""
__lazy_modules__ = ["reannotate._version", "collections.abc", "typing"]

import ast
import builtins
import sys
import types

# This requires the use of some private functions and classes from annotationlib
# The alternative would be vendoring their implementations.
from annotationlib import (
    _build_closure,  # type: ignore
    _get_dunder_annotations,  # type: ignore
    _stringify_single,  # type: ignore
    _Stringifier,  # type: ignore
    _StringifierDict,  # type: ignore
    Format,
    ForwardRef,
    type_repr,
)

from ._version import (
    __version__ as __version__,
    __version_tuple__ as __version_tuple__
)

# I want this to be well typed, but I **really** don't want to waste time
# importing modules purely for typing at runtime
TYPE_CHECKING = False
if sys.version_info >= (3, 15):
    from collections.abc import Callable as Callable, Mapping as Mapping
    import typing as t
else:
    # Hacks for imports prior to Python 3.15
    from _collections_abc import Callable as Callable, Mapping as Mapping
    if TYPE_CHECKING:
        import typing as t
    else:
        # Hack lazy import for 3.14
        t = sys.modules.get("typing")
        if t is None:  # pragma: no cover
            class _LazyTyping:
                def __getattr__(self, name):
                    global t
                    import typing
                    t = typing
                    return getattr(t, name)
            t = _LazyTyping()
            del _LazyTyping

if TYPE_CHECKING:
    from typing import overload as _overload
else:
    # Unlike the real overload, this does not register functions
    # Just return None so the function is unusable
    def _overload(func):
        return None


class _Sentinel:
    # Sentinel object for the case where None is valid
    def __repr__(self):
        return "<Sentinel Object>"


_sentinel = _Sentinel()


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

    globals: dict[str, t.Any]
    _locals: Mapping[str, t.Any] | None
    _owner: object
    _is_class: bool
    _cells: Mapping[str, t.Any] | None
    _type_params: tuple[t.TypeVar | t.ParamSpec | t.TypeVarTuple, ...] | None

    def __init__(
        self,
        *,
        globals: dict[str, t.Any],
        locals: Mapping[str, t.Any] | None = None,
        owner: object = None,
        is_class: bool = False,
        cells: Mapping[str, t.Any] | None = None,
        type_params: tuple[t.TypeVar | t.ParamSpec | t.TypeVarTuple, ...] | None = None,
    ):
        self.globals = globals
        self._locals = locals
        self._owner = owner
        self._is_class = is_class
        self._cells = cells
        self._type_params = type_params

    def _compare_cells(self, other: EvaluationContext) -> bool:
        # Needed for `__eq__`
        if self._cells is other._cells:
            return True
        elif self._cells is None or other._cells is None:
            return False

        # fmt: off
        return (
            self._cells.keys() == other._cells.keys()
            and all(self._cells[k] is other._cells[k] for k in self._cells)
        )
        # fmt: on

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
    def locals(self) -> dict[str, t.Any]:
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

    def evaluate(
        self,
        obj: object,
        use_forwardref: bool = False,
        extra_names: dict[str, t.Any] | None = None
    ):
        # returns the evaluated value and a boolean to indicate if ForwardRef was required
        if isinstance(obj, ast.expr):
            expr = ast.fix_missing_locations(ast.Expression(body=obj))
            code = compile(expr, "<annotate>", "eval")
        elif isinstance(obj, str):
            code = compile(obj, "<annotate>", "eval")
        elif isinstance(obj, types.CodeType):
            code = obj
        elif isinstance(obj, ForwardRef):
            code = obj.__forward_code__
        else:
            raise TypeError(
                "'obj' must be a string, ast expression, ForwardRef or code object"
            )

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

    _obj: object
    _evaluation_context: EvaluationContext | None
    _as_str: str | None
    _resolved_value: _Sentinel | t.Any

    def __init__(
        self,
        obj: object,
        *,
        evaluation_context: EvaluationContext | None = None,
        resolved_value: _Sentinel | t.Any = _sentinel
    ):
        self._obj = obj
        self._evaluation_context = evaluation_context

        self._as_str = None
        self._resolved_value = resolved_value

    def __eq__(self, other: object) -> bool:
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

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.as_str!r})"

    @property
    def is_resolved(self) -> bool:
        return self._resolved_value is not _sentinel

    @property
    def as_str(self) -> str:
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
    def evaluation_context(self) -> EvaluationContext | None:
        return self._evaluation_context

    @_overload
    def evaluate(
        self,
        format: t.Literal[Format.STRING],
        extra_names: dict[str, t.Any] | None = ...
    ) -> str: ...

    @_overload
    def evaluate(
        self,
        format: t.Literal[Format.VALUE, Format.FORWARDREF] = ...,
        extra_names: dict[str, t.Any] | None = ...
    ) -> t.Any: ...

    def evaluate(self, format=Format.VALUE, extra_names=None):
        match format:
            case Format.VALUE | Format.FORWARDREF:
                if self._resolved_value is not _sentinel:
                    return self._resolved_value

                # Forward references don't have an evaluation context
                # As such they need to be handled separately
                use_forwardref = format == Format.FORWARDREF
                if isinstance(self._obj, ForwardRef):
                    try:
                        result = self._obj.evaluate(format=Format.VALUE)
                    except Exception:
                        if not use_forwardref:
                            raise
                        result = self._obj.evaluate(format=Format.FORWARDREF)
                    else:
                        self._resolved_value = result

                    return result

                # fmt: off
                if (
                    (context := self.evaluation_context)
                    and (isinstance(self._obj, (str, ast.AST)))
                ):
                    #fmt: on
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
                    ref.__globals__ = context.globals  # type: ignore
                    ref.__cell__ = context._cells  # type: ignore

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
    Otherwise they will be converted.

    Internally in Python 3.15+ these are stored as a frozendict to prevent
    modification.
    """

    __slots__ = ("_deferred_annotations",)

    _deferred_annotations: Mapping[str, DeferredAnnotation]

    def __init__(self, annotations: dict[str, t.Any]):
        new_annos = {
            k: v if isinstance(v, DeferredAnnotation) else DeferredAnnotation(v)
            for k, v in annotations.items()
        }
        try:
            self._deferred_annotations = frozendict(new_annos)  # type: ignore
        except NameError:
            self._deferred_annotations = new_annos

    @property
    def deferred_annotations(self) -> dict[str, DeferredAnnotation]:
        return dict(self._deferred_annotations)

    @_overload
    def __call__(self, format: t.Literal[Format.STRING]) -> dict[str, str]: ...

    @_overload
    def __call__(self, format: t.Literal[Format.VALUE, Format.FORWARDREF]) -> dict[str, t.Any]: ...

    @_overload
    def __call__(self, format: Format) -> dict[str, t.Any]: ...

    def __call__(self, format, /):
        match format:
            case Format.VALUE | Format.FORWARDREF | Format.STRING:
                return {
                    k: v.evaluate(format=format)
                    for k, v in self._deferred_annotations.items()
                }
            case _:
                raise NotImplementedError(format)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.deferred_annotations!r})"


@_overload
def call_annotate_deferred(
    annotate: Callable[[Format], dict[str, t.Any]],
    *,
    owner: object = ...,
    skip_globals_check: bool = ...,
    _is_evaluate: t.Literal[True],
) -> DeferredAnnotation: ...

@_overload
def call_annotate_deferred(
    annotate: Callable[[Format], dict[str, t.Any]],
    *,
    owner: object = ...,
    skip_globals_check: bool = ...,
    _is_evaluate: t.Literal[False] = ...,
) -> dict[str, DeferredAnnotation]: ...

def call_annotate_deferred(
    annotate,
    *,
    owner = None,
    skip_globals_check = False,
    _is_evaluate = False,
):
    """
    Call an annotate function in a way to retrieve deferred annotations.

    Unlike annotationlib.call_annotate_function this includes an option to skip the check that
    ``Format.VALUE_WITH_FAKE_GLOBALS`` is supported. This makes it possible to avoid evaluating the
    annotations, which the check requires. This is intended to make it possible to gather deferred
    annotations without triggering any lazy imports until/unless they are subsequently evaluated.
    This should only be used if it is known that the ``__annotate__`` function has been generated by
    CPython and has not been replaced by the user.

    :param annotate: ``__annotate__`` function
    :param owner: The object thaat owns the annotate function, if it exists
    :param skip_globals_check: Skip the call to VALUE_WITH_FAKE_GLOBALS - assume it is supported
    :returns: a dictionary of string keys and ``DeferredAnnotation`` values
    """

    try:
        return annotate.deferred_annotations  # type: ignore
    except AttributeError:
        pass

    value_annotations = _sentinel

    if not skip_globals_check:
        try:
            # Used to cache value annotations for deferred if successful
            value_annotations = annotate(Format.VALUE_WITH_FAKE_GLOBALS)
        except NotImplementedError:
            # Deferred annotations and VALUE_WITH_FAKE_GLOBALS are not supported: fallback to VALUE
            return {k: DeferredAnnotation(v) for k, v in annotate(Format.VALUE).items()}
        except Exception:
            pass

    # Logic taken from call_annotate_function in annotationlib.py
    # Modified from the logic for STRING annotations
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
            (
                annos.__ast_node__
                if isinstance(annos, _Stringifier)
                else _stringify_single(annos)
            ),
            evaluation_context=context,
            resolved_value=value_annotations,
        )
    else:
        # The only instance of _Sentinel that value_annotations can be is _sentinel
        # Type checkers don't necessarily understand this so ignore them here
        if not isinstance(annos, dict):
            if owner:
                errmsg = f"{owner!r}.__annotate__ returned a non-dict"
            else:
                errmsg = f"{annotate!r} returned a non-dict"
            raise TypeError(errmsg)

        return {
            key: DeferredAnnotation(
                (
                    val.__ast_node__
                    if isinstance(val, _Stringifier)
                    else _stringify_single(val)
                ),
                evaluation_context=context,
                resolved_value=(
                    value_annotations[key]  # type: ignore
                    if value_annotations is not _sentinel
                    else _sentinel
                ),
            )
            for key, val in annos.items()
        }


def call_evaluate_deferred(
    evaluate: Callable[[Format], t.Any],
    *,
    owner: object = None,
    skip_globals_check: bool = False
) -> DeferredAnnotation:
    return call_annotate_deferred(
        evaluate,
        owner=owner,
        skip_globals_check=skip_globals_check,
        _is_evaluate=True,
    )


def get_deferred_annotations(
    obj: t.Any,
    *,
    skip_globals_check: bool = False
) -> dict[str, DeferredAnnotation]:
    """
    Extend annotationlib.get_annotations to handle `Format.DEFERRED`
    """
    annotate = getattr(obj, "__annotate__", None)

    if annotate is not None:
        ann = call_annotate_deferred(
            annotate,
            owner=obj,
            skip_globals_check=skip_globals_check,
        )
        # call_annotate_deferred will always return a new dict
        return ann

    # Fallback, try `__annotations__`
    ann = _get_dunder_annotations(obj)

    if ann is not None:
        return {k: DeferredAnnotation(v) for k, v in ann.items()}
    elif isinstance(obj, type) or callable(obj):
        return {}

    raise TypeError(f"{obj!r} does not have annotations")

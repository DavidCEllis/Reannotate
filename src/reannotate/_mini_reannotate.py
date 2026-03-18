__lazy_modules__ = ["collections.abc", "typing"]

from collections.abc import Mapping
import typing as t
import types

from annotationlib import (
    Format,
    ForwardRef,
    call_annotate_function,
    get_annotations,
    type_repr,
)


class _Sentinel:
    # Sentinel object for the case where None is valid
    def __repr__(self):
        return "<Sentinel Object>"

_sentinel = _Sentinel()


def _call_annotate_deferred(
    annotate: types.FunctionType,
    *,
    owner: object = None,
):
    # Get string annotations and use them to build top level ForwardRef objects
    string_annos = call_annotate_function(annotate, format=Format.STRING)
    is_class = isinstance(owner, type)
    ref_annos = {}

    # Get closure var cell dict
    cell_dict = dict(
        zip(annotate.__code__.co_freevars, annotate.__closure__, strict=True)
    )

    for k, v in string_annos.items():
        ref = ForwardRef(v, owner=owner, is_class=is_class)
        ref.__cell__ = cell_dict
        ref_annos[k] = ref

    return ref_annos


def get_deferred_annotations(obj):
    annotations = None
    annotate = getattr(obj, "__annotate__", None)
    if annotate is not None:
        try:
            # Needs to support VALUE_WITH_FAKE_GLOBALS to have
            # the appropriate globals information
            annotate(Format.VALUE_WITH_FAKE_GLOBALS)
        except NotImplementedError:
            # Fallback for user functions
            annotations = get_annotations(obj, format=Format.FORWARDREF)
        except Exception:
            pass
        if annotations is None:
            annotations = _call_annotate_deferred(annotate, owner=obj)

    else:
        annotations = get_annotations(obj)

    return {k: DeferredAnnotation(v) for k, v in annotations.items()}


class DeferredAnnotation:
    """
    This exists to handle evaluating objects that have already been evaluated
    in the required formats.

    'obj' can be any object

    If obj is a ForwardRef it will be evaluated by `ForwardRef.evaluate()`

    Otherwise the object is treated as having already been evaluated, trying to
    evaluate as VALUE or FORWARDREF will return the original object, STRING will
    return type_repr of the object.
    """

    __slots__ = ("_obj", "_as_str", "_resolved_value")

    _obj: object
    _as_str: str | None
    _resolved_value: _Sentinel | t.Any

    def __init__(
        self,
        obj: object,
    ) -> None:
        self._obj = obj

        self._as_str = None
        self._resolved_value = _sentinel

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DeferredAnnotation):
            return NotImplemented

        return self._obj == other._obj

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.as_str!r})"

    @property
    def as_str(self) -> str:
        if self._as_str is None:
            if isinstance(self._obj, str):
                self._as_str = self._obj
            elif isinstance(self._obj, ForwardRef):
                self._as_str = self._obj.__forward_arg__
            else:
                self._as_str = type_repr(self._obj)
        return self._as_str

    def evaluate(
        self,
        format: Format = Format.VALUE,
    ) -> t.Any | str:
        match format:
            case Format.VALUE | Format.FORWARDREF:
                if self._resolved_value is not _sentinel:
                    return self._resolved_value

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

    def __init__(self, annotations: dict[str, t.Any]) -> None:
        new_annos = {
            k: v if isinstance(v, DeferredAnnotation) else DeferredAnnotation(v)
            for k, v in annotations.items()
        }

        # Use a frozendict in 3.15+
        try:
            self._deferred_annotations = frozendict(new_annos)  # type: ignore  # cover-req-ge3.15
        except NameError:  # cover-req-lt3.15
            self._deferred_annotations = new_annos

    @property
    def deferred_annotations(self) -> dict[str, DeferredAnnotation]:
        return dict(self._deferred_annotations)

    def __call__(self, format: Format, /) -> dict[str, t.Any]:
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

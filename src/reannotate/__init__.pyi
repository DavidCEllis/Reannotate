from annotationlib import Format
from collections.abc import Callable, Mapping

import typing as t


class _Sentinel: ...
_sentinel: _Sentinel = ...


class EvaluationContext:
    __slots__: tuple[str] = ...

    globals: dict[str, t.Any]

    def __init__(
        self,
        *,
        globals: dict[str, t.Any],
        locals: Mapping[str, t.Any] | None = ...,
        owner: object = ...,
        is_class: bool = ...,
        cells: t.Any = ...,  # Need to investigate possible types
        type_params: tuple[t.TypeVar | t.ParamSpec | t.TypeVarTuple, ...] | None = ...,
    ) -> None: ...

    def __eq__(self, other: object) -> bool: ...

    @property
    def locals(self) -> dict[str, t.Any]: ...

    def evaluate(
        self,
        obj: object,
        use_forwardref: bool = ...,
        extra_names: None | dict[str, t.Any] = ...
    ) -> tuple[t.Any, bool]: ...


class DeferredAnnotation:
    __slots__: tuple[str] = ...

    def __init__(
        self,
        obj: object,
        evaluation_context: EvaluationContext | None = None,
        resolved_value: object = ...,
    ) -> None: ...

    def __eq__(self, other: object) -> bool: ...
    def __repr__(self) -> str: ...

    @property
    def is_resolved(self) -> bool: ...

    @property
    def as_str(self) -> str: ...

    @property
    def evaluation_context(self) -> EvaluationContext: ...

    @t.overload
    def evaluate(
        self,
        format: t.Literal[Format.STRING],
        extra_names: dict[str, t.Any] | None = ...
    ) -> str: ...

    @t.overload
    def evaluate(
        self,
        format: t.Literal[Format.VALUE, Format.FORWARDREF] = ...,
        extra_names: dict[str, t.Any] | None = ...
    ) -> t.Any: ...


class ReAnnotate:
    __slots__: tuple[str]

    # In 3.14 this is a dict, in 3.15+ it is a frozendict
    _deferred_annotations: Mapping[str, DeferredAnnotation]

    def __init__(self, annotations: dict[str, t.Any]) -> None: ...

    @property
    def deferred_annotations(self) -> dict[str, DeferredAnnotation]: ...

    @t.overload
    def __call__(self, format: t.Literal[Format.STRING]) -> dict[str, str]: ...

    @t.overload
    def __call__(self, format: t.Literal[Format.VALUE, Format.FORWARDREF]) -> dict[str, t.Any]: ...


def call_annotate_deferred(
    annotate: Callable[[Format], dict[str, t.Any]],
    *,
    owner: object = ...,
    skip_globals_check: bool = ...,
) -> dict[str, DeferredAnnotation]: ...


def call_evaluate_deferred(
    evaluate: Callable[[Format], t.Any],
    *,
    owner: object = ...,
    skip_globals_check: bool = ...
) -> DeferredAnnotation: ...


def get_deferred_annotations(
    obj: t.Any,
    *,
    skip_globals_check: bool = ...,
) -> dict[str, DeferredAnnotation]: ...

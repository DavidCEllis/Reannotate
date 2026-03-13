# Patched version of inspect.signature that uses deferred annotations
# This works by making copies of the relevant functions and patching their
# usage of get_annotations to get_deferred_annotations with additional
# arguments ignored.
__lazy_modules__ = ["collections.abc", "typing"]

import annotationlib
import types
import typing as t
import inspect

from collections.abc import Callable, Mapping

from . import get_deferred_annotations, DeferredAnnotation


type _IntrospectableCallable = Callable[..., t.Any]


def _false_get_annotations(obj: t.Any, **kwargs) -> dict[str, DeferredAnnotation]:
    # A wrapper for get_deferred_annotations that takes kwargs but uses none
    return get_deferred_annotations(obj)


patch_dict = {
    "get_annotations": _false_get_annotations,
}


def get_patched_function(
    func: types.FunctionType,
    patch_dict: dict[str, t.Any],
) -> types.FunctionType:
    patched_globs = func.__globals__ | patch_dict
    new_func = types.FunctionType(
        func.__code__,
        patched_globs,
        name=func.__name__,
        closure=func.__closure__,
        argdefs=func.__defaults__,
        kwdefaults=func.__kwdefaults__,
    )
    patched_globs[func.__name__] = new_func
    patch_dict[func.__name__] = new_func
    return new_func

# Patch the relevant inspect functions.
# _signature_from_function is used by _signature_from_callable
_deferred_signature_from_function = get_patched_function(
    inspect._signature_from_function,
    patch_dict,
)
_deferred_signature_from_callable = get_patched_function(
    inspect._signature_from_callable,
    patch_dict,
)


def signature(
    obj: _IntrospectableCallable,
    *,
    follow_wrapped: bool = True,
    globals: Mapping[str, t.Any] | None = None,
    locals: Mapping[str, t.Any] | None = None,
    eval_str: bool = False,
    annotation_format: annotationlib.Format = annotationlib.Format.VALUE,
) -> inspect.Signature:
    """
    Return a signature with deferred annotations

    This has the same arguments as inspect.signature but annotation format
    will be ignored.
    """
    return _deferred_signature_from_callable(
        obj,
        sigcls=inspect.Signature,
        follow_wrapper_chains=follow_wrapped,
        globals=globals,
        locals=locals,
        eval_str=eval_str,
        annotation_format=annotation_format,
    )

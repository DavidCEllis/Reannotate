# Patched version of inspect.signature that uses deferred annotations
import types
import typing as t
import inspect

from . import get_deferred_annotations


def _false_get_annotations(obj, **kwargs):
    # A wrapper for get_deferred_annotations that takes kwargs but uses none
    return get_deferred_annotations(obj)

def get_patched_function(
    func: types.FunctionType,
    patch_dict: dict[str, t.Any]
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

patch_dict = {
    "get_annotations": _false_get_annotations,
}

# Patched versions of all of the relevant inspect classes
deferred_signature_from_function = get_patched_function(inspect._signature_from_function, patch_dict)
deferred_signature_from_callable = get_patched_function(inspect._signature_from_callable, patch_dict)

def signature(obj, *, follow_wrapped=True):
    return deferred_signature_from_callable(
        obj,
        sigcls=inspect.Signature,
        follow_wrapper_chains=follow_wrapped,
    )

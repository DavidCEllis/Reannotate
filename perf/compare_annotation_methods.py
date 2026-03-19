# type: ignore  # Pylance should ignore this file
from annotationlib import get_annotations, Format, call_annotate_function
from timeit import timeit

from reannotate import get_deferred_annotations


def get_evaluated_deferred(obj):
    return {
        k: v.evaluate(format=Format.FORWARDREF)
        for k, v in get_deferred_annotations(obj).items()
    }


def repeated_call_annotate_forwardref(obj, format=Format.VALUE):
    # Get annotations but prevent caching in `__annotations__`
    annotate = obj.__annotate__
    return call_annotate_function(annotate, format=format, owner=obj)


class Example:
    a: int
    b: str
    c: float
    d: bool
    e: object


ref_example = timeit(lambda: repeated_call_annotate_forwardref(Example), number=10_000)
string_example = timeit(lambda: get_annotations(Example, format=Format.STRING), number=10_000)
deferred_example = timeit(lambda: get_deferred_annotations(Example), number=10_000)
deferred_eval = timeit(lambda: get_evaluated_deferred(Example), number=10_000)

print("Example with all identifiers")
print(f"Annotation Time: {ref_example:.3g}s")
print(f"STRING annotations - {string_example:.3g} | {string_example/ref_example:.3g}x")
print(f"deferred annotations - {deferred_example:.3g} | {deferred_example/ref_example:.3g}x")
print(f"deferred eval annotations - {deferred_eval:.3g} |  {deferred_eval/ref_example:.3g}x")
print()


class Example:
    a: int | float
    b: str | object
    c: list[float]
    d: dict[str, int]
    e: tuple[int, float, str]


ref_example = timeit(lambda: repeated_call_annotate_forwardref(Example), number=10_000)
string_example = timeit(lambda: get_annotations(Example, format=Format.STRING), number=10_000)
deferred_example = timeit(lambda: get_deferred_annotations(Example), number=10_000)
deferred_eval = timeit(lambda: get_evaluated_deferred(Example), number=10_000)

print("Example with some generics")
print(f"Annotation Time: {ref_example:.3g}s")
print(f"STRING annotations - {string_example:.3g} | {string_example/ref_example:.3g}x")
print(f"deferred annotations - {deferred_example:.3g} | {deferred_example/ref_example:.3g}x")
print(f"deferred eval annotations - {deferred_eval:.3g} |  {deferred_eval/ref_example:.3g}x")
print()

class Example:
    a: unknown[list[str, dict[str, int]]]
    b: unknown[list[str, dict[str, int]]]
    c: unknown[list[str, dict[str, int]]]
    d: unknown[list[str, dict[str, int]]]
    e: unknown[list[str, dict[str, int]]]


ref_example = timeit(lambda: repeated_call_annotate_forwardref(Example, format=Format.FORWARDREF), number=10_000)
string_example = timeit(lambda: get_annotations(Example, format=Format.STRING), number=10_000)
deferred_example = timeit(lambda: get_deferred_annotations(Example), number=10_000)
deferred_eval = timeit(lambda: get_evaluated_deferred(Example), number=10_000)

print("Example with multiple forwardref containers")
print(f"Annotation Time: {ref_example:.3g}s")
print(f"STRING annotations - {string_example:.3g} | {string_example/ref_example:.3g}x")
print(f"deferred annotations - {deferred_example:.3g} | {deferred_example/ref_example:.3g}x")
print(f"deferred eval annotations - {deferred_eval:.3g} |  {deferred_eval/ref_example:.3g}x")
print()


class Example:
    a: unknown[list[str, dict[str, int]]]
    b: unknown[list[str, dict[str, int]]]
    c: unknown[list[str, dict[str, int]]]
    d: unknown[list[str, dict[str, int]]]
    e: unknown[list[str, dict[str, int]]]
    f: object.undefined


ref_example = timeit(lambda: repeated_call_annotate_forwardref(Example, format=Format.FORWARDREF), number=10_000)
string_example = timeit(lambda: get_annotations(Example, format=Format.STRING), number=10_000)
deferred_example = timeit(lambda: get_deferred_annotations(Example), number=10_000)
deferred_eval = timeit(lambda: get_evaluated_deferred(Example), number=10_000)

print("Example with multiple forwardref containers and an attribute error")
print(f"Annotation Time: {ref_example:.3g}s")
print(f"STRING annotations - {string_example:.3g} | {string_example/ref_example:.3g}x")
print(f"deferred annotations - {deferred_example:.3g} | {deferred_example/ref_example:.3g}x")
print(f"deferred eval annotations - {deferred_eval:.3g} |  {deferred_eval/ref_example:.3g}x")
print()
# type: ignore  # Pylance should ignore this file
from annotationlib import get_annotations, Format, call_annotate_function
from timeit import timeit

from reannotate import get_deferred_annotations


COUNT = 10_000


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


ref_example = timeit(lambda: repeated_call_annotate_forwardref(Example), number=COUNT)
string_example = timeit(lambda: get_annotations(Example, format=Format.STRING), number=COUNT)
deferred_example = timeit(lambda: get_deferred_annotations(Example), number=COUNT)
deferred_eval = timeit(lambda: get_evaluated_deferred(Example), number=COUNT)

print("Example with all identifiers")
print(f"Annotation Time: {1000 * ref_example/COUNT:.3g}ms")
print(f"STRING annotations - {1000 * string_example/COUNT:.3g}ms | {string_example/ref_example:.3g}x")
print(f"deferred annotations - {1000 * deferred_example/COUNT:.3g}ms | {deferred_example/ref_example:.3g}x")
print(f"deferred eval annotations - {1000 * deferred_eval/COUNT:.3g}ms |  {deferred_eval/ref_example:.3g}x")
print()


class Example:
    a: int | float
    b: str | object
    c: list[float]
    d: dict[str, int]
    e: tuple[int, float, str]


ref_example = timeit(lambda: repeated_call_annotate_forwardref(Example), number=COUNT)
string_example = timeit(lambda: get_annotations(Example, format=Format.STRING), number=COUNT)
deferred_example = timeit(lambda: get_deferred_annotations(Example), number=COUNT)
deferred_eval = timeit(lambda: get_evaluated_deferred(Example), number=COUNT)

print("Example with some generics")
print(f"Annotation Time: {1000 * ref_example/COUNT:.3g}ms")
print(f"STRING annotations - {1000 * string_example/COUNT:.3g}ms | {string_example/ref_example:.3g}x")
print(f"deferred annotations - {1000 * deferred_example/COUNT:.3g}ms | {deferred_example/ref_example:.3g}x")
print(f"deferred eval annotations - {1000 * deferred_eval/COUNT:.3g}ms |  {deferred_eval/ref_example:.3g}x")
print()

class Example:
    a: unknown[list[str, dict[str, int]]]
    b: unknown[list[str, dict[str, int]]]
    c: unknown[list[str, dict[str, int]]]
    d: unknown[list[str, dict[str, int]]]
    e: unknown[list[str, dict[str, int]]]


ref_example = timeit(lambda: repeated_call_annotate_forwardref(Example, format=Format.FORWARDREF), number=COUNT)
string_example = timeit(lambda: get_annotations(Example, format=Format.STRING), number=COUNT)
deferred_example = timeit(lambda: get_deferred_annotations(Example), number=COUNT)
deferred_eval = timeit(lambda: get_evaluated_deferred(Example), number=COUNT)

print("Example with multiple forwardref containers")
print(f"Annotation Time: {1000 * ref_example/COUNT:.3g}ms")
print(f"STRING annotations - {1000 * string_example/COUNT:.3g}ms | {string_example/ref_example:.3g}x")
print(f"deferred annotations - {1000 * deferred_example/COUNT:.3g}ms | {deferred_example/ref_example:.3g}x")
print(f"deferred eval annotations - {1000 * deferred_eval/COUNT:.3g}ms |  {deferred_eval/ref_example:.3g}x")
print()


class Example:
    a: unknown[list[str, dict[str, int]]]
    b: unknown[list[str, dict[str, int]]]
    c: unknown[list[str, dict[str, int]]]
    d: unknown[list[str, dict[str, int]]]
    e: unknown[list[str, dict[str, int]]]
    f: object.undefined


ref_example = timeit(lambda: repeated_call_annotate_forwardref(Example, format=Format.FORWARDREF), number=COUNT)
string_example = timeit(lambda: get_annotations(Example, format=Format.STRING), number=COUNT)
deferred_example = timeit(lambda: get_deferred_annotations(Example), number=COUNT)
deferred_eval = timeit(lambda: get_evaluated_deferred(Example), number=COUNT)

print("Example with multiple forwardref containers and an attribute error")
print(f"Annotation Time: {1000 * ref_example/COUNT:.3g}ms")
print(f"STRING annotations - {1000 * string_example/COUNT:.3g}ms | {string_example/ref_example:.3g}x")
print(f"deferred annotations - {1000 * deferred_example/COUNT:.3g}ms | {deferred_example/ref_example:.3g}x")
print(f"deferred eval annotations - {1000 * deferred_eval/COUNT:.3g}ms |  {deferred_eval/ref_example:.3g}x")
print()
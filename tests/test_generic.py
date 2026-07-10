# Tests for unions and generic extraction of __origin__ and __args__
import types
import typing
from annotationlib import get_annotations, Format
from collections.abc import Callable

from reannotate import get_args, get_origin, get_deferred_annotations, DeferredAnnotation

from unittest.mock import patch


# Falsey Metaclass for union test
class FalseyMeta(type):
    def __bool__(self):
        return False

class FalseyType(metaclass=FalseyMeta):
    pass


class TestGenericAnnotations:
    def test_get_origin(self):
        # Basic origin test for deferred annotations
        def f(a: list[str | int]): ...

        a_anno = get_deferred_annotations(f)['a']
        origin = get_origin(a_anno)

        assert origin is not None
        assert origin.evaluate() is list

    def test_get_args(self):
        # Basic args test for deferred annotations
        def f(a: dict[str, int]): ...

        a_anno = get_deferred_annotations(f)['a']

        args = get_args(a_anno)

        assert args[0].evaluate() is str
        assert args[1].evaluate() is int

    def test_no_origin_args(self):
        # Check that an object with no generic doesn't have origin or args
        def f(a: str): ...

        a_anno = get_deferred_annotations(f)['a']

        assert get_origin(a_anno) is None
        assert get_args(a_anno) == ()

    def test_union_annotation(self):
        def f(a: int | float): ...

        a_anno = get_deferred_annotations(f)['a']

        origin = get_origin(a_anno)
        assert origin is not None
        assert origin.evaluate() is types.UnionType

        args = get_args(a_anno)
        assert args[0].evaluate() is int
        assert args[1].evaluate() is float

    def test_multiple_union_annotation(self):
        # Test a longer chain, make sure list[int] is not flattened
        def f(a: int | float | str | list[int]): ...

        a_anno = get_deferred_annotations(f)['a']

        origin = get_origin(a_anno)
        assert origin is not None
        assert origin.evaluate() is types.UnionType

        args = get_args(a_anno)
        assert args[0].evaluate() is int
        assert args[1].evaluate() is float
        assert args[2].evaluate() is str
        assert args[3].evaluate() == list[int]

    def test_parenthesised_unflattened(self):
        # test that parenthesised __or__ calls are not flattened
        def f(a: int | (float | str) | list): ...

        a_anno = get_deferred_annotations(f)['a']

        args = get_args(a_anno)
        assert args[0].evaluate() is int
        assert args[1].evaluate() == float | str
        assert args[2].evaluate() is list


class TestAnnotationForwardRef:
    # Test evaluating from a ForwardRef
    def test_get_origin(self):
        def f(a: a[str]): ...  # type: ignore

        a_fr = get_annotations(f, format=Format.FORWARDREF)['a']
        a_anno = DeferredAnnotation(a_fr)

        origin = get_origin(a_anno)
        assert origin is not None
        assert origin.as_str == 'a'
        assert get_args(a_anno)[0].evaluate() is str

    def test_get_no_origin_args(self):
        def f(a: a): ...  # type: ignore

        a_fr = get_annotations(f, format=Format.FORWARDREF)['a']
        a_anno = DeferredAnnotation(a_fr)

        assert get_origin(a_anno) is None
        assert get_args(a_anno) == ()

    def test_get_no_origin_cls(self):
        class Example:
            a: a[str]  # type: ignore

        a_fr = get_annotations(Example, format=Format.FORWARDREF)['a']
        a_anno = DeferredAnnotation(a_fr)

        origin = get_origin(a_anno)
        assert origin is not None
        assert origin.as_str == 'a'
        assert get_args(a_anno)[0].evaluate() is str

    def test_union_annotation(self):
        # Put a forwardref first so the whole annotation is a ForwardRef
        def f(a: unknown | int | float): ...  # type: ignore

        a_fr = get_annotations(f, format=Format.FORWARDREF)['a']
        a_anno = DeferredAnnotation(a_fr)

        origin = get_origin(a_anno)
        assert origin is not None
        assert origin.evaluate() is types.UnionType

        args = get_args(a_anno)
        assert args[1].evaluate() is int
        assert args[2].evaluate() is float

        assert args[1].evaluate(format=Format.STRING) == "int"
        assert a_anno.evaluate(format=Format.STRING) == "unknown | int | float"

    def test_union_annotation_falsey(self):
        def f(a: unknown | FalseyType): ...  # type: ignore

        a_fr = get_annotations(f, format=Format.FORWARDREF)['a']
        a_anno = DeferredAnnotation(a_fr)

        assert a_anno.evaluate(format=Format.STRING) == "unknown | test_generic.FalseyType"

        args = get_args(a_anno)
        assert args[1].evaluate() is FalseyType

    def test_filled_cell(self):
        # Test getting evaluation context from a forwardref with cell values
        def f():
            def g(a: a): ...  # type: ignore
            def h(a: a[b]): ...  # type: ignore
            g_annos = get_annotations(g, format=Format.FORWARDREF)
            h_annos = get_annotations(h, format=Format.FORWARDREF)
            a = list
            b = str
            return g_annos, h_annos

        g_fr, h_fr = f()

        g_anno = DeferredAnnotation(g_fr['a'])
        h_anno = DeferredAnnotation(h_fr['a'])

        assert g_anno.evaluate() is list
        assert h_anno.evaluate() == list[str]

        assert get_origin(g_anno) is None

        origin = get_origin(h_anno)
        assert origin is not None
        assert origin.evaluate() is list


class TestDirectAnnotation:
    # Tests where the DeferredAnnotation has been created from a concrete type
    def test_origin_args(self):
        anno = DeferredAnnotation(dict[str, int])

        origin = get_origin(anno)
        args = get_args(anno)

        assert origin is not None
        assert origin.evaluate() is dict
        assert args[0].evaluate() is str
        assert args[1].evaluate() is int

    def test_no_origin_args(self):
        anno = DeferredAnnotation(str)

        origin = get_origin(anno)
        args = get_args(anno)

        assert origin is None
        assert args == ()

    def test_no_unflatten(self):
        def f[**P](a: Callable[P, str]): ...
        anno = DeferredAnnotation(get_annotations(f)['a'])

        origin = get_origin(anno)
        assert origin is not None
        assert origin.evaluate() is Callable

        args = get_args(anno)

        assert isinstance(args[0].evaluate(), typing.ParamSpec)
        assert args[1].evaluate() is str

    def test_unflatten(self):
        anno = DeferredAnnotation(Callable[[bytes, str], int])

        origin = get_origin(anno)
        assert origin is not None
        assert origin.evaluate() is Callable

        args = get_args(anno)

        assert args[0].evaluate() == [bytes, str]
        assert args[1].evaluate() is int

    def test_union(self):
        anno = DeferredAnnotation(float | int)

        origin = get_origin(anno)
        assert origin is not None
        assert origin.evaluate() is types.UnionType

        args = get_args(anno)
        assert args[0].evaluate() is float
        assert args[1].evaluate() is int


# Same tests as the previous class, but with sys.modules patched
@patch("sys.modules", {})
class TestDirectAnnotationNoTyping(TestDirectAnnotation):
    pass


class TestGenericStrings:
    def test_emulated_future(self):
        # Emulate __future__ annotations
        # It still makes sense for this to work even if they will all evaluate to strings
        class Example:
            pass

        Example.__annotations__ = {'a': "list[int]", 'b': "float | int"}

        annos = get_deferred_annotations(Example)
        a_anno = annos['a']
        b_anno = annos['b']

        a_origin = get_origin(a_anno)
        a_args = get_args(a_anno)

        assert a_origin is not None
        assert a_origin.evaluate() == "list"
        assert a_args[0].evaluate() == "int"

        b_origin = get_origin(b_anno)
        b_args = get_args(b_anno)

        assert b_origin is not None
        assert b_origin.evaluate() is types.UnionType
        assert b_args[0].evaluate() == "float"
        assert b_args[1].evaluate() == "int"

    def test_literal_strings(self):
        # Literal strings should behave the same as __future__
        class Example:
            a: "list[int]"
            b: "float | int"

        annos = get_deferred_annotations(Example)
        a_anno = annos['a']
        b_anno = annos['b']

        a_origin = get_origin(a_anno)
        a_args = get_args(a_anno)

        assert a_origin is not None
        assert a_origin.evaluate() == "list"
        assert a_args[0].evaluate() == "int"

        b_origin = get_origin(b_anno)
        b_args = get_args(b_anno)

        assert b_origin is not None
        assert b_origin.evaluate() is types.UnionType
        assert b_args[0].evaluate() == "float"
        assert b_args[1].evaluate() == "int"

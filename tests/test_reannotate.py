import typing
import unittest

from annotationlib import ForwardRef, Format, call_annotate_function, get_annotations
from reannotate import DeferredAnnotation, call_annotate_deferred, get_deferred_annotations, ReAnnotate


class TestDeferredFormat(unittest.TestCase):

    def test_create_from_type(self):
        # Create a DeferredAnnotation from already evaluated types
        deferred_str = DeferredAnnotation(str)

        self.assertEqual(deferred_str.evaluate(format=Format.VALUE), str)
        self.assertEqual(deferred_str.evaluate(format=Format.FORWARDREF), str)
        self.assertEqual(deferred_str.evaluate(format=Format.STRING), "str")

        container = dict[str, list[int]]
        deferred_container = DeferredAnnotation(container)

        self.assertEqual(deferred_container.evaluate(format=Format.VALUE), container)
        self.assertEqual(deferred_container.evaluate(format=Format.FORWARDREF), container)
        self.assertEqual(deferred_container.evaluate(format=Format.STRING), "dict[str, list[int]]")


    def test_create_from_string(self):
        # Create a DeferredAnnotation from string annotations
        # The 'STRING' format must not be double quoted

        deferred_str = DeferredAnnotation("str")

        self.assertEqual(deferred_str.evaluate(format=Format.VALUE), "str")
        self.assertEqual(deferred_str.evaluate(format=Format.FORWARDREF), "str")
        self.assertEqual(deferred_str.evaluate(format=Format.STRING), "str")

        container = "dict[str, list[int]]"
        deferred_container = DeferredAnnotation(container)

        self.assertEqual(deferred_container.evaluate(format=Format.VALUE), container)
        self.assertEqual(deferred_container.evaluate(format=Format.FORWARDREF), container)
        self.assertEqual(deferred_container.evaluate(format=Format.STRING), container)

    def test_create_from_forwardref(self):
        # Create a DeferredAnnotation from an undefined ForwardRef
        class Example:
            a: undefined  # type: ignore

        ref = get_annotations(Example, format=Format.FORWARDREF)['a']

        deferred_ref = DeferredAnnotation(ref)

        with self.assertRaises(NameError):
            deferred_ref.evaluate(format=Format.VALUE)

        new_ref = deferred_ref.evaluate(format=Format.FORWARDREF)

        self.assertEqual(new_ref, ref)

        self.assertEqual(
            deferred_ref.evaluate(format=Format.STRING),
            "undefined",
        )

        # Check the evaluation works once a value is defined
        undefined = str
        self.assertEqual(
            deferred_ref.evaluate(),
            str,
        )

    def test_does_not_support_valuewithfakeglobals(self):
        anno = DeferredAnnotation(str)

        with self.assertRaises(NotImplementedError):
            anno.evaluate(format=Format.VALUE_WITH_FAKE_GLOBALS)

    def test_eq(self):
        # Basic
        anno = DeferredAnnotation(str)
        eq_anno = DeferredAnnotation(str)

        self.assertEqual(anno, eq_anno)

        # From Annotations
        def f(x: str, y: undefined): ...  # type: ignore # noqa: F821

        annos = get_deferred_annotations(f)
        eq_annos = get_deferred_annotations(f)

        self.assertEqual(annos, eq_annos)

        self.assertNotEqual(annos['x'], str)

    def test_ast_eq(self):
        # Test the eq method when deferred annotations use AST objects internally
        def f(a: dict[str, int]): ...

        annos = get_deferred_annotations(f)
        anno_rep = get_deferred_annotations(f)

        self.assertEqual(annos['a'], anno_rep['a'])

    def test_repr(self):
        attrib_anno = DeferredAnnotation(str)
        string_anno = DeferredAnnotation("str")
        ref_anno = DeferredAnnotation(ForwardRef("str"))

        self.assertEqual(repr(attrib_anno), repr(string_anno))
        self.assertEqual(repr(attrib_anno), repr(ref_anno))

    def test_evaluate_attribute_error(self):
        # test evaluating an annotation that would raise
        # an AttributeError
        m = object()
        class Example:
            a: m.undefined  # type: ignore

        annos = get_deferred_annotations(Example)

        with self.assertRaises(AttributeError):
            annos['a'].evaluate(format=Format.VALUE)

        a_ref = annos['a'].evaluate(format=Format.FORWARDREF)

        self.assertIsInstance(a_ref, ForwardRef)

        # Remake from a forwardref and check again
        a_deferred = DeferredAnnotation(a_ref)

        a_fr = a_deferred.evaluate(format=Format.FORWARDREF)

        self.assertIsInstance(a_fr, ForwardRef)

    def test_evaluates_to_value_cached(self):
        # Test that deferred annotations evaluate to the same values as value annotations

        variable = int

        class Example:
            a: str
            b: list[int | float]
            c: variable  # type: ignore

        value_annos = get_annotations(Example, format=Format.VALUE)
        deferred_annos = get_deferred_annotations(Example)

        self.assertEqual(
            value_annos,
            {k: v.evaluate() for k, v in deferred_annos.items()}
        )

        # __annotations__ is cached, as are DeferredAnnotation objects after they evaluate
        # successfully.
        variable = str

        value_annos = get_annotations(Example, format=Format.VALUE)

        self.assertEqual(
            value_annos,
            {k: v.evaluate() for k, v in deferred_annos.items()}
        )

    def test_is_evaluated(self):
        # Check that the value is cached only when expected
        class Example:
            a: list[undefined]  # type: ignore

        a_anno = get_deferred_annotations(Example)['a']
        a_anno.evaluate(format=Format.FORWARDREF)

        self.assertFalse(a_anno.is_evaluated)

        undefined = str
        a_anno.evaluate(format=Format.FORWARDREF)

        self.assertTrue(a_anno.is_evaluated)

    def test_always_deferred(self):
        # Check some types that had 'escaped' deferral initially
        class Example:
            a: str
            b: "int"
            c: [str, int]  # type: ignore
            d: {list: float}  # type: ignore
            e: (str, int)  # type: ignore
            f: typing.attribute_error

        annos = get_deferred_annotations(Example)

        for anno in annos.values():
            self.assertIsInstance(anno, DeferredAnnotation)

    def test_no_unique_name(self):
        # If unique names are not blocked, a literal ellipsis gets converted
        # To a 'unique' name and fails evaluation

        class Example:
            a: list[...]  # type: ignore
            b: undefined  # Prevent caching from VALUE_WITH_FAKE_GLOBALS  # type: ignore  # noqa: F821

        annos = get_deferred_annotations(Example)

        self.assertEqual(
            list[...],  # type: ignore
            annos['a'].evaluate()
        )


class TestMakeAnnotateFunction(unittest.TestCase):
    def test_remade_annotation(self):
        def f(a: int) -> str: ...

        def_annos = get_deferred_annotations(f)
        new_annotate = ReAnnotate(def_annos)

        for fmt in Format:
            if fmt == Format.VALUE_WITH_FAKE_GLOBALS:
                continue
            with self.subTest(format=fmt):
                self.assertEqual(
                    get_annotations(f, format=fmt),
                    call_annotate_function(new_annotate, format=fmt)
                )

    def test_forwardref_annotation(self):
        # Check forwardrefs resolve if they are defined *after* deferred
        # annotations are collected.
        def f(a: undefined): ...  # type: ignore

        def_annos = get_deferred_annotations(f)
        new_annotate = ReAnnotate(def_annos)

        for fmt in Format:
            if fmt in {Format.VALUE, Format.VALUE_WITH_FAKE_GLOBALS}:
                continue
            with self.subTest(format=fmt):
                direct_annos = get_annotations(f, format=fmt)
                remade_annos = call_annotate_function(new_annotate, format=fmt)

                if fmt == Format.FORWARDREF:
                    # cell adjustment
                    remade_annos['a'].__cell__ = remade_annos['a'].__cell__['undefined']

                self.assertEqual(direct_annos, remade_annos)

        undefined = str

        for fmt in Format:
            if fmt == Format.VALUE_WITH_FAKE_GLOBALS:
                continue
            with self.subTest(format=f"Retest {fmt}"):
                self.assertEqual(
                    get_annotations(f, format=fmt),
                    call_annotate_function(new_annotate, format=fmt)
                )

    def test_fakeglobals_raises(self):
        def f(a: int) -> str: ...

        def_annos = get_deferred_annotations(f)
        new_annotate = ReAnnotate(def_annos)

        with self.assertRaises(NotImplementedError):
            new_annotate(Format.VALUE_WITH_FAKE_GLOBALS)

import ast
import typing
import unittest

from annotationlib import ForwardRef, Format, call_annotate_function, get_annotations, get_annotate_from_class_namespace
from reannotate import (
    DeferredAnnotation,
    EvaluationContext,
    ReAnnotate,
    call_annotate_deferred,
    call_evaluate_deferred,
    get_deferred_annotations,
)


class TestDeferredAnnotationClass(unittest.TestCase):
    # Test direct features of DeferredAnnotation

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
            anno.evaluate(format=Format.VALUE_WITH_FAKE_GLOBALS)  # type: ignore

    def test_eq(self):
        # Basic
        anno = DeferredAnnotation(str)
        eq_anno = DeferredAnnotation(str)

        self.assertEqual(anno, eq_anno)

        # From Annotations
        def f(x: str, y: undefined): ...  # type: ignore

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


class TestEvaluationContext(unittest.TestCase):
    # Most of the evaluation context features are tested through other classes
    # This tests the remaining parts directly
    def test_none_cells_fails_eq(self):
        # If one 'cells' attribute is None fail the evaluation
        # even if all others match
        class Example:
            a: int

        a_anno = get_deferred_annotations(Example)['a']
        a_anno_copy = get_deferred_annotations(Example)['a']

        # This is not the test, this is just to make sure the test is valid
        assert a_anno.evaluation_context is not a_anno_copy.evaluation_context

        self.assertEqual(a_anno.evaluation_context, a_anno_copy.evaluation_context)

        # Type narrowing
        assert a_anno_copy.evaluation_context is not None

        # Remove cells from one
        a_anno_copy.evaluation_context._cells = None

        self.assertNotEqual(a_anno.evaluation_context, a_anno_copy.evaluation_context)

    def test_not_implemented_eq(self):
        def f(a: int): ...

        ctx = get_deferred_annotations(f)['a'].evaluation_context
        self.assertNotEqual(ctx, object())

    def test_ctx_evaluate_raises(self):
        ctx = EvaluationContext(globals={})
        with self.assertRaises(TypeError):
            ctx.evaluate(object())

    def test_evaluate_extra_name(self):
        ctx = EvaluationContext(globals={})
        result = ctx.evaluate("typing_any", extra_names={"typing_any": typing.Any})

        self.assertEqual(result[0], typing.Any)


class TestGetDeferredAnnotations(unittest.TestCase):
    # Test features of annotations returned from get_deferred_annotations

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

    def test_is_resolved(self):
        # Check that the value is cached only when expected
        class Example:
            a: list[undefined]  # type: ignore

        a_anno = get_deferred_annotations(Example)['a']
        a_anno.evaluate(format=Format.FORWARDREF)

        self.assertFalse(a_anno.is_resolved)

        undefined = str
        a_anno.evaluate(format=Format.FORWARDREF)

        self.assertTrue(a_anno.is_resolved)

    def test_always_deferred(self):
        # Check some types that had 'escaped' deferral initially
        class Example:
            a: str
            b: "int"
            c: [str, int]  # type: ignore
            d: {list: float}  # type: ignore
            e: (str, int)  # type: ignore
            f: typing.attribute_error  # type: ignore

        annos = get_deferred_annotations(Example)

        for anno in annos.values():
            self.assertIsInstance(anno, DeferredAnnotation)

    def test_no_unique_name(self):
        # If unique names are not blocked, a literal ellipsis gets converted
        # To a 'unique' name and fails evaluation

        class Example:
            a: list[...]  # type: ignore
            b: undefined  # Prevent caching from VALUE_WITH_FAKE_GLOBALS  # type: ignore

        annos = get_deferred_annotations(Example)

        self.assertEqual(
            list[...],  # type: ignore
            annos['a'].evaluate()
        )

    def test_type_parameter(self):
        class Example[T]:
            a: T

        # If the globals check is used, a is evaluated early and cached
        annos = get_deferred_annotations(Example, skip_globals_check=True)

        self.assertEqual(annos['a'].evaluate(), Example.__type_params__[0])

    def test_fake_future_annotations(self):
        # Test a class with "faked" __future__ annotations
        class Example:
            a: int
            b: str

        Example.__annotations__ = {'a': 'int', 'b': 'str'}

        annos = get_deferred_annotations(Example)

        self.assertEqual(annos['a'].evaluate(), 'int')
        self.assertEqual(annos['b'].evaluate(), 'str')

    def test_objects_with_no_annotations(self):
        annos = get_deferred_annotations(object)
        self.assertEqual(annos, {})

        annos = get_deferred_annotations(print)
        self.assertEqual(annos, {})

    def test_no_annotations_raises(self):
        obj = object()
        with self.assertRaises(TypeError):
            get_deferred_annotations(obj)

    def test_annotate_nondict(self):
        def f(): pass

        def fail_func(format, /):
            return None

        f.__annotate__ = fail_func

        with self.assertRaises(TypeError):
            get_deferred_annotations(f)

        with self.assertRaises(TypeError):
            call_annotate_deferred(fail_func)

    def test_only_value_supported(self):
        class Example:
            a: int
            b: str

        def annotate(fmt, /):
            match fmt:
                case Format.VALUE:
                    return {'a': int, 'b': str}
                case _:
                    raise NotImplementedError(fmt)

        Example.__annotate__ = annotate

        annos = get_deferred_annotations(Example)

        self.assertEqual(annos['a'].evaluate(), int)
        self.assertEqual(annos['a'].evaluate(format=Format.STRING), 'int')


class TestCallAnnotateFunction(unittest.TestCase):
    def test_call_matches_get(self):
        # Check that call_annotate_deferred matches get_annotations on classes
        class Example:
            a: int
            b: undefined  # type: ignore

        annotate = get_annotate_from_class_namespace(Example.__dict__)

        assert annotate is not None  # Type narrowing assertion

        annos = call_annotate_deferred(annotate, owner=Example)

        self.assertEqual(annos, get_deferred_annotations(Example))

    def test_fake_globals_supporting_callable_called_with_value(self):
        # If a callable claims to support fake globals, but is not a function
        # a fallback to VALUE is used
        class AnnotateCallable:
            # Need the names for Format and NotImplementedError to be available
            def __call__(self, fmt, *, _Format=Format, _NotImplementedError=NotImplementedError):
                match fmt:
                    case _Format.VALUE_WITH_FAKE_GLOBALS:
                        return {'a': str}
                    case _Format.VALUE:
                        return {'a': int}
                    case _:
                        raise _NotImplementedError(fmt)

        annotate = AnnotateCallable()

        annos = call_annotate_deferred(annotate)
        assert annos['a'].evaluate() is int

    def test_fake_globals_supporting_callable_raises(self):
        # If a callable claims to support fake globals, but is not a function
        # Will fail if VALUE annotations can't be used
        class AnnotateCallable:
            # Need the names for Format and NotImplementedError to be available
            def __call__(self, fmt, *, _Format=Format, _NotImplementedError=NotImplementedError):
                match fmt:
                    case _Format.VALUE_WITH_FAKE_GLOBALS:
                        return {'a': str}
                    case _Format.VALUE:
                        raise NameError("undefined")
                    case _:
                        raise _NotImplementedError(fmt)

        annotate = AnnotateCallable()

        with self.assertRaises(TypeError):
            call_annotate_deferred(annotate)


class TestCallEvaluateFunction(unittest.TestCase):
    def test_call_type_obj(self):
        type evaluable = list[str]
        evaluate_func = evaluable.evaluate_value
        deferred = call_evaluate_deferred(evaluate_func)

        self.assertEqual(deferred.evaluate(), list[str])
        self.assertEqual(deferred.evaluate(format=Format.STRING), "list[str]")


class TestReAnnotateClass(unittest.TestCase):
    def test_remade_annotation(self):
        def f(a: int) -> str: ...  # type: ignore

        def_annos = get_deferred_annotations(f)
        new_annotate = ReAnnotate(def_annos)

        for fmt in Format:
            if fmt == Format.VALUE_WITH_FAKE_GLOBALS:
                continue
            with self.subTest(format=fmt):
                self.assertEqual(
                    get_annotations(f, format=fmt),
                    call_annotate_function(new_annotate, format=fmt)  # type: ignore
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
                remade_annos = call_annotate_function(new_annotate, format=fmt)  # type: ignore

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
                    call_annotate_function(new_annotate, format=fmt)  # type: ignore
                )

    def test_fakeglobals_raises(self):
        def f(a: int) -> str: ...  # type: ignore

        def_annos = get_deferred_annotations(f)
        new_annotate = ReAnnotate(def_annos)

        with self.assertRaises(NotImplementedError):
            new_annotate(Format.VALUE_WITH_FAKE_GLOBALS)  # type: ignore

    def test_reannotated_gives_deferred(self):
        def f(a: undefined): ...  # type: ignore

        annos = get_deferred_annotations(f)
        new_annotate = ReAnnotate(annos)

        annos_recovered = call_annotate_deferred(new_annotate)

        self.assertEqual(annos, annos_recovered)


class TestExtra(unittest.TestCase):
    # These test some edge cases
    def test_ast_without_context(self):
        # test that an ast object without context
        # evaluates to string
        obj = ast.parse("list[int]").body[0].value

        anno = DeferredAnnotation(obj)

        self.assertEqual(anno.evaluate(), "list[int]")

    def test_user_locals(self):
        # Test if a user provides a locals dict
        globs = {}
        locs = {"undefined": str}

        ctx = EvaluationContext(globals=globs, locals=locs)

        val, _ = ctx.evaluate("undefined")

        self.assertEqual(val, str)

    def test_context_evaluate_forwardref_code(self):
        # This isn't used internally in this extracted version
        # but would be if it became an internal format
        class Example:
            a: undefined

        a_anno = get_deferred_annotations(Example)['a']
        # Extract the evaluation context, and a forwardref
        a_context = a_anno.evaluation_context

        # type narrowing, not a test
        assert a_context is not None

        a_ref = a_anno.evaluate(format=Format.FORWARDREF)

        assert isinstance(a_ref, ForwardRef)

        a_val, a_used_ref = a_context.evaluate(a_ref, use_forwardref=True)

        self.assertTrue(a_used_ref)
        self.assertIsInstance(a_val, ForwardRef)

        undefined = str

        a_val, a_used_ref = a_context.evaluate(a_ref)
        self.assertFalse(a_used_ref)
        self.assertEqual(a_val, str)

        # Also check using the code object directly
        a_val, a_used_ref = a_context.evaluate(a_ref.__forward_code__)

    def test_version_imports(self):
        # This is largely to make sure the file imports in 3.15+
        # as it is a lazy import there
        from reannotate._version import __version__, __version_tuple__

        self.assertIsInstance(__version__, str)
        self.assertIsInstance(__version_tuple__, tuple)


class TestStringLiteral:
    def test_string_literal(self):
        # Manually stringified annotations don't get evaluated
        class Example:
            a: "int"
            b: float
            c: undefined  # Prevent caching of VALUE annotations

        annos = get_deferred_annotations(Example)

        assert annos['a'].evaluate() == "int"
        assert annos['a'].evaluate(format=Format.STRING) == "int"  # Not double quoted
        assert annos['b'].evaluate() is float

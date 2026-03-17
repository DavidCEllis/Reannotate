import unittest

from reannotate import get_deferred_annotations
from reannotate.patches import signature


class TestSignature(unittest.TestCase):
    def test_signature(self):
        def f(a: str, b: int) -> float: ...  # type: ignore

        annos = get_deferred_annotations(f)
        sig = signature(f)

        parameters = sig.parameters

        for k, v in parameters.items():
            self.assertEqual(annos[k], v.annotation)

        self.assertEqual(annos['return'], sig.return_annotation)

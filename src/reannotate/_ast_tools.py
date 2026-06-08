__lazy_modules__ = [
    "collections.abc",
    "typing",
]

import sys
import ast
from annotationlib import type_repr

if sys.version_info >= (3, 15):  # cover-req-ge3.15
    from collections.abc import Mapping
    import typing as t

    _sentinel = sentinel("_sentinel")  # noqa: F821
else:  # cover-req-lt3.15
    from _collections_abc import Mapping
    from ._lazy_import_314 import typing as t

    _sentinel = object()


class NameReplacer(ast.NodeTransformer):
    """
    This class is used to 'fix' names from ForwardRef objects to hide the internals
    """

    def __init__(self, names: Mapping[str, t.Any]):
        self._names = names

    def visit_Name(self, node: ast.Name) -> ast.Name:
        if (new_name := self._names.get(node.id, _sentinel)) is not _sentinel:
            node = ast.Name(id=type_repr(new_name))
        return node

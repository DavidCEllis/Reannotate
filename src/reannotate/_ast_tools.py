import ast
from annotationlib import type_repr


class NameReplacer(ast.NodeTransformer):
    """
    This class is used to 'fix' names from ForwardRef objects to hide the internals
    """
    def __init__(self, names):
        self._names = names

    def visit_Name(self, node: ast.Name):
        if new_name := self._names.get(node.id):
            new_node = ast.Name(id=type_repr(new_name))
            ast.copy_location(node, new_node)
            node = new_node
        return node

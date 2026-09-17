"""Shared helper for the "bazos imports nothing from refprice" assertions.

Parses the import statements rather than grepping the file, because several `bazos` modules
*name* this app in a comment explaining why the seam exists — and a substring search makes
documenting the reason fail the test that enforces it.
"""
import ast
import pathlib


def modules_imported_by(bazos_module: str) -> list[str]:
    """Top-level module names imported by `bazos/<bazos_module>`, including inside functions."""
    source = pathlib.Path(__import__("bazos").__file__).parent / bazos_module
    imported: list[str] = []
    for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    return [name.split(".")[0] for name in imported]

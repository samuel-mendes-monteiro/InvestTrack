"""The layers import only downwards: api -> storage -> sources -> core.

`core` must stay pure (testable without a database or network), and
`sources` only parse outside data into `core`'s types. A wrong import is a
failing test here instead of a slow drift.
"""

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).parent.parent / "investtrack"

# What each layer may import from the project, besides itself.
ALLOWED = {
    "core": set(),
    "sources": {"core"},
    "storage": {"core", "sources"},
}


def project_imports(file: Path) -> set[str]:
    """The investtrack.<layer> names a file imports."""
    layers = set()
    for node in ast.walk(ast.parse(file.read_text())):
        if isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        elif isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        else:
            continue
        for name in names:
            parts = name.split(".")
            if parts[0] == "investtrack" and len(parts) > 1:
                layers.add(parts[1])
    return layers


@pytest.mark.parametrize("layer", sorted(ALLOWED))
def test_layer_imports_only_downwards(layer):
    wrong = {
        str(file.relative_to(PACKAGE)): sorted(imported)
        for file in (PACKAGE / layer).rglob("*.py")
        if (imported := project_imports(file) - ALLOWED[layer] - {layer})
    }
    assert wrong == {}

"""The import rules in docs/backend-structure.md, checked rather than hoped for.

Each rule is what keeps a layer replaceable: a service that imports fastapi cannot be
called from the worker, and a schema that imports a service is a circular import waiting
for the second caller.
"""

import ast
from pathlib import Path

import pytest

API = Path(__file__).resolve().parent.parent / "api"

FORBIDDEN = {
    "services": ("fastapi", "api.routers", "api.deps"),
    "repositories": ("fastapi", "api.routers", "api.services", "api.deps"),
    "schemas": ("fastapi", "api.routers", "api.services", "api.repositories", "sqlalchemy"),
    # security.py is the session arithmetic, with no HTTP types; errors.py is the bridge.
    "core/config.py": ("fastapi",),
    "core/security.py": ("fastapi",),
    "routers": ("sqlalchemy", "schema", "api.repositories"),
}


def _imports(path: Path) -> set[str]:
    out = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def _files(where: str) -> list[Path]:
    target = API / where
    return [target] if target.suffix else sorted(target.glob("*.py"))


@pytest.mark.parametrize("where", FORBIDDEN)
def test_layer_imports_stay_inside_their_rules(where: str) -> None:
    for path in _files(where):
        for name in _imports(path):
            for banned in FORBIDDEN[where]:
                assert name != banned and not name.startswith(banned + "."), (
                    f"{path.relative_to(API)} imports {name}"
                )

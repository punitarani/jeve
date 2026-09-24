"""Sim state never depends on generated text — enforced, not promised.

CORE-0006 replaced seven packages with one distribution and said the boundaries
would be held by a test instead of by packaging. This is that test. It walks the
real import graph (the AST of every module, not a grep), so a lazy import inside
a function is caught too.

The rule that matters most: nothing that computes the world may import
`jeve.gen`. Prose is rendered *from* typed state for a person to read; if the
simulation could import the renderer, sooner or later something would read a
sentence back.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "jeve"

# package -> packages it must never import, directly or lazily.
# `evals` (EVAL-0001) is outermost: it drives `sim`, reads `api`'s detectors and
# calls models through `llm`, and nothing may import it — a number the harness
# writes must never reach the world, the API or the prose it measures.
FORBIDDEN: dict[str, set[str]] = {
    "core": {"world", "decide", "memory", "sim", "gen", "api", "llm", "evals"},
    "llm": {"world", "decide", "memory", "sim", "gen", "api", "evals"},
    "decide": {"world", "sim", "gen", "api", "evals"},
    "memory": {"sim", "gen", "api", "evals"},
    "world": {"sim", "gen", "api", "llm", "evals"},
    "sim": {"gen", "api", "evals"},
    "gen": {"world", "sim", "api", "evals"},
    "api": {"evals"},
    "evals": set(),
}


def imports_of(path: Path) -> set[str]:
    """Every `jeve.<package>` a module imports, at any depth in the file."""

    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names = [node.module]
        for name in names:
            parts = name.split(".")
            if parts[0] == "jeve" and len(parts) > 1:
                found.add(parts[1])
    return found


def test_the_import_graph_respects_the_layers() -> None:
    violations: list[str] = []
    for package, banned in FORBIDDEN.items():
        for path in sorted((SRC / package).rglob("*.py")):
            crossed = imports_of(path) & banned
            for other in sorted(crossed):
                violations.append(
                    f"{path.relative_to(SRC.parent)} imports jeve.{other}"
                )
    assert violations == [], "\n".join(violations)


def test_nothing_that_computes_the_world_can_see_generated_text() -> None:
    """The one rule, stated on its own so a failure names it."""

    for package in ("core", "world", "decide", "memory", "sim", "llm"):
        for path in sorted((SRC / package).rglob("*.py")):
            assert "gen" not in imports_of(path), (
                f"{path.relative_to(SRC.parent)} imports jeve.gen: simulation "
                "state must never depend on generated text"
            )


def test_every_package_is_covered() -> None:
    """A new top-level package must be placed in the layering, not left out."""

    packages = {p.name for p in SRC.iterdir() if p.is_dir() and p.name[0] != "_"}
    assert packages == set(FORBIDDEN)


def test_the_walker_sees_a_lazy_import(tmp_path: Path) -> None:
    sneaky = tmp_path / "sneaky.py"
    sneaky.write_text(
        "def f():\n    from jeve.gen import dialogue\n    return dialogue\n"
    )
    assert imports_of(sneaky) == {"gen"}

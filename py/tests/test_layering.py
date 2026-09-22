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
FORBIDDEN: dict[str, set[str]] = {
    "core": {"world", "decide", "memory", "sim", "gen", "api", "llm"},
    "llm": {"world", "decide", "memory", "sim", "gen", "api"},
    "decide": {"world", "sim", "gen", "api"},
    "memory": {"sim", "gen", "api"},
    "world": {"sim", "gen", "api", "llm"},
    "sim": {"gen", "api"},
    "gen": {"world", "sim", "api"},
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
    assert packages - {"api"} == set(FORBIDDEN)


def external_imports_of(path: Path) -> set[str]:
    """The top-level name of every import in a module, at any depth."""

    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names = [node.module]
        found.update(name.split(".")[0] for name in names)
    return found


def test_only_telemetry_talks_to_sentry() -> None:
    """CORE-0012: one guarded module, like `jeve.llm` for httpx.

    `jeve.telemetry` is the only place that may import `sentry_sdk`: it is
    what keeps "no DSN, no import, no socket" true, and what keeps a telemetry
    failure from reaching a tick — every call into the SDK is wrapped there,
    and a call made anywhere else would not be.
    """

    scripts = SRC.parent.parent / "scripts"
    offenders = [
        str(path.relative_to(SRC.parent.parent))
        for path in sorted([*SRC.rglob("*.py"), *scripts.rglob("*.py")])
        if "sentry_sdk" in external_imports_of(path) and path != SRC / "telemetry.py"
    ]
    assert offenders == [], "\n".join(offenders)


def test_the_walker_sees_a_lazy_import(tmp_path: Path) -> None:
    sneaky = tmp_path / "sneaky.py"
    sneaky.write_text(
        "def f():\n    from jeve.gen import dialogue\n    return dialogue\n"
    )
    assert imports_of(sneaky) == {"gen"}

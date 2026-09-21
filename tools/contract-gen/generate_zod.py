#!/usr/bin/env python3
"""Generate zod schemas from the pydantic contract (jeve.api.contracts).

Run via `nx run contracts:generate` / `make contracts`, which executes this
under `uv run --directory py` so `jeve` resolves from the installed package —
no path juggling. `contracts:check-drift` regenerates and fails on a git diff.
"""

import enum
import types
import typing
from pathlib import Path
from typing import Any, get_args, get_origin

from pydantic import BaseModel
from pydantic_core import PydanticUndefined

from jeve.api.contracts import MODELS

OUTPUT = (
    Path(__file__).resolve().parent.parent.parent
    / "packages"
    / "contracts"
    / "src"
    / "index.ts"
)


def python_type_to_zod(annotation: object, *, required: bool) -> str:
    """One annotation → one zod schema.

    A required `X | None` is `.nullable()`; an optional one (it has a default)
    is `.optional()` — the API either sends the key or omits it, it does not
    send JSON null for absent fields.
    """

    if annotation is int:
        return "z.number().int()"
    if annotation is float:
        return "z.number()"
    if annotation is str:
        return "z.string()"
    if annotation is bool:
        return "z.boolean()"
    if annotation is Any:
        return "z.unknown()"

    origin = get_origin(annotation)
    if origin is typing.Literal:
        args = ", ".join(f'"{a}"' for a in get_args(annotation))
        return f"z.enum([{args}])"
    if origin in (typing.Union, types.UnionType):
        args = get_args(annotation)
        if len(args) == 2 and type(None) in args:
            inner = args[0] if args[1] is type(None) else args[1]
            zod = python_type_to_zod(inner, required=required)
            return f"{zod}.{'nullable' if required else 'optional'}()"
        union = ", ".join(python_type_to_zod(a, required=required) for a in args)
        return f"z.union([{union}])"
    if origin is list:
        args = get_args(annotation)
        inner = python_type_to_zod(args[0], required=True) if args else "z.unknown()"
        return f"z.array({inner})"
    if origin is dict:
        args = get_args(annotation)
        if len(args) == 2:
            key = python_type_to_zod(args[0], required=True)
            value = python_type_to_zod(args[1], required=True)
            return f"z.record({key}, {value})"
        return "z.record(z.string(), z.unknown())"
    if origin is tuple:
        # A fixed-length tuple is a zod tuple: a Tile is [x, y], not a list.
        args = get_args(annotation)
        inner = ", ".join(python_type_to_zod(a, required=True) for a in args)
        return f"z.tuple([{inner}])"
    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        # An enum is the vocabulary's single source: zod gets its values.
        args = ", ".join(f'"{m.value}"' for m in annotation)
        return f"z.enum([{args}])"
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation.__name__
    raise TypeError(f"no zod mapping for {annotation!r}")


def comment(text: str | None, *, indent: str = "  ") -> str:
    if not text:
        return ""
    flat = " ".join(text.split())
    return f"{indent}/** {flat} */\n"


def main() -> None:
    out = """/**
 * The API contract, as zod schemas — generated. Do not edit by hand.
 *
 * Source of truth: the pydantic models in `jeve.api.contracts`
 * (py/src/jeve/api/contracts.py). `nx run contracts:generate` rewrites this
 * file and `contracts:check-drift` fails on the diff; `test_api.py` validates
 * real responses against the same models, so drift is a failing check rather
 * than a runtime surprise.
 *
 * Every response is parsed at the boundary rather than cast. An endpoint that
 * changes shape then fails loudly in one place instead of becoming `undefined`
 * three components deep.
 */
import { z } from "zod";

"""
    for model in MODELS:
        doc = model.__doc__ or ""
        out += comment(doc, indent="")
        out += f"export const {model.__name__} = z.object({{\n"
        for name, field in model.model_fields.items():
            out += comment(field.description)
            required = field.default is PydanticUndefined
            zod = python_type_to_zod(field.annotation, required=required)
            # A default means the key may be absent, whatever its type — the
            # union branch already marks `X | None = default`; everything else
            # gets its `.optional()` here.
            if not required and not zod.endswith(".optional()"):
                zod += ".optional()"
            out += f"  {name}: {zod},\n"
        out += "});\n"
        out += f"export type {model.__name__} = z.infer<typeof {model.__name__}>;\n\n"

    out += """export const ORG_COLORS: Record<string, string> = {
  tallybird: "#7c9cff",
  halloran: "#c9a227",
  ledgerline: "#5bb98c",
  thirdrail: "#e0757c",
};
export * from "./world";
"""
    OUTPUT.write_text(out)
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()

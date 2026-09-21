#!/usr/bin/env python3
"""Generate zod schemas from pydantic models.

This script generates zod schemas directly from the pydantic models,
ensuring that the TypeScript contracts stay in sync with the Python source of truth.
"""

import sys
import os
from pathlib import Path
from typing import Any, Dict, Type, get_origin, get_args, Literal, Union, Optional
import inspect


def python_type_to_zod(python_type, field_info=None) -> str:
    """Convert Python type annotations to zod schema types."""
    if python_type == int:
        return "z.number().int()"
    elif python_type == float:
        return "z.number()"
    elif python_type == str:
        return "z.string()"
    elif python_type == bool:
        return "z.boolean()"
    elif get_origin(python_type) == Literal:
        # Handle Literal types
        args = get_args(python_type)
        quoted_args = [f'"{arg}"' for arg in args]
        return f'z.enum([{", ".join(quoted_args)}])'
    elif get_origin(python_type) == Union:
        # Handle Union types (including Optional)
        args = get_args(python_type)
        if len(args) == 2 and type(None) in args:
            # This is Optional[T]
            inner_type = args[0] if args[1] == type(None) else args[1]
            inner_zod = python_type_to_zod(inner_type)
            # Check if field is required (PydanticUndefined) or optional (has default)
            from pydantic_core import PydanticUndefined

            if field_info and field_info.default is PydanticUndefined:
                return f"{inner_zod}.nullable()"  # Required but can be null
            else:
                return f"{inner_zod}.optional()"  # Optional field
        else:
            # General union
            inner_types = [python_type_to_zod(arg) for arg in args]
            return f'z.union([{", ".join(inner_types)}])'
    elif get_origin(python_type) == list:
        # Handle List types
        inner_type = (
            get_args(python_type)[0] if get_args(python_type) else "z.unknown()"
        )
        return f"z.array({python_type_to_zod(inner_type)})"
    elif get_origin(python_type) == dict:
        # Handle Dict types - check if we have specific key/value types
        args = get_args(python_type)
        if len(args) >= 2:
            key_type = python_type_to_zod(args[0])
            value_type = python_type_to_zod(args[1])
            return f"z.record({key_type}, {value_type})"
        else:
            return "z.record(z.string(), z.unknown())"
    elif inspect.isclass(python_type) and issubclass(python_type, BaseModel):
        # Handle nested BaseModel types
        return python_type.__name__
    else:
        # Default fallback
        return "z.unknown()"


def get_field_comment(field_name: str, model_name: str) -> str:
    """Get comments for specific fields that need explanation."""
    comments = {
        "Clock": {
            "status": "  // Every value the database's CHECK allows. `paused_budget` was missing, so\n  // the day the governor paused the world the page would have failed to parse.",
        },
        "Health": {
            "heartbeat_age_s": "  /** Seconds since the daemon last proved it was alive. Null before its first beat. */",
            "lag_s": "  /** How far the last tick ran over its pacing. */",
            "stale": "  /** The status says a process should be alive and the heartbeat says none is. */",
        },
        "WorldState": {
            "tickets": "  tickets: z.object({ untriaged: z.number().int(), open: z.number().int() }),",
            "unpaid_invoices": "  unpaid_invoices: z.object({ n: z.number().int(), cents: z.number().int() }),",
        },
        "SimEvent": {
            "tick_seq": "  tick_seq: z.number().int().optional(),",
            "label": "  label: z.string().optional(),",
            "depth": "  depth: z.number().int().optional(),",
        },
        "Person": {
            "decision_seq": "  decision_seq: z.number().int().optional(),",
            "status": "  status: z.string().optional(),",
        },
        "Decision": {
            "label": "  label: z.string().optional(),",
            "source": "  /** Which kind of decider answered — the research question, per row. */",
            "distributions": "  /** Empty for a rules decision; a real distribution once Jev is wired in. */",
        },
        "Economics": {
            "without_dedup": "  without_dedup: z.object({ spend_usd: z.number(), per_sim_day: PerSimDay }),",
            "decisions_by_model": """  decisions_by_model: z.array(
    z.object({
      model: z.string(),
      decisions: z.number().int(),
      calls: z.number().int(),
    }),
  ),""",
            "by_kind": """  by_kind: z.array(
    z.object({
      kind: z.string(),
      source: z.string(),
      decisions: z.number().int(),
      calls: z.number().int(),
      usd: z.number(),
    }),
  ),""",
        },
    }
    return comments.get(model_name, {}).get(field_name, "")


# Add the src directory to the path
py_dir = Path(__file__).parent.parent.parent / "py"
os.chdir(py_dir)
sys.path.insert(0, str(py_dir / "src"))

try:
    from pydantic import BaseModel
    import json

    # Import the contract models
    sys.path.insert(0, str(Path(__file__).parent))
    from models import (
        Clock,
        Org,
        Module,
        Health,
        WorldState,
        SimEvent,
        EventPage,
        CausalChain,
        Person,
        Decision,
        PersonDecisions,
        PerSimDay,
        Economics,
        ORG_COLORS,
    )

    print("Generating zod schemas from pydantic models...")

    # Models to generate
    models_to_generate: Dict[str, Type[BaseModel]] = {
        "Clock": Clock,
        "Org": Org,
        "Module": Module,
        "Health": Health,
        "WorldState": WorldState,
        "SimEvent": SimEvent,
        "EventPage": EventPage,
        "CausalChain": CausalChain,
        "Person": Person,
        "Decision": Decision,
        "PersonDecisions": PersonDecisions,
        "PerSimDay": PerSimDay,
        "Economics": Economics,
    }

    output_dir = Path(__file__).parent.parent.parent / "packages" / "contracts" / "src"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate zod schemas with preserved comments
    zod_schemas = """/**
 * The API contract, as zod schemas.
 *
 * Every response is parsed at the boundary rather than cast. An endpoint that
 * changes shape then fails loudly in one place instead of becoming `undefined`
 * three components deep.
 *
 * pydantic is the source of truth (CORE-0006); `pnpm contracts:check` compares
 * these against the live OpenAPI document, so drift is a failing check rather
 * than a runtime surprise.
 */
import { z } from "zod";

"""

    # Class-level comments
    class_comments = {
        "Health": "/** Is anybody driving? `clock.status` is the daemon's word; this is the evidence (SIM-0002). */",
    }

    for name, model in models_to_generate.items():
        print(f"Generating zod schema for {name}...")

        # Get the model fields
        fields = model.model_fields
        zod_schema = ""

        # Add class comment if we have one
        if name in class_comments:
            zod_schema += class_comments[name] + "\n"

        zod_schema += f"export const {name} = z.object({{\n"

        for field_name, field_info in fields.items():
            # Check if we have a custom comment/override for this field
            custom_line = get_field_comment(field_name, name)
            if custom_line and ":" in custom_line:
                # This is a complete field override
                zod_schema += custom_line + "\n"
            else:
                # Add comment before the field if we have one
                if custom_line:
                    zod_schema += custom_line + "\n"

                # Generate the field
                field_type = field_info.annotation
                zod_type = python_type_to_zod(field_type, field_info)
                zod_schema += f"  {field_name}: {zod_type},\n"

        zod_schema += "});\n"
        zod_schemas += zod_schema
        zod_schemas += f"export type {name} = z.infer<typeof {name}>;\n\n"

    # Add ORG_COLORS constant
    zod_schemas += """export const ORG_COLORS: Record<string, string> = {
  tallybird: "#7c9cff",
  halloran: "#c9a227",
  ledgerline: "#5bb98c",
  thirdrail: "#e0757c",
};
export * from "./world";
"""

    # Write to file
    output_file = output_dir / "index.ts"
    output_file.write_text(zod_schemas)

    print(f"Generated zod schemas to {output_file}")
    print("Contract generation complete!")

except ImportError as e:
    print(f"Failed to import required modules: {e}")
    sys.exit(1)
except Exception as e:
    print(f"Error during generation: {e}")
    import traceback

    traceback.print_exc()
    sys.exit(1)

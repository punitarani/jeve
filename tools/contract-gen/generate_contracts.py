#!/usr/bin/env python3
"""Generate TypeScript contracts from pydantic models.

This script generates TypeScript types and zod schemas from the pydantic models
in the tools/contract-gen/models.py file, ensuring that the TypeScript contracts
stay in sync with the Python source of truth.
"""

import sys
import os
from pathlib import Path
from typing import Any, Dict, Type, get_type_hints, get_origin, get_args
import inspect

# Add the src directory to the path
py_dir = Path(__file__).parent.parent.parent / "py"
os.chdir(py_dir)
sys.path.insert(0, str(py_dir / "src"))

try:
    from pydantic_zod_codegen import emit_typescript, normalise_for_json2ts
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

    print("Generating TypeScript contracts from pydantic models...")

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

    output_dir = (
        Path(__file__).parent.parent.parent
        / "packages"
        / "contracts"
        / "src"
        / "generated"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate TypeScript for each model
    generated_files = []
    for name, model in models_to_generate.items():
        print(f"Generating {name}...")

        # Get JSON schema from pydantic model
        schema = model.model_json_schema()

        # Normalize for json2ts
        normalized = normalise_for_json2ts(schema)

        # Generate TypeScript
        typescript_output = emit_typescript(normalized, name_hint=name)

        # Write to file
        output_file = output_dir / f"{name.lower()}.ts"
        output_file.write_text(typescript_output)
        generated_files.append(output_file)

        print(f"  Generated {output_file}")

    # Create index file that exports everything
    index_content = """// Generated TypeScript contracts from pydantic models
// This file is auto-generated - do not edit manually

"""
    for name in models_to_generate:
        index_content += f'export * from "./{name.lower()}";\n'

    # Add the ORG_COLORS constant (not a pydantic model, so we need to add it manually)
    index_content += """
export const ORG_COLORS: Record<string, string> = {
  tallybird: "#7c9cff",
  halloran: "#c9a227",
  ledgerline: "#5bb98c",
  thirdrail: "#e0757c",
};
"""

    index_file = output_dir / "index.ts"
    index_file.write_text(index_content)

    # Create a zod schemas file that imports the types
    zod_content = """// Generated zod schemas from pydantic models
// This file is auto-generated - do not edit manually

import { z } from "zod";
import * as types from "./types.js";

// Zod schemas for runtime validation
export const Clock = z.object({
  sim_time: z.number().int(),
  label: z.string(),
  day: z.number().int(),
  weekday: z.number().int(),
  in_office_hours: z.boolean(),
  tick_seq: z.number().int(),
  status: z.enum(["running", "paused", "paused_budget", "waiting_on_model", "halted"]),
  speed: z.number(),
  run_id: z.string(),
});

export const Org = z.object({
  id: z.string(),
  name: z.string(),
  kind: z.enum(["software", "law", "accounting", "cafe"]),
  cash_cents: z.number().int(),
  receivable_cents: z.number().int(),
});

export const Module = z.object({
  id: z.string(),
  name: z.string(),
  status: z.enum(["up", "down"]),
});

export const Health = z.object({
  heartbeat_age_s: z.number().nullable(),
  lag_s: z.number(),
  last_error: z.string().nullable(),
  stale: z.boolean(),
});

export const WorldState = z.object({
  seq: z.number().int(),
  clock: Clock,
  health: Health,
  orgs: z.array(Org),
  modules: z.array(Module),
  tickets: z.object({ untriaged: z.number().int(), open: z.number().int() }),
  unpaid_invoices: z.object({ n: z.number().int(), cents: z.number().int() }),
  persons: z.record(z.string(), z.number().int()),
});

export const SimEvent = z.object({
  seq: z.number().int(),
  sim_time: z.number().int(),
  tick_seq: z.number().int().optional(),
  kind: z.string(),
  actor_id: z.string().nullable(),
  org_id: z.string().nullable(),
  payload: z.record(z.string(), z.unknown()),
  causes: z.array(z.number().int()),
  label: z.string().optional(),
  depth: z.number().int().optional(),
});

export const EventPage = z.object({
  events: z.array(SimEvent),
  seq: z.number().int(),
});

export const CausalChain = z.object({
  root: z.number().int(),
  direction: z.enum(["up", "down"]),
  events: z.array(SimEvent),
});

export const Person = z.object({
  id: z.string(),
  org_id: z.string().nullable(),
  name: z.string(),
  role: z.string(),
  kind: z.enum(["staff", "counterparty"]),
  traits: z.record(z.string(), z.number()).nullable(),
  decision_seq: z.number().int().optional(),
  status: z.string().optional(),
});

export const Decision = z.object({
  id: z.number().int(),
  decision_seq: z.number().int(),
  sim_time: z.number().int(),
  label: z.string().optional(),
  question_set: z.string(),
  source: z.enum(["rules", "jev", "llm"]),
  distributions: z.record(z.string(), z.record(z.string(), z.number())),
  prng_path: z.string(),
  draws: z.record(z.string(), z.number()),
  chosen: z.record(z.string(), z.unknown()),
  model_call: z.string().nullable(),
});

export const PersonDecisions = z.object({
  person: Person,
  decisions: z.array(Decision),
});

export const PerSimDay = z.object({
  usd: z.number(),
  usd_per_100_persons: z.number(),
  usd_per_10_orgs: z.number(),
  usd_per_1000_events: z.number(),
});

export const Economics = z.object({
  spend_usd: z.number(),
  spend_is_estimated_calls: z.number().int(),
  model_calls: z.number().int(),
  input_tokens: z.number().int(),
  sim_days: z.number(),
  counts: z.record(z.string(), z.number().int()),
  per_sim_day: PerSimDay,
  without_dedup: z.object({ spend_usd: z.number(), per_sim_day: PerSimDay }),
  dedup_rate: z.number(),
  unpriced_decisions: z.number().int(),
  decisions_by_model: z.array(
    z.object({
      model: z.string(),
      decisions: z.number().int(),
      calls: z.number().int(),
    }),
  ),
  by_kind: z.array(
    z.object({
      kind: z.string(),
      source: z.string(),
      decisions: z.number().int(),
      calls: z.number().int(),
      usd: z.number(),
    }),
  ),
  note: z.string(),
});
"""

    zod_file = output_dir / "schemas.ts"
    zod_file.write_text(zod_content)

    print(f"  {zod_file}")
    print("\nContract generation complete!")

except ImportError as e:
    print(f"Failed to import required modules: {e}")
    print("Make sure pydantic-zod-codegen is installed: uv add pydantic-zod-codegen")
    sys.exit(1)
except Exception as e:
    print(f"Error during generation: {e}")
    import traceback

    traceback.print_exc()
    sys.exit(1)

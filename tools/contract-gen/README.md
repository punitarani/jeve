# Contract Generation

Generates the TypeScript zod schemas in `packages/contracts/src/index.ts` from
the pydantic models in `py/src/jeve/api/contracts.py` — the single source of
truth for what the API serves.

## Usage

```bash
make contracts            # regenerate (nx run contracts:generate)
make contracts-check      # regenerate and fail if the committed file differs
```

## How drift is caught

Two directions, both failing checks:

* **models → schema**: `contracts:check-drift` regenerates `index.ts` and
  fails CI if the committed file differs from what the models produce.
* **schema → reality**: `py/tests/test_api.py` validates live endpoint
  responses against the same pydantic models, so a shape the model forgot is
  a failing test. The browser also parses every response with the generated
  zod schemas, so drift that reaches it fails at the boundary.

## Conventions

* Field-level `Field(description=...)` and model docstrings become `/** */`
  comments in the generated file.
* A required `X | None` field generates `.nullable()`; a field with a default
  generates `.optional()` — matching the wire, where the API omits keys rather
  than sending JSON null.
* `MODELS` in `contracts.py` is the emission order: dependencies come before
  the schemas that reference them (zod consts read their references at module
  load).
* `ORG_COLORS` is emitted as a constant, not a schema.

## Maintenance

When API contracts change:

1. Update the models in `py/src/jeve/api/contracts.py`.
2. Run `make contracts` and commit the regenerated `index.ts`.
3. The contract test in `test_api.py` will fail if the wire shape and the
   model disagree.

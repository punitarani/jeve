# Contract Generation

Automated generation of TypeScript zod schemas from pydantic models.

## Overview

This tool ensures that TypeScript contracts stay synchronized with Python backend models by generating zod schemas directly from pydantic definitions.

## Structure

- `models.py` - Pydantic models defining API contracts
- `generate_zod.py` - Script that generates zod schemas from pydantic models

## Usage

```bash
# Generate contracts
cd py && uv run python ../tools/contract-gen/generate_zod.py

# Or use the Nx target
npx nx run contracts:generate

# Or use Make
make contracts
```

## Features

- **Type Safety**: Generates zod schemas with proper TypeScript types
- **Semantic Preservation**: Maintains optional vs nullable field distinctions
- **Documentation**: Preserves comments and explanations from original schemas
- **Deterministic**: Reproducible output for drift detection

## Integration

The generated schemas are used by:
- Frontend applications for API response validation
- Type checking to ensure type safety
- CI to detect drift between Python and TypeScript contracts

## Maintenance

When API contracts change:
1. Update the pydantic models in `models.py`
2. Run `make contracts` to regenerate schemas
3. Commit both the model changes and generated schemas
4. CI will validate that schemas are in sync

## Drift Detection

The system includes drift detection to ensure contracts stay synchronized:

```bash
# Check if contracts are up to date
make contracts-check

# This will fail if the generated schemas differ from what's committed
```

This ensures that:
- Pydantic models are the single source of truth
- TypeScript schemas never drift from Python definitions
- Contract changes are explicit and reviewed
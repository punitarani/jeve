# Python Development Standards

Python code in this project follows strict conventions to maintain quality and consistency.

## Standards

- **Python Version**: Python 3.14
- **Type Hints**: Full type hints required on all functions and methods
- **Package Manager**: `uv` for dependency management
- **Data Validation**: Pydantic at all boundaries (API, database, external interfaces)
- **Linting**: `ruff` for linting and formatting
- **Type Checking**: `mypy --strict` for static type checking
- **Philosophy**: Stdlib-first approach - prefer standard library over external dependencies

## Project Structure

The Python codebase follows a layered architecture:

```
py/src/jeve/
├── core/        # Core domain models and interfaces
├── llm/         # Model gateway and catalog
├── decide/      # Decision policy and question sets
├── world/       # Simulation engine and flows
├── memory/      # Relational memory and beliefs
├── gen/         # Prose generation (never imported by world computation)
├── sim/         # Run loop and orchestration
└── api/         # API endpoints
```

## Testing

- Every module must be testable without network access
- Real model calls are isolated in `jeve.llm` and tests marked `@live`
- Layering is enforced by `tests/test_layering.py`

## Import Constraints

- **Nothing that computes the world may import `jeve.gen`** - prose generation is a projection
- All imports respect the layered architecture (contracts → world → decide/memory → gen → sim/api)
- Circular dependencies are prevented by the layering test

## Common Commands

```bash
# Run type checking
cd py && mypy --strict src/jeve

# Run linting
cd py && ruff check src/jeve

# Run tests
cd py && pytest

# Run specific test with network access
cd py && pytest tests/test_live.py -m live
```

## Database

Production is PlanetScale Postgres on an eighth of a vCPU and one gigabyte.
Growth, not traffic, is what breaks it.

- **Hot paths are O(1) or an index range.** Anything read per tick, per model
  call or per page poll must not scan a growing table (`events`, `decisions`,
  `ledger_entries`, `ledger_txns`, `spend_entries`). A total that a journal
  can rebuild beats a fold over the journal (LLM-0010).
- **`tests/test_query_plans.py` is the gate.** Every new hot query goes in
  the list; it fails when no index can serve the query.
- **Migrations are plain SQL, one transaction each, never idempotent.** No
  `CONCURRENTLY`. A new table needs no `GRANT`: the app role is a member of
  `pg_write_all_data`. The schema-rewind test in `tests/test_episodes.py`
  must undo every migration from 0009 on, so extend it with yours.
- **Measure before and after.** PlanetScale Insights sorted by CPU time, and
  `EXPLAIN (ANALYZE, BUFFERS)` through the read-only role, are the numbers;
  a local database is too small to show a plan the planner will pick at size.

## Key Constraints

- No parallel abstractions "in case" - one way to do each thing
- Prefer deleting code to adding configuration
- Comments explain *why*, not *what*, and reference the incident that justified the code
- Every module testable without network (except explicitly marked live tests)
"""Typed settings, read from the environment once.

Loading is explicit: nothing here reads a .env file. The Makefile passes
`uv run --env-file .env` when the file exists, and a clean clone runs in replay
mode where no key is needed.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from jeve.errors import ConfigError

# LLM-0004: the ladder. Crossing a rung changes what the gateway will authorise.
EXPLORE_CEILING_USD = 12.0
HALT_CEILING_USD = 16.0
HARD_CEILING_USD = 20.0
# One process may not spend more than this, whatever the ladder says. A loop
# that re-issues the same call should cost a dollar, not the night.
RUN_CAP_USD = 1.0


class Settings(BaseModel):
    """Everything the process needs from its environment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    ops_dir: Path = Field(default=Path("ops"))

    explore_ceiling_usd: float = EXPLORE_CEILING_USD
    halt_ceiling_usd: float = HALT_CEILING_USD
    hard_ceiling_usd: float = HARD_CEILING_USD
    run_cap_usd: float = RUN_CAP_USD
    # LLM-0007: the ladder is a guardrail, not the stop — OpenRouter's cap is.
    # Set high in production; the daemon answers a 402 with waiting_on_budget.
    cors_origins: tuple[str, ...] = ()
    dialogue_generate: bool = True

    # LLM-0008: observability. The key is the switch — absent, `jeve.tracing`
    # never imports the SDK and opens no socket, which is what keeps CI and a
    # clean clone offline.
    braintrust_api_key: str | None = None
    braintrust_project: str = "jeve"
    tracing_enabled: bool = True

    @property
    def spend_path(self) -> Path:
        return self.ops_dir / "spend.json"

    def require_api_key(self) -> str:
        if not self.openrouter_api_key:
            raise ConfigError(
                "OPENROUTER_API_KEY is not set. Live calls need it; "
                "replay runs do not — pass a replay gateway instead."
            )
        return self.openrouter_api_key


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up to the directory holding `.git`.

    The spend ledger must be one file for the whole project. Resolving `ops/`
    against the current directory would give the simulation and a script run
    from `py/` two different ledgers and two different ceilings.
    """

    here = (start or Path(__file__)).resolve()
    for candidate in (here, *here.parents):
        if (candidate / ".git").exists():
            return candidate
    return Path.cwd()


def load_settings(*, ops_dir: Path | None = None) -> Settings:
    """Read settings from os.environ.

    Absent credentials are not an error here. Only issuing a live call is.
    """

    base_url = os.environ.get("OPENROUTER_BASE_URL") or "https://openrouter.ai/api/v1"
    override = os.environ.get("JEVE_OPS_DIR")
    if ops_dir is not None:
        root = ops_dir
    elif override:
        root = Path(override)
    else:
        root = find_repo_root() / "ops"

    def _usd(name: str, default: float) -> float:
        return float(os.environ.get(name) or default)

    return Settings(
        openrouter_api_key=os.environ.get("OPENROUTER_API_KEY") or None,
        openrouter_base_url=base_url.rstrip("/"),
        ops_dir=root,
        run_cap_usd=_usd("JEVE_RUN_CAP_USD", RUN_CAP_USD),
        explore_ceiling_usd=_usd("JEVE_EXPLORE_CEILING_USD", EXPLORE_CEILING_USD),
        halt_ceiling_usd=_usd("JEVE_HALT_CEILING_USD", HALT_CEILING_USD),
        hard_ceiling_usd=_usd("JEVE_HARD_CEILING_USD", HARD_CEILING_USD),
        cors_origins=tuple(
            origin.strip()
            for origin in os.environ.get("JEVE_CORS_ORIGINS", "").split(",")
            if origin.strip()
        ),
        dialogue_generate=os.environ.get("JEVE_DIALOGUE_GENERATE", "on")
        not in ("off", "0", "false"),
        braintrust_api_key=os.environ.get("BRAINTRUST_API_KEY") or None,
        braintrust_project=os.environ.get("BRAINTRUST_PROJECT") or "jeve",
        tracing_enabled=os.environ.get("JEVE_TRACING", "on")
        not in ("off", "0", "false"),
    )

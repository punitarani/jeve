"""One of everything to a Sentry project, so a deploy can be checked (CORE-0012).

    make sentry-probe                 # the daemon's project (SENTRY_DSN_SIM)
    make sentry-probe SERVICE=api     # the API's (SENTRY_DSN_API)

Sends one issue, one span, one metric and one log line, flushes, and says what
it sent. Nothing about the world is touched: no database, no model. Run it
under the same env the process runs with — `doppler run --project worker
--config prd -- make sentry-probe` — and then look in the project. The issue
it files is a `ProbeError`, unmistakably a probe; resolve it once seen.

Exit 2 means no DSN for that service reached this process, which is the
failure the probe exists to catch: a key that sat in Doppler and never
reached Fly went unnoticed for an hour once (LLM-0008).
"""

from __future__ import annotations

import sys

from jeve import telemetry
from jeve.telemetry import Service


class ProbeError(RuntimeError):
    """Deliberate. Filed to prove the road to the project is open."""


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args and args[0] not in ("api", "sim"):
        print(f"usage: sentry_probe.py [api|sim] (not {args[0]!r})", file=sys.stderr)
        return 2
    service: Service = "api" if args and args[0] == "api" else "sim"

    if not telemetry.init(service):
        print(
            f"no DSN for {service}: set SENTRY_DSN_{service.upper()} (or SENTRY_DSN)",
            file=sys.stderr,
        )
        return 2

    with telemetry.span(
        "probe", {"sentry.op": "probe", "probe.service": service}, root=True
    ) as span:
        span.set({"probe.ok": True})
        telemetry.count("jeve.probe", 1, attributes={"service": service})
        telemetry.log("info", "jeve sentry probe", attributes={"service": service})
        try:
            raise ProbeError(f"jeve sentry probe for {service}: resolve me")
        except ProbeError as error:
            telemetry.capture(error, tags={"probe": "true"})
    telemetry.flush()

    print(
        f"sent to the {service} project: one ProbeError issue, one `probe` span, "
        "one `jeve.probe` count, one info log. Give it a minute, then look."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

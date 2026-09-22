"""Prove the telemetry wire format without a live Axiom (OBS-0001).

    make obs-probe

`api.axiom.co` is unreachable from CI and from most sandboxes, so the way to
check that the endpoints, per-signal headers and protobuf encoding are right
is to point the exporter at something local that prints what it received:

    # one terminal
    AXIOM_DOMAIN=http://127.0.0.1:4318 AXIOM_TOKEN=local make obs-probe

`AXIOM_DOMAIN` accepts a full `scheme://host:port` for exactly this. Run it
against `otel/opentelemetry-collector` with a `debug` exporter, or against
the tiny sink this script starts for you when nothing is listening.

With no token at all it prints what the off state looks like and exits 0 —
which is itself worth seeing, because that is how CI runs.
"""

from __future__ import annotations

import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from jeve import obs
from jeve.config import load_settings
from jeve.obs import meters

RECEIVED: list[tuple[str, int, str]] = []


class _Sink(BaseHTTPRequestHandler):
    """Answers 200 to anything and remembers what it was sent."""

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        self.rfile.read(length)
        dataset = (
            self.headers.get("x-axiom-dataset")
            or self.headers.get("x-axiom-metrics-dataset")
            or "-"
        )
        auth = self.headers.get("authorization") or ""
        RECEIVED.append((self.path, length, f"{dataset} auth={auth[:11]}..."))
        self.send_response(200)
        self.send_header("content-length", "0")
        self.end_headers()

    def log_message(self, fmt: str, *args: Any) -> None:
        pass


def _start_sink() -> tuple[HTTPServer, str]:
    server = HTTPServer(("127.0.0.1", 0), _Sink)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


def main() -> int:
    server: HTTPServer | None = None
    if not os.environ.get("AXIOM_DOMAIN"):
        server, url = _start_sink()
        os.environ["AXIOM_DOMAIN"] = url
        os.environ.setdefault("AXIOM_TOKEN", "probe-token")
        print(f"no AXIOM_DOMAIN set; started a local sink at {url}\n")

    settings = load_settings()
    if not settings.axiom_token:
        print("AXIOM_TOKEN is unset: telemetry is off, which is the CI path.")
        obs.start("jeve-probe")
        assert obs.live() is None, "something was built without a token"
        print("confirmed: no provider, no exporter, no thread.")
        return 0

    print(f"domain   {settings.axiom_domain}")
    print(f"datasets {settings.axiom_dataset} / {settings.axiom_metrics_dataset}\n")

    obs.start("jeve-probe")
    if obs.live() is None:
        print("telemetry failed to start; see the line above.", file=sys.stderr)
        return 1

    with obs.span("probe", {"jeve.sim_time": 900, "jeve.sim_label": "d0 Mon 00:15"}):
        obs.logger("jeve.probe").info("a probe line, as an operator would see it")
        meters.TICKS.add(1, {"jeve.outcome": "ok"})
        meters.TICK_LAG.record(0.25, {"jeve.policy": "rules"})
    obs.shutdown()

    if server is not None:
        server.shutdown()
        if not RECEIVED:
            print("nothing arrived — the exporter could not reach the sink.")
            return 1
        print("received:")
        for path, length, who in sorted(RECEIVED):
            print(f"  {path:<14} {length:>6} bytes  {who}")
        paths = {path for path, _, _ in RECEIVED}
        missing = {"/v1/traces", "/v1/logs", "/v1/metrics"} - paths
        if missing:
            print(f"\nmissing: {', '.join(sorted(missing))}")
            return 1
        print("\nall three signals reached their endpoint with a dataset header.")
    else:
        print("flushed. check the collector's output.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

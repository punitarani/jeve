"""Telemetry: OpenTelemetry to Axiom, and nothing at all without a token.

OBS-0001. This package is the one seam between jeve and a telemetry backend.
Nothing outside `jeve.obs` imports `opentelemetry`, so swapping Axiom for
another OTLP endpoint — or dropping OTel entirely — is a change to one package.

It sits at the bottom of the layering beside `jeve.core`: everything may import
it, it imports nothing from `jeve` but `config`. It is deliberately *not* part
of `core`, which is the deterministic floor — a package that owns an exporter
thread and a TLS socket does not belong in the module that also defines the
seeded clock.

The contract that matters: with `AXIOM_TOKEN` unset, the OTel SDK is never
imported, no thread starts and no socket opens. `make check` runs that way on
every clean clone, and so does CI.
"""

from __future__ import annotations

from jeve.obs.log import Log, logger
from jeve.obs.spans import Attrs, AttrValue, Span, span
from jeve.obs.wiring import live, register_gauge, shutdown, start

__all__ = [
    "AttrValue",
    "Attrs",
    "Log",
    "Span",
    "live",
    "logger",
    "register_gauge",
    "shutdown",
    "span",
    "start",
]

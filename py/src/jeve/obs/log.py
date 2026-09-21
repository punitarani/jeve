"""One line to the terminal, one record to Axiom.

The rule that protects every runbook: **stdout gets the message, verbatim.**
Structured fields go only into the OTLP record's attributes. Every line this
replaces already interpolates its numbers into the human sentence, so `fly logs`
shows exactly what it showed before, and `tests/test_daemon.py`'s three capsys
assertions keep passing unchanged. The stream matters as much as the text: a
warning that moved from stderr to stdout is a broken runbook.

We do not install `opentelemetry.sdk._logs.LoggingHandler` on the root logger.
That is the recursion trap — an export failure logs, the log emits a record, the
record is exported. Records are emitted directly here instead, which also means
jeve never bridges stdlib `logging` and there stays one path from a jeve module
to an operator's screen.
"""

from __future__ import annotations

import sys
import time
from typing import IO, TYPE_CHECKING

from jeve.obs import wiring

if TYPE_CHECKING:
    from jeve.obs.spans import Attrs


class Log:
    """A named writer. `info` goes to stdout; `warn` and `error` to stderr."""

    __slots__ = ("_scope",)

    def __init__(self, scope: str) -> None:
        self._scope = scope

    def info(self, message: str, attrs: Attrs | None = None) -> None:
        self._write(message, attrs, sys.stdout, 9, "INFO")

    def warn(self, message: str, attrs: Attrs | None = None) -> None:
        self._write(message, attrs, sys.stderr, 13, "WARN")

    def error(self, message: str, attrs: Attrs | None = None) -> None:
        self._write(message, attrs, sys.stderr, 17, "ERROR")

    def _write(
        self,
        message: str,
        attrs: Attrs | None,
        stream: IO[str],
        severity: int,
        label: str,
    ) -> None:
        # flush because a forever-running process under an init system block
        # buffers stdout; fly.toml sets PYTHONUNBUFFERED for the same reason,
        # and this makes a local run behave like production without it.
        print(message, file=stream, flush=True)

        # Resolved per call, never cached: modules build their Log at import
        # time, which is before start() has run.
        state = wiring.live()
        if state is None:
            return
        from opentelemetry._logs import SeverityNumber

        state.emitter.emit(
            timestamp=time.time_ns(),
            severity_number=SeverityNumber(severity),
            severity_text=label,
            body=message,
            attributes={"jeve.scope": self._scope, **(attrs or {})},
        )


def logger(scope: str) -> Log:
    """A writer tagged with where it writes from, e.g. `jeve.sim`."""

    return Log(scope)

"""Braintrust spans for every model call. Off unless a key is set (LLM-0008).

A module rather than a package, for the same reason `config.py` and `db.py`
are: it cuts across the layering instead of sitting in it, and
`tests/test_layering.py` places packages.

Three properties are load-bearing, and each has a test:

- **Off by default.** With no `BRAINTRUST_API_KEY`, `braintrust` is never
  imported, no socket is opened, and `span()` yields a null span. The key is
  the only switch — a second one would be a second way to say the same thing.
  A clean clone and CI stay offline with nothing to configure.
- **Never fatal.** Every call into the SDK is wrapped. The first failure prints
  one line and latches tracing off for the rest of the process. Telemetry must
  not be able to halt a tick: `gateway._log_discrepancy` exists because an
  unwritable ops dir once killed a decision call on Fly, and this is that rule
  again.
- **A pure side effect.** Spans *read* what was sent; they never rebuild it.
  The bytes on the wire are the cache key (DECIDE-0004), so a span that
  re-serialised a request would silently re-bill every call.
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from types import TracebackType
from typing import Any, Protocol

from jeve.config import Settings, load_settings


class Span(Protocol):
    """The part of a span callers touch."""

    def log(self, **event: Any) -> None: ...

    def export(self) -> str:
        """An opaque parent handle, or `""` when tracing is off."""
        ...


class SpanContext(Protocol):
    """What a sink hands back: a span bound to a `with` block."""

    def __enter__(self) -> Span: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None: ...


class Sink(Protocol):
    """Where spans go. Braintrust in production, a recorder in tests."""

    def start_span(
        self, name: str, *, type: str | None, parent: str | None, **event: Any
    ) -> SpanContext: ...

    def flush(self) -> None: ...


class _NullSpan:
    """Costs nothing and answers everything. What you get when tracing is off."""

    def log(self, **event: Any) -> None:
        return None

    def export(self) -> str:
        return ""


_NULL: Span = _NullSpan()


class _Guarded:
    """A span whose failures stop here rather than reaching the caller."""

    __slots__ = ("_inner",)

    def __init__(self, inner: Span) -> None:
        self._inner = inner

    def log(self, **event: Any) -> None:
        try:
            self._inner.log(**event)
        except Exception as error:
            _disable(error)

    def export(self) -> str:
        try:
            return self._inner.export()
        except Exception as error:
            _disable(error)
            return ""


class _BraintrustSink:
    """The real sink. Imports the SDK only once tracing is known to be on."""

    DEFAULT_PROJECT = "jeve"

    def __init__(self, *, project_id: str | None, api_key: str) -> None:
        import braintrust
        from braintrust.span_types import SpanTypeAttribute

        self._braintrust = braintrust
        self._types = SpanTypeAttribute
        # `init_logger` resolves its login lazily, so this opens no socket and
        # a wrong key costs nothing until a span is actually written. The
        # default `async_flush=True` batches on a background thread, which is
        # what a daemon that runs for days needs.
        #
        # One of the two, never both. `_compute_logger_metadata` branches on
        # which is None: an id alone is looked up (`get_project_id`), a name
        # alone is created or resolved (`post_project`) — but *both* takes a
        # third branch that trusts the id verbatim and never calls the API at
        # all. A stale or foreign id would then be accepted here, travel on
        # every row, and be rejected server-side; the batch is dropped on a
        # background thread and nothing reaches us. The branch buys the
        # validation. Passing neither resolves to no object and surfaces much
        # later as an assertion inside span export.
        if project_id:
            braintrust.init_logger(project_id=project_id, api_key=api_key)
        else:
            braintrust.init_logger(project=self.DEFAULT_PROJECT, api_key=api_key)

    def start_span(
        self, name: str, *, type: str | None, parent: str | None, **event: Any
    ) -> SpanContext:
        span_type = self._types(type) if type is not None else None
        started: SpanContext = self._braintrust.start_span(
            name=name, type=span_type, parent=parent, **event
        )
        return started

    def flush(self) -> None:
        # braintrust's own `flush()` carries no return annotation, so --strict
        # calls it untyped. Narrower than silencing the whole package.
        self._braintrust.flush()  # type: ignore[no-untyped-call]


_sink: Sink | None = None
_looked = False
_off = False
# `span()` is called from the engine thread and from the gateway's own loop
# thread (`JevPolicy._Bridge`), so first use can race and two loggers could be
# built. An uncontended lock costs less than the dict the span carries.
_lock = threading.Lock()


def configure(*, settings: Settings | None = None, sink: Sink | None = None) -> bool:
    """Point tracing at a sink. Idempotent; returns whether tracing is live.

    `span()` calls this on first use, so no entry point has to remember to.
    Passing `sink` replaces whatever is there: that is the test seam, and the
    only supported way to see spans without a network.
    """

    global _sink, _looked, _off
    with _lock:
        if sink is not None:
            _sink, _looked, _off = sink, True, False
            return True
        if _looked:
            return _sink is not None
        _looked = True
        try:
            resolved = settings or load_settings()
            if not resolved.braintrust_api_key:
                return False
            _sink = _BraintrustSink(
                project_id=resolved.braintrust_project_id,
                api_key=resolved.braintrust_api_key,
            )
            return True
        except Exception as error:
            _disable(error)
            return False


def enabled() -> bool:
    """Is anything listening? Configures on first call, like `span()` does."""

    return configure()


def reset() -> None:
    """Forget the sink and the warning. Tests only."""

    global _sink, _looked, _off
    _sink, _looked, _off = None, False, False


def flush() -> None:
    """Push buffered spans. Called where a process or a gateway winds down."""

    sink = _sink
    if sink is None:
        return
    try:
        sink.flush()
    except Exception as error:
        _disable(error)


@contextmanager
def span(
    name: str,
    *,
    type: str | None = None,
    parent: str | None = None,
    **event: Any,
) -> Iterator[Span]:
    """Open a span. Yields a null span when tracing is off or has failed.

    `parent` is a handle from `Span.export()`, and is needed in exactly one
    place: `JevPolicy._Bridge` runs the gateway on its own event loop on its
    own thread, and `asyncio.run_coroutine_threadsafe` copies the context on
    *that* thread, so the batch span opened on the engine thread is invisible
    there. Everywhere else the ambient parent is the right one and this stays
    None.
    """

    if not configure():
        yield _NULL
        return
    sink = _sink
    if sink is None:
        yield _NULL
        return
    try:
        context = sink.start_span(name, type=type, parent=parent, **event)
        inner = context.__enter__()
    except Exception as error:
        _disable(error)
        yield _NULL
        return
    try:
        yield _Guarded(inner)
    except BaseException as raised:
        # The span records the failure and the failure carries on: a dead model
        # is the daemon's business (SIM-0002), never the tracer's to swallow.
        _close(context, raised)
        raise
    _close(context, None)


def _close(context: SpanContext, raised: BaseException | None) -> None:
    try:
        if raised is None:
            context.__exit__(None, None, None)
        else:
            context.__exit__(type(raised), raised, raised.__traceback__)
    except Exception as error:
        _disable(error)


def _disable(error: Exception) -> None:
    """One warning, then silence. Tracing must never become the loudest thing."""

    global _sink, _looked, _off
    _sink = None
    _looked = True
    if not _off:
        _off = True
        print(f"tracing disabled: {type(error).__name__}: {error}", file=sys.stderr)

"""Errors, traces, metrics and logs to Sentry. Off unless a DSN is set (CORE-0012).

A module rather than a package, for the same reason `tracing.py` is: it cuts
across the layering instead of sitting in it, and `tests/test_layering.py`
places packages. `tracing.py` carries what the model *said* to Braintrust
(LLM-0008); this carries what it cost the *system* — a tick's duration, a
halt's exit code, a 520, a wedged pool — to Sentry. Two backends, two questions.

The three properties LLM-0008 established hold here too, each with a test:

- **Off by default.** With no DSN, `sentry_sdk` is never imported, no thread is
  started and no socket is opened. The DSN is the only switch — `SENTRY_DSN_API`
  for the API, `SENTRY_DSN_SIM` for the daemon, `SENTRY_DSN` as the fallback for
  both. A clean clone and CI stay offline with nothing to configure.
- **Never fatal.** Every call into the SDK is wrapped. The first failure prints
  one line and latches telemetry off for the rest of the process, unbinding the
  client so the SDK's own integrations (ASGI, httpx) go quiet with it. An
  unwritable ops dir once killed a decision call on Fly; telemetry must not be
  able to halt a tick.
- **A pure side effect.** Nothing here rebuilds a request, adds a header to one
  (outbound trace propagation is off: OpenRouter is not part of our trace and
  the bytes on the wire are a cache key, DECIDE-0004) or reads a result back.

One deliberate difference from `tracing.py`: there is no lazy configure. An
entry point names its service — `init("api")` in `jeve.api.app` before the app
is built, `init("sim")` in `jeve.sim.daemon.main` — because the DSN differs by
service and because the FastAPI integration must be in place before routes are
decorated, or every `/causal/{seq}` is a raw URL for the life of the process.

Tracing runs in Sentry's stream mode. The daemon runs for days, its model calls
cross a thread (`JevPolicy._Bridge`), and a crash must not lose the tick that
was in flight: streamed spans are flushed every few seconds, take an explicit
parent, and have no thousand-span ceiling.
"""

from __future__ import annotations

import re
import sys
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from jeve.config import Settings, load_settings

type Service = Literal["api", "sim"]
type Level = Literal["trace", "debug", "info", "warning", "error", "fatal"]


class Parent:
    """An opaque handle to a span, for parenting across a thread.

    `run_coroutine_threadsafe` copies the context on the *loop's* thread, so
    the tick span open on the engine thread is never the current span there.
    `current()` exports it as one of these and `span(parent=...)` attaches to
    it — the same shape `tracing.Span.export()` has for Braintrust.
    """

    __slots__ = ("_span",)

    def __init__(self, span: Any) -> None:
        self._span = span


class Span(Protocol):
    """The part of a span callers touch."""

    def set(self, attributes: Mapping[str, Any]) -> None:
        """Add attributes. Keys are dotted Sentry names: `{"sim.decisions": n}`."""
        ...

    @property
    def parent(self) -> Parent | None:
        """This span as a handle, or None on the null span."""
        ...


class _NullSpan:
    """Costs nothing and answers everything. What you get when telemetry is off."""

    def set(self, attributes: Mapping[str, Any]) -> None:
        return None

    @property
    def parent(self) -> Parent | None:
        return None


_NULL: Span = _NullSpan()


class _Guarded:
    """A span whose failures stop here rather than reaching the caller."""

    __slots__ = ("_inner",)

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def set(self, attributes: Mapping[str, Any]) -> None:
        try:
            self._inner.set_attributes(_clean(attributes))
        except Exception as error:
            _disable(error)

    @property
    def parent(self) -> Parent | None:
        return Parent(self._inner)


@dataclass(slots=True)
class _State:
    service: Service | None = None
    looked: bool = False
    bound: bool = False
    off: bool = False


_state = _State()
# `span()` is called from the engine thread and from the gateway's own loop
# thread; `_disable` may fire on either.
_lock = threading.Lock()

# The ASGI middleware opens the service span before routing, named by URL
# (`http://host/health`); the FastAPI route patch renames it to the template.
# Either form of the two we never want: `/health` is Fly's probe every ten
# seconds, `/stream` is a 900-second SSE body whose "duration" means nothing.
_UNTRACED_ROUTES = re.compile(r"^(?:[a-z]+://[^/]+)?/(?:health|stream)$")


def _service_options(service: Service) -> dict[str, Any]:
    """SDK options that belong to one service. Here, not in the entry point, so
    the test fixture and production configure the API identically."""

    if service != "api":
        return {}
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    return {
        "ignore_spans": [_UNTRACED_ROUTES],
        # A span per middleware layer (CORS, here) is noise on a read endpoint.
        "integrations": [
            StarletteIntegration(middleware_spans=False),
            FastApiIntegration(middleware_spans=False),
        ],
    }


def init(
    service: Service, *, settings: Settings | None = None, **sdk_overrides: Any
) -> bool:
    """Bind this process to its Sentry project. Returns whether telemetry is live.

    First call wins: a later call is a no-op that returns the current answer.
    That is what lets the API module's import-time call and a test fixture
    coexist, and lets `soak.run_world` call `daemon.main` twice in one process.
    `sdk_overrides` reach `sentry_sdk.init` last; `transport=` is the test seam,
    and the only supported way to see what was sent without a network.
    """

    global _state
    with _lock:
        if _state.looked:
            return _state.bound and not _state.off
        _state.looked = True
        _state.service = service
        try:
            resolved = settings or load_settings()
            own = {"api": resolved.sentry_dsn_api, "sim": resolved.sentry_dsn_sim}
            dsn = own[service] or resolved.sentry_dsn
            if not dsn:
                return False

            # Imported only once telemetry is known to be on: with no DSN this
            # module costs an env read and nothing else.
            import sentry_sdk
            from sentry_sdk.integrations.logging import ignore_logger

            # `enable_logs` forwards stdlib `logging` at INFO and above. uvicorn
            # writes one access line per request and httpx one per call — that
            # would be most of the log volume, saying nothing a span does not.
            for name in ("uvicorn.access", "httpx", "httpcore"):
                ignore_logger(name)

            options: dict[str, Any] = {
                "dsn": dsn,
                "environment": resolved.sentry_environment,
                "release": resolved.sentry_release,
                "traces_sample_rate": 1.0,
                "trace_lifecycle": "stream",
                "enable_logs": True,
                "enable_metrics": True,
                "send_default_pii": False,
                # Never add `sentry-trace`/`baggage` to an outbound request:
                # OpenRouter is not part of our trace, and a header on a call
                # whose bytes are a cache key is one more thing to get wrong.
                # Inbound propagation (the browser's headers) is unaffected.
                "trace_propagation_targets": [],
                **_service_options(service),
                **sdk_overrides,
            }
            sentry_sdk.init(**options)
            # A tag reaches error events; an attribute reaches spans, logs and
            # metrics. Both, so every signal says which process it came from.
            sentry_sdk.get_global_scope().set_tag("service", service)
            sentry_sdk.set_attribute("service", service)
            _state.bound = True
            return True
        except Exception as error:
            _disable_locked(error)
            return False


def enabled() -> bool:
    """Is anything listening? Pure read: this never configures."""

    return _state.bound and not _state.off


def reset() -> None:
    """Unbind the SDK and forget the warning. Tests only.

    Closes the client (its transport worker and the span/log/metric batchers)
    and clears every scope, so the next test starts from nothing. The SDK's
    integrations patch once per process and look up the client on each call,
    so they simply go quiet.
    """

    global _state
    with _lock:
        if _state.bound:
            _unbind()
        _state = _State()


def flush() -> None:
    """Push everything buffered. Called where a process winds down.

    In stream mode spans, logs and metrics sit in batchers until a timer or
    this call moves them; a daemon that exits without it loses its last tick.
    """

    if not enabled():
        return
    try:
        import sentry_sdk

        sentry_sdk.flush(timeout=5.0)
    except Exception as error:
        _disable(error)


@contextmanager
def span(
    name: str,
    attributes: Mapping[str, Any] | None = None,
    *,
    root: bool = False,
    parent: Parent | None = None,
) -> Iterator[Span]:
    """Open a span. Yields a null span when telemetry is off or has failed.

    Child-only by default: with nothing active, a bare `span()` yields the null
    span rather than starting a trace of its own. The stream hub's poll loop and
    the gateway thread both run where nothing is active, and a root per `db`
    call every half second is the kind of trace nobody asked for. `root=True`
    is the one way to start a trace (the tick); `parent=` attaches to a span
    that is not current on this thread (the gateway, under the tick).
    """

    if not enabled():
        yield _NULL
        return
    try:
        from sentry_sdk import traces

        kwargs: dict[str, Any] = {"name": name, "attributes": _clean(attributes)}
        if parent is not None:
            kwargs["parent_span"] = parent._span
        elif root:
            kwargs["parent_span"] = None
        elif traces.get_current_span() is None:
            yield _NULL
            return
        context = traces.start_span(**kwargs)
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


def current() -> Parent | None:
    """The active span as a handle to carry across a thread, or None."""

    if not enabled():
        return None
    try:
        from sentry_sdk import traces

        active = traces.get_current_span()
        return None if active is None else Parent(active)
    except Exception as error:
        _disable(error)
        return None


def count(
    name: str,
    value: float = 1,
    *,
    unit: str | None = None,
    attributes: Mapping[str, Any] | None = None,
) -> None:
    if not enabled():
        return
    try:
        from sentry_sdk import metrics

        metrics.count(name, value, unit=unit, attributes=_clean(attributes))
    except Exception as error:
        _disable(error)


def gauge(
    name: str,
    value: float,
    *,
    unit: str | None = None,
    attributes: Mapping[str, Any] | None = None,
) -> None:
    if not enabled():
        return
    try:
        from sentry_sdk import metrics

        metrics.gauge(name, value, unit=unit, attributes=_clean(attributes))
    except Exception as error:
        _disable(error)


def distribution(
    name: str,
    value: float,
    *,
    unit: str | None = None,
    attributes: Mapping[str, Any] | None = None,
) -> None:
    if not enabled():
        return
    try:
        from sentry_sdk import metrics

        metrics.distribution(name, value, unit=unit, attributes=_clean(attributes))
    except Exception as error:
        _disable(error)


def log(
    level: Level, message: str, *, attributes: Mapping[str, Any] | None = None
) -> None:
    """A structured log line. The `print` beside it is still the human stream."""

    if not enabled():
        return
    try:
        from sentry_sdk import logger

        emit = getattr(logger, level)
        emit(message, attributes=_clean(attributes))
    except Exception as error:
        _disable(error)


def capture(error: BaseException, *, tags: Mapping[str, Any] | None = None) -> None:
    """Report an exception as an issue, tagged. For halts, not for weather."""

    if not enabled():
        return
    try:
        import sentry_sdk

        named = {k: str(v) for k, v in (tags or {}).items() if v is not None}
        sentry_sdk.capture_exception(error, tags=named)
    except Exception as failure:
        _disable(failure)


def status(key: str, value: str) -> None:
    """Name the process's state on everything that follows: errors and signals."""

    if not enabled():
        return
    try:
        import sentry_sdk

        sentry_sdk.set_tag(key, value)
        sentry_sdk.set_attribute(key, value)
    except Exception as error:
        _disable(error)


def _clean(attributes: Mapping[str, Any] | None) -> dict[str, Any]:
    """Span, log and metric attributes take primitives only; None is not one."""

    cleaned: dict[str, Any] = {}
    for key, value in (attributes or {}).items():
        if value is None:
            continue
        cleaned[key] = (
            value if isinstance(value, str | int | float | bool) else str(value)
        )
    return cleaned


def _close(context: Any, raised: BaseException | None) -> None:
    try:
        if raised is None:
            context.__exit__(None, None, None)
        else:
            context.__exit__(type(raised), raised, raised.__traceback__)
    except Exception as error:
        _disable(error)


def _unbind() -> None:
    """Best effort, each step on its own: what fails here is already failing."""

    try:
        import sentry_sdk

        try:
            sentry_sdk.get_client().close(timeout=0)
        except Exception:
            pass
        for scope in (
            sentry_sdk.get_global_scope(),
            sentry_sdk.get_isolation_scope(),
            sentry_sdk.get_current_scope(),
        ):
            try:
                scope.clear()
            except Exception:
                pass
        sentry_sdk.get_global_scope().set_client(None)
    except Exception:
        pass


def _disable(error: Exception) -> None:
    with _lock:
        _disable_locked(error)


def _disable_locked(error: Exception) -> None:
    """One warning, then silence. Telemetry must never become the loudest thing."""

    if _state.off:
        return
    _state.off = True
    print(f"telemetry disabled: {type(error).__name__}: {error}", file=sys.stderr)
    if _state.bound:
        _unbind()
        _state.bound = False

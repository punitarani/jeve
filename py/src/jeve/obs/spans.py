"""A span, or a convincing impression of one.

Attributes are a plain mapping with full, dotted names — `{"jeve.sim_time": n}`,
not keyword arguments that some rule rewrites. Keyword arguments cannot carry a
dot, so any kwargs-based API needs a translation rule, and a translation rule is
a second way to name an attribute. One way: write the name you mean.

Stable OpenTelemetry semantic conventions are used verbatim where they exist
(`http.route`, `db.system.name`, `gen_ai.request.model`); everything specific to
this simulation is prefixed `jeve.`. The names are written as literals rather
than imported from `opentelemetry.semconv`, because the `gen_ai.*` group still
lives in an underscore-prefixed `_incubating` package that moves between
releases — and a dashboard that breaks on a dependency bump is worse than a
string we own.

No jeve module ever passes a `start_time`: the SDK stamps spans off the wall
clock inside site-packages. That is how CORE-0003 is kept structurally rather
than by discipline — sim time reaches a span only as the `jeve.sim_time`
attribute, never as a timestamp.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from jeve.obs import wiring

if TYPE_CHECKING:
    from opentelemetry.trace import Span as OtelSpan

type AttrValue = str | bool | int | float
type Attrs = Mapping[str, AttrValue]


class Span:
    """The handle a `with obs.span(...)` block yields.

    Wrapping OpenTelemetry's span rather than re-exporting it keeps the vendor
    name inside this package and gives the off path something to return that
    costs nothing.
    """

    __slots__ = ("_span",)

    def __init__(self, span: OtelSpan | None) -> None:
        self._span = span

    def set(self, attrs: Attrs) -> None:
        """Record what was only knowable once the work was done."""

        if self._span is None:
            return
        for name, value in attrs.items():
            self._span.set_attribute(name, value)

    def fail(self, error: BaseException) -> None:
        """Mark the span as the failure it was, without the traceback.

        `error.type` and the message only: a stack trace is large, repeats on
        every retry, and says nothing the class and the message do not.
        """

        if self._span is None:
            return
        from opentelemetry.trace import Status, StatusCode

        self._span.set_attribute("error.type", type(error).__name__)
        self._span.set_status(Status(StatusCode.ERROR, str(error)[:200]))


_DEAD = Span(None)


@contextmanager
def span(name: str, attrs: Attrs | None = None) -> Iterator[Span]:
    """Open a span, or yield a handle that does nothing.

    An exception leaving the block is recorded and re-raised — the caller's
    error handling is unchanged by being observed.
    """

    state = wiring.live()
    if state is None:
        yield _DEAD
        return
    with state.tracer.start_as_current_span(name) as raw:
        wrapped = Span(raw)
        if attrs:
            wrapped.set(attrs)
        try:
            yield wrapped
        except BaseException as error:
            wrapped.fail(error)
            raise


def current_ids() -> tuple[str, str] | None:
    """`(trace_id, span_id)` as hex, for stitching a log line to its span."""

    state = wiring.live()
    if state is None:
        return None
    from opentelemetry.trace import get_current_span

    context: Any = get_current_span().get_span_context()
    if not context.is_valid:
        return None
    return f"{context.trace_id:032x}", f"{context.span_id:016x}"

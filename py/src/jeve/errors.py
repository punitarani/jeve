"""Typed errors. Every failure the gateway can produce has a name here."""


class JeveError(Exception):
    """Base for everything this project raises deliberately."""


class ConfigError(JeveError):
    """Required configuration is missing or malformed."""


class BudgetExceededError(JeveError):
    """The spend ceiling refuses to authorise another call.

    Raised *before* a request is issued. It is never caught and retried: the
    ceiling is the point.
    """


class ModelResolutionError(JeveError):
    """A configured model name does not exist in OpenRouter's catalogue."""


class TransportError(JeveError):
    """The request did not complete. May or may not have been billed."""


class ProviderBudgetError(JeveError):
    """The upstream refused for money (HTTP 402): the account cap is spent.

    Unbilled — the request never reached inference — and never retried by the
    gateway, because a two-minute backoff cannot refill credits. It is also not
    a halt: the cap resets on its billing window, so the daemon waits it out
    (`waiting_on_budget`, SIM-0003) instead of exiting for an operator.
    """


class ModelVersionDriftError(JeveError):
    """A different build of the model answered than the one the repo is pinned to.

    Not weather (SIM-0002): waiting will not fix it, and carrying on would mix
    two models' answers in one world. Somebody moves the pin, on purpose.
    """


class ResponseShapeError(JeveError):
    """The response completed but did not carry what the caller needs."""

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


class ModelVersionDriftError(JeveError):
    """A different build of the model answered than the one the repo is pinned to.

    Not weather (SIM-0002): waiting will not fix it, and carrying on would mix
    two models' answers in one world. Somebody moves the pin, on purpose.
    """


class ResponseShapeError(JeveError):
    """The response completed but did not carry what the caller needs."""

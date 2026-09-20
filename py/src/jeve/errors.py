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


class ResponseShapeError(JeveError):
    """The response completed but did not carry what the caller needs."""

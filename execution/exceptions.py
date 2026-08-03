"""Execution-layer specific exceptions."""


class OrderValidationError(ValueError):
    """Raised when an order request fails framework-level validation."""


class ExecutionProviderError(RuntimeError):
    """Raised when an execution provider cannot process an order."""


class OrderNotFoundError(LookupError):
    """Raised when a provider cannot locate a previously submitted order."""

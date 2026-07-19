"""Shared workflow control-flow exceptions."""


class BudgetExceededError(RuntimeError):
    """Raised before a model call when the run-level API budget is exhausted."""


class RunCancelledError(RuntimeError):
    """Raised at a safe pipeline boundary after cooperative cancellation."""

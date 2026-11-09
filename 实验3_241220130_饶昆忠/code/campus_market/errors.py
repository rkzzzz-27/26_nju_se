"""Errors returned by the domain and HTTP boundary."""

from __future__ import annotations


class MarketError(Exception):
    """A rejected business operation with a stable public error code."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status

    def as_dict(self) -> dict[str, str]:
        return {"error": self.code, "message": self.message}


def require(condition: bool, code: str, message: str, status: int = 400) -> None:
    """Raise a consistent domain error for a failed precondition."""
    if not condition:
        raise MarketError(code, message, status)

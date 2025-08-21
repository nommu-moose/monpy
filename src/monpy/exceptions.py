from typing import Optional, List, Dict, Any


class MondayAPIError(Exception):
    """Raised when the monday.com API returns either GraphQL or HTTP errors."""

    def __init__(self, message: str, *, errors: Optional[List[Dict[str, Any]]] = None) -> None:
        super().__init__(message)
        self.errors = errors or []

    # Nice-to-have for better debugging / logging
    def __str__(self) -> str:  # pragma: no cover
        base = super().__str__()
        return f"{base} | details: {self.errors}" if self.errors else base


class FeatureNotSupported(MondayAPIError):
    """Raised when the API reports that a specific feature or field is not supported.

    This is used to gracefully skip or branch logic when certain GraphQL fields or
    mutations are unavailable in the current monday.com API version or account plan.
    """
    pass

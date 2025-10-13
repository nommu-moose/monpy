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


# --- Specific error hierarchy (all remain subclasses of MondayAPIError) -----


class NotFound(MondayAPIError):
    """Base class for resource-not-found conditions."""


class WorkspaceNotFound(NotFound):
    pass


class BoardNotFound(NotFound):
    pass


class ColumnNotFound(NotFound):
    pass


class ItemNotFound(NotFound):
    pass


class ParentItemNotFound(NotFound):
    pass


class SubItemNotFound(NotFound):
    pass


class DocNotFound(NotFound):
    pass


class GroupNotFound(NotFound):
    pass


class WebhookNotFound(NotFound):
    pass


class BoardResolutionError(MondayAPIError):
    """Raised when a board identifier cannot be derived for an operation."""
    pass


class ValidationError(MondayAPIError):
    """Base class for client-side validation failures."""
    pass


class EmptyUpdateError(ValidationError):
    pass


class ColumnValueError(ValidationError):
    pass


class PeopleAssignmentError(ValidationError):
    pass


class LinkedItemsLimitExceeded(ValidationError):
    pass


class NetworkError(MondayAPIError):
    pass


class RateLimitError(MondayAPIError):
    pass


class HTTPError(MondayAPIError):
    pass


class GraphQLError(MondayAPIError):
    pass

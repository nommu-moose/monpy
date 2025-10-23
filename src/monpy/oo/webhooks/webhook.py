from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..base import BaseModel


@dataclass
class Webhook(BaseModel):
    """
    Represents a monday.com webhook.
    """

    event: str | None = None
    config: dict[str, Any] | None = field(default=None, repr=False)
    board_id: str | None = None

    def _flush_changes(self) -> None:
        """Webhooks are immutable via the API, so this is a no-op."""
        pass

    def _refresh_from_api(self) -> None:
        """
        Refresh webhook data.

        Note: monday.com API does not support fetching a single webhook by ID.
        This method will do nothing.
        """
        pass

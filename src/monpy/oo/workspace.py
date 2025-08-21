from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .base import BaseModel


@dataclass
class Workspace(BaseModel):
    name: str | None = None
    kind: str | None = None
    description: str | None = None

    def _flush_changes(self) -> None:
        attrs: dict[str, object] = {}
        if "name" in self._dirty:
            attrs["name"] = self.name
        if "kind" in self._dirty:
            attrs["kind"] = self.kind
        if "description" in self._dirty:
            attrs["description"] = self.description
        if attrs:
            self._session.client.update_workspace(self.id, **attrs)

    def _refresh_from_api(self) -> None:
        raw = self._session.client.get_workspace(self.id)
        self.name = raw.get("name")
        self.kind = raw.get("kind")
        self.description = raw.get("description")

    # --- convenience ---------------------------------------------------
    def create_board(self, *, name: str, board_kind: str = "public") -> dict:
        """Create a board inside this workspace and return its metadata dict.

        We return the raw client dict for completeness; callers may wrap it via
        ``self._session.board(bid)`` if they need an OO ``Board`` instance.
        """
        return self._session.client.create_board(name=name, board_kind=board_kind, workspace_id=self.id)



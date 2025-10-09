from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .base import BaseModel
from .columns import ColumnValues


@dataclass
class SubItem(BaseModel):
    name: str | None = None
    state: str | None = None
    updated_at: str | None = None
    board_id: str | None = None
    _values: ColumnValues | None = None

    @property
    def values(self) -> ColumnValues:
        # ColumnValues uses the board’s columns; subitems live on hidden boards
        if self._values is None:
            self._values = ColumnValues(self)
        return self._values

    def _flush_changes(self) -> None:
        col_vals: Dict[str, Any] = self._dirty.get("column_values", {})
        if col_vals:
            # Resolve board_id if missing
            b_id = self.board_id or self._session.client._get_board_id_for_subitem(self.id)
            self._session.client.update_subitem_values(self.id, column_values=col_vals, board_id=b_id)

    # --- convenience APIs ---------------------------------------------
    def set_connected_items(self, *, column_attr: str, linked_item_ids: list[str] | list[int]) -> None:
        # Resolve subitems board and schedule an update
        b_id = self.board_id or self._session.client._get_board_id_for_subitem(self.id)
        col_id = self._session.board(b_id).columns.id_for_attr(column_attr)
        payload = {col_id: {"item_ids": [int(i) for i in linked_item_ids]}}
        # subitem updates are not batched with item updates currently; perform immediately
        self._session.client.update_subitem_values(self.id, column_values=payload, board_id=b_id)

    def _refresh_from_api(self) -> None:
        raw = self._session.client.get_subitem_values(self.id, include_board=True)
        self.name = raw.get("name")
        self.state = raw.get("state")
        self.updated_at = raw.get("updated_at")
        b = raw.get("board")
        if b:
            self.board_id = str(b.get("id"))

    # --- prefetch values ----------------------------------------------
    def prefetch_values(self, *, column_ids: Optional[list[str]] = None) -> None:
        row = self._session.client.get_subitem_values(self.id, include_board=True, column_ids=column_ids)
        try:
            self.name = row.get("name", self.name)
            self.state = row.get("state", self.state)
            self.updated_at = row.get("updated_at", self.updated_at)
            b = row.get("board")
            if b and not self.board_id:
                self.board_id = str(b.get("id"))
        except Exception:
            pass
        self.values.warm_from_row(row)



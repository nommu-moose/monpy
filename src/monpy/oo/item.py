from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .base import BaseModel
from .columns import ColumnValues
from .file_asset import upload_to_file_column, list_files_from_column, download_files_from_column
from .doc import Doc


@dataclass
class Item(BaseModel):
    name: str | None = None
    state: str | None = None
    updated_at: str | None = None
    board_id: str | None = None
    _is_subitem: bool = field(default=False, repr=False)
    _values: ColumnValues | None = field(default=None, repr=False, init=False)

    @property
    def values(self) -> ColumnValues:
        # Persist wrapper so cache survives multiple property accesses
        if self._values is None:
            self._values = ColumnValues(self)
        return self._values

    # --- convenience APIs ---------------------------------------------
    def set_connected_items(self, *, column_attr: str, linked_item_ids: list[str] | list[int]) -> None:
        col_id = self._session.board(self.board_id).columns.id_for_attr(column_attr)
        payload = {col_id: {"item_ids": [int(i) for i in linked_item_ids]}}
        self._session._schedule_item_update(board_id=self.board_id, item_id=self.id, column_values=payload)

    def delete(self) -> None:
        self._session.client.delete_item(self.id)

    def rename(self, name: str) -> None:
        self._session.client.rename_item(self.id, name=name)
        self.name = name

    def archive(self) -> None:
        self._session.client.archive_item(self.id)
        self.state = "archived"

    def unarchive(self) -> None:
        self._session.client.unarchive_item(self.id)
        self.state = "active"

    def duplicate(self, *, with_updates: bool = True, with_assets: bool = True,
                  target_board_id: Optional[str] = None, target_group_id: Optional[str] = None) -> dict:
        return self._session.client.duplicate_item(
            self.id,
            with_updates=with_updates,
            with_assets=with_assets,
            target_board_id=target_board_id,
            target_group_id=target_group_id,
        )

    def move_to_group(self, group_id: str) -> None:
        self._session.client.move_item_to_group(self.id, group_id=group_id)

    def move_to_board(self, board_id: str, *, group_id: Optional[str] = None) -> dict:
        return self._session.client.move_item_to_board(self.id, board_id=board_id, group_id=group_id)

    def _refresh_from_api(self) -> None:
        raw = self._session.client.get_item_values(self.id, include_board=True)
        self.name = raw.get("name")
        self.state = raw.get("state")
        self.updated_at = raw.get("updated_at")
        b = raw.get("board")
        if b:
            self.board_id = str(b.get("id"))

    def _flush_changes(self) -> None:
        # Support batched column value updates
        col_vals: Dict[str, Any] = self._dirty.get("column_values", {})
        if col_vals and self.board_id:
            self._session._schedule_item_update(board_id=self.board_id, item_id=self.id, column_values=col_vals)

    # --- files convenience --------------------------------------------
    def upload_file(self, *, column_attr: str, file_obj, filename: str | None = None, mime_type: str = "application/octet-stream") -> dict:
        col_id = self._session.board(self.board_id).columns.id_for_attr(column_attr)
        return upload_to_file_column(self._session, item_id=self.id, column_id=col_id, file_obj=file_obj, filename=filename, mime_type=mime_type)

    def list_files(self, *, column_attr: str) -> list[dict]:
        col_id = self._session.board(self.board_id).columns.id_for_attr(column_attr)
        return list_files_from_column(self._session, item_id=self.id, column_id=col_id)

    def download_files(self, *, column_attr: str) -> list[bytes]:
        col_id = self._session.board(self.board_id).columns.id_for_attr(column_attr)
        return download_files_from_column(self._session, item_id=self.id, column_id=col_id)

    # --- docs convenience ---------------------------------------------
    def doc(self, *, column_attr: str) -> Doc:
        """Return a lightweight Doc wrapper bound to this item+column context.

        Use with ``Doc.replace_plain_text(..., column_item_id=item.id, column_id=...)``.
        """
        col_id = self._session.board(self.board_id).columns.id_for_attr(column_attr)
        d = Doc(id="_")  # placeholder id
        d._session = self._session
        # The actual operations still pass column context explicitly
        return d

    # --- prefetch values ----------------------------------------------
    def prefetch_values(self, *, column_ids: Optional[list[str]] = None) -> None:
        """Fetch all (or selected) column values at once and warm the OO cache.

        This does not change lazy loading semantics; cached results are used
        when ``Session.values_cache_ttl`` is set and the TTL is not expired.
        """
        row = self._session.client.get_item_values(self.id, include_board=True, column_ids=column_ids)
        # Update basic item metadata from the payload (best-effort)
        try:
            self.name = row.get("name", self.name)
            self.state = row.get("state", self.state)
            self.updated_at = row.get("updated_at", self.updated_at)
            b = row.get("board")
            if b and not self.board_id:
                self.board_id = str(b.get("id"))
        except Exception:
            pass
        # Warm the values cache on the persistent wrapper
        self.values.warm_from_row(row)

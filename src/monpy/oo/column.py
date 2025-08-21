from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from .base import BaseModel
from .utils import to_attr


@dataclass
class Column(BaseModel):
    title: str | None = None
    type: str | None = None
    settings: Dict[str, object] | None = None
    # Present for connect-boards columns when available
    connected_board_ids: Optional[List[str]] = None


class ColumnCollection:
    def __init__(self, board, columns: List[Column]) -> None:
        self._board = board
        self._by_id: Dict[str, Column] = {c.id: c for c in columns}
        self._by_attr: Dict[str, Column] = {}
        for c in columns:
            key = to_attr(c.title or c.id)
            self._by_attr[key] = c

    def by_id(self, column_id: str) -> Column:
        return self._by_id[column_id]

    def by_attr(self, attr_name: str) -> Column:
        return self._by_attr[attr_name]

    def __getattr__(self, name: str) -> Column:
        try:
            return self.by_attr(name)
        except KeyError as exc:
            raise AttributeError(name) from exc

    # --- helpers -------------------------------------------------------
    def has_id(self, column_id: str) -> bool:
        return column_id in self._by_id

    def has_attr(self, attr_name: str) -> bool:
        return attr_name in self._by_attr

    def id_for_attr(self, attr_name: str) -> str:
        return self.by_attr(attr_name).id



from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable


@runtime_checkable
class ColumnDefaults(Protocol):
    def to_dict(self) -> Mapping[str, Any]:
        ...


@dataclass
class ConnectBoardsDefaults:
    board_ids: list[int] | list[str]
    allow_multiple_items: bool | None = None
    allow_create_reflection_column: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"boardIds": [int(i) for i in self.board_ids]}
        if self.allow_multiple_items is not None:
            payload["allowMultipleItems"] = bool(self.allow_multiple_items)
        if self.allow_create_reflection_column is not None:
            payload["allowCreateReflectionColumn"] = bool(self.allow_create_reflection_column)
        return payload



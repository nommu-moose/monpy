from __future__ import annotations

from typing import Iterable

from ..client import MondayClient


def list_item_ids_from_token(token: str, board_id: str, *, include_archived: bool = False) -> list[str]:
    """
    Return item IDs for a board using only an API token.

    Parameters
    ----------
    token
        monday.com user API token.
    board_id
        Target board ID.
    include_archived
        When True, also include archived items.

    Returns
    -------
    list[str]
        All matching item IDs as strings.
    """
    client = MondayClient(token)

    def _states() -> Iterable[str]:
        yield "active"
        if include_archived:
            yield "archived"

    ids: list[str] = []
    for st in _states():
        rows = client.get_all_items(board_id, page_size=200, state=st, fields=("id",))
        ids.extend(str(row.get("id")) for row in rows if row.get("id") is not None)
    return ids


__all__ = [
    "list_item_ids_from_token",
]



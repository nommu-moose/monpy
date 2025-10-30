from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence

from ..client import MondayClient
from ..exceptions import ItemNotFound, MondayAPIError
from .upsert_item import _encode_value_for_type, _ensure_group


def upsert_item_values(
    token: str,
    *,
    board_id: str,
    columns: Sequence[Mapping[str, Any]],
    item_id: Optional[str] = None,
    item_name: Optional[str] = None,
    safe_updates: bool = True,
) -> str:
    """
    Upsert an item on a board using column IDs.

    Parameters
    ----------
    token: str
        monday.com API token.
    board_id: str
        Target board ID.
    columns: list of {"column_id": str, "value": Any}
        Column IDs and values to set. If a column_id is "name", it sets the item name.
        Values are encoded according to each column's type.
    item_id: Optional[str]
        If provided, update this item when it exists; otherwise create a new one.
    item_name: Optional[str]
        Fallback name when creating. Overridden by a provided "name" column entry.
    safe_updates: bool
        When True, use safe update API.

    Returns
    -------
    str: The ID of the upserted item.
    """
    client = MondayClient(token)

    # Fetch column types once to properly encode values
    try:
        cols_meta = client.get_columns(board_id, fields=("id", "type"))
    except MondayAPIError:
        cols_meta = []

    type_by_id: Dict[str, str] = {}
    for c in cols_meta or []:
        try:
            type_by_id[str(c.get("id"))] = str(c.get("type") or "")
        except Exception:
            continue

    # Build values payload and resolve name
    values: Dict[str, Any] = {}
    name_to_set: Optional[str] = None

    for spec in columns or []:
        cid = spec.get("column_id") or spec.get("id")
        if not cid:
            continue
        cid_s = str(cid)
        if cid_s == "name":
            v = spec.get("value")
            if v is not None:
                name_to_set = str(v)
            continue
        col_type = type_by_id.get(cid_s)
        encoded = _encode_value_for_type(col_type, spec.get("value"))
        values[cid_s] = encoded

    if name_to_set is None and item_name:
        name_to_set = str(item_name)

    # Update existing item if possible
    if item_id:
        try:
            client.get_item_values(item_id)
            to_update = dict(values)
            if name_to_set:
                to_update["name"] = name_to_set
            if to_update:
                if safe_updates:
                    client.safe_update_item_values(board_id, item_id, column_values=to_update)
                else:
                    client.update_item_values(board_id, item_id, column_values=to_update)
            return str(item_id)
        except ItemNotFound:
            # fall through to create
            pass

    # Create new item
    gid = _ensure_group(client, board_id)
    created = client.create_item(board_id, group_id=gid, item_name=name_to_set or "", column_values=values)
    return str(created.get("id"))


__all__ = [
    "upsert_item_values",
]



from __future__ import annotations

from typing import Any, Dict, Iterable, Iterator, List, Optional

from ..client import MondayClient
from ..oo import Session


def _yield_all_workspaces(client: MondayClient, *, page_size: int = 100) -> Iterator[Dict[str, Any]]:

    fields = ("id", "name")
    yield from client.iter_workspaces(page_size=page_size, fields=list(fields))


def _yield_all_boards_for_workspace(
    client: MondayClient,
    workspace_id: str,
    *,
    page_size: int = 100,
) -> Iterator[Dict[str, Any]]:

    fields = ("id", "name", "workspace_id")
    yield from client.iter_boards(
        page_size=page_size,
        workspace_id=workspace_id,
        state="active",
        fields=list(fields),
    )


def _list_items_for_board(client: MondayClient, board_id: str, *, page_size: int = 200) -> List[Dict[str, Any]]:

    return client.get_all_items(board_id, page_size=page_size, state="active", fields=["id", "name"])  # type: ignore[list-item]


def _batched_list_items_for_boards(client: MondayClient, board_ids: List[str], *, page_size: int = 200, batch_size: int = 20) -> Dict[str, List[Dict[str, Any]]}:

    result: Dict[str, List[Dict[str, Any]]] = {bid: [] for bid in board_ids}
    # Use existing client.list_items pagination per board, but interleave boards in batches
    # because monday GraphQL doesn't support multi-board items_page in a single call reliably.
    for start in range(0, len(board_ids), batch_size):
        chunk = board_ids[start : start + batch_size]
        # For each board in the chunk, exhaust its iterator (cursor pagination)
        for bid in chunk:
            for row in client.iter_items(bid, page_size=page_size, state="active", fields=["id", "name"]):  # type: ignore[list-item]
                result[bid].append({"id": str(row.get("id")), "name": row.get("name")})
    return result


def build_workspace_board_item_tree(
    session: Session,
    *,
    page_size_workspaces: int = 100,
    page_size_boards: int = 100,
    page_size_items: int = 200,
    items_batch_size: int = 20,
) -> List[Dict[str, Any]]:
    """Return a nested structure of all workspaces -> boards -> items (IDs + names).

    The structure matches:
        [
          {
            "workspace_id": "...",
            "workspace_name": "...",
            "boards": [
              {
                "board_id": "...",
                "board_name": "...",
                "items": [{"item_id": "...", "item_name": "..."}, ...]
              }, ...
            ]
          }, ...
        ]

    Fetching uses the low-level client's iterators for maximal page sizes and
    batches item listing across boards in manageable chunks to respect API limits.
    """

    client = session.client

    # 1) Gather workspaces
    workspaces: List[Dict[str, Any]] = [
        {"id": str(ws.get("id")), "name": ws.get("name")}
        for ws in _yield_all_workspaces(client, page_size=page_size_workspaces)
    ]

    # 2) For each workspace, gather boards (id, name, workspace_id)
    ws_id_to_boards: Dict[str, List[Dict[str, Any]]] = {}
    all_board_ids: List[str] = []
    for ws in workspaces:
        ws_id = ws["id"]
        boards: List[Dict[str, Any]] = []
        for b in _yield_all_boards_for_workspace(client, ws_id, page_size=page_size_boards):
            bid = str(b.get("id"))
            boards.append({
                "id": bid,
                "name": b.get("name"),
            })
            all_board_ids.append(bid)
        ws_id_to_boards[ws_id] = boards

    # 3) Items per board, batched
    board_id_to_items: Dict[str, List[Dict[str, Any]]] = {}
    if all_board_ids:
        board_id_to_items = _batched_list_items_for_boards(
            client,
            all_board_ids,
            page_size=page_size_items,
            batch_size=items_batch_size,
        )

    # 4) Assemble nested structure
    out: List[Dict[str, Any]] = []
    for ws in workspaces:
        ws_id = ws["id"]
        ws_entry: Dict[str, Any] = {
            "workspace_id": ws_id,
            "workspace_name": ws.get("name"),
            "boards": [],
        }
        for b in ws_id_to_boards.get(ws_id, []):
            bid = b["id"]
            items = [
                {"item_id": str(it.get("id")), "item_name": it.get("name")}
                for it in board_id_to_items.get(bid, [])
            ]
            ws_entry["boards"].append(
                {
                    "board_id": bid,
                    "board_name": b.get("name"),
                    "items": items,
                }
            )
        out.append(ws_entry)
    return out


__all__ = [
    "build_workspace_board_item_tree",
]



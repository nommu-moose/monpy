from __future__ import annotations

from typing import Any, Dict, Iterable, Iterator, List, Optional

from ..client import MondayClient
from ..oo import Session
from ..oo import Workspace, Board, Item


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


def _batched_list_items_for_boards(client: MondayClient, board_ids: List[str], *, page_size: int = 200, batch_size: int = 20) -> Dict[str, List[Dict[str, Any]]]:

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
) -> List[Workspace]:
    """Return an OO tree: list of Workspaces with Boards and Items attached.

    - Returns: ``list[Workspace]`` where each ``Workspace`` has ``boards: list[Board]``
      (attached attribute) and each ``Board`` has ``items: list[Item]`` (attached attribute).
    - All returned objects are bound to the provided ``Session`` so methods like
      ``refresh()``, ``create_item()``, etc. work as expected without additional
      lookups.

    Fetching uses the low-level client's iterators for maximal page sizes and
    batches item listing across boards in manageable chunks to respect API limits.
    """

    client = session.client

    # 1) Gather workspaces (shallow) and create OO Workspace objects bound to session
    workspaces_raw: List[Dict[str, Any]] = [
        {"id": str(ws.get("id")), "name": ws.get("name")}
        for ws in _yield_all_workspaces(client, page_size=page_size_workspaces)
    ]
    workspaces: List[Workspace] = []
    ws_id_to_ws: Dict[str, Workspace] = {}
    for ws in workspaces_raw:
        ws_id = ws["id"]
        ws_obj = Workspace(id=ws_id, name=ws.get("name"))
        ws_obj._session = session
        # Attach dynamic children container
        ws_obj.boards = []  # type: ignore[attr-defined]
        workspaces.append(ws_obj)
        ws_id_to_ws[ws_id] = ws_obj

    # 2) For each workspace, gather boards, create OO Board objects, attach to Workspace
    board_id_to_board: Dict[str, Board] = {}
    all_board_ids: List[str] = []
    for ws_raw in workspaces_raw:
        ws_id = ws_raw["id"]
        ws_obj = ws_id_to_ws[ws_id]
        for b in _yield_all_boards_for_workspace(client, ws_id, page_size=page_size_boards):
            bid = str(b.get("id"))
            bd_obj = Board(
                id=bid,
                name=b.get("name"),
                workspace_id=ws_id,
            )
            bd_obj._session = session
            # Attach dynamic children container
            bd_obj.items = []  # type: ignore[attr-defined]
            ws_obj.boards.append(bd_obj)  # type: ignore[attr-defined]
            board_id_to_board[bid] = bd_obj
            all_board_ids.append(bid)

    # 3) Items per board, batched
    board_id_to_items: Dict[str, List[Dict[str, Any]]] = {}
    if all_board_ids:
        board_id_to_items = _batched_list_items_for_boards(
            client,
            all_board_ids,
            page_size=page_size_items,
            batch_size=items_batch_size,
        )

    # 4) Attach items to Board objects
    for bid, rows in board_id_to_items.items():
        bd_obj = board_id_to_board.get(bid)
        if bd_obj is None:
            continue
        for it in rows:
            iid = str(it.get("id"))
            it_obj = Item(id=iid, name=it.get("name"), board_id=bid)
            it_obj._session = session
            bd_obj.items.append(it_obj)  # type: ignore[attr-defined]

    return workspaces


__all__ = [
    "build_workspace_board_item_tree",
]



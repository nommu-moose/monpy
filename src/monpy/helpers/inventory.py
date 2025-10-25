from __future__ import annotations

from typing import Any, Dict, Iterable, Iterator, List, Optional
import json
from datetime import datetime
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..client import MondayClient
from ..oo import Session
from ..oo import Workspace, Board, Item
from ..oo.columns.values import _decode_value, LocationValue
from ..exceptions import RateLimitError


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


def _batched_list_items_for_boards(
    client: MondayClient,
    board_ids: List[str],
    *,
    page_size: int = 200,
    batch_size: int = 20,
    num_threads: int = 4,
    max_retries: int = 4,
) -> Dict[str, List[Dict[str, Any]]]:
    """Batch-fetch basic item data for multiple boards using multithreading."""
    result: Dict[str, List[Dict[str, Any]]] = {bid: [] for bid in board_ids}
    
    def fetch_items_for_board(bid: str) -> tuple[str, List[Dict[str, Any]]]:
        board_items: List[Dict[str, Any]] = []
        try:
            for row in client.iter_items(bid, page_size=page_size, state="active", fields=["id", "name"]):
                board_items.append({"id": str(row.get("id")), "name": row.get("name")})
        except RateLimitError:
            # Retry the entire board fetch with backoff
            _retry_with_backoff(
                lambda: None,  # dummy function to trigger retry logic
                max_retries=max_retries,
            )
            # After retry, attempt again
            for row in client.iter_items(bid, page_size=page_size, state="active", fields=["id", "name"]):
                board_items.append({"id": str(row.get("id")), "name": row.get("name")})
        return bid, board_items
    
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = {
            executor.submit(fetch_items_for_board, bid): bid
            for bid in board_ids
        }
        for future in as_completed(futures):
            try:
                bid, items = future.result()
                result[bid] = items
            except Exception:
                # If fetch fails, keep empty list
                pass
    
    return result


def _get_detailed_items_for_board(
    client: MondayClient, board_id: str, *, page_size: int = 200, max_retries: int = 4
) -> List[Dict[str, Any]]:
    """Fetch all items for a board with full column values."""
    items_data: List[Dict[str, Any]] = []
    for item_row in client.iter_items(board_id, page_size=page_size, state="active"):
        item_id = str(item_row.get("id"))
        try:
            full_item = _retry_with_backoff(
                client.get_item_values,
                item_id,
                include_board=True,
                parse_json_values=False,
                max_retries=max_retries,
            )
            items_data.append(full_item)
        except Exception:
            # Fallback to basic item data if details fail
            items_data.append(item_row)
    return items_data


def _batched_get_detailed_items_for_boards(
    client: MondayClient,
    board_ids: List[str],
    *,
    page_size: int = 200,
    batch_size: int = 20,
    num_threads: int = 4,
    max_retries: int = 4,
) -> Dict[str, List[Dict[str, Any]]]:
    """Batch-fetch detailed items (with column values) for multiple boards using multithreading."""
    result: Dict[str, List[Dict[str, Any]]] = {bid: [] for bid in board_ids}
    
    def fetch_items_for_board(bid: str) -> tuple[str, List[Dict[str, Any]]]:
        items = _get_detailed_items_for_board(
            client, bid, page_size=page_size, max_retries=max_retries
        )
        return bid, items
    
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = {
            executor.submit(fetch_items_for_board, bid): bid
            for bid in board_ids
        }
        for future in as_completed(futures):
            try:
                bid, items = future.result()
                result[bid] = items
            except Exception:
                # If fetch fails, keep empty list
                pass
    
    return result


def _build_columns_cache(session: Session) -> Dict[str, Dict[str, Any]]:
    """Build a cache of board_id -> {column_id: column_metadata} for efficient lookups."""
    cache: Dict[str, Dict[str, Any]] = {}
    for workspace in session.list_workspaces():
        for board in workspace.boards:  # type: ignore[union-attr]
            if board.id not in cache:
                cols_by_id: Dict[str, Any] = {}
                try:
                    for col in board.columns:
                        cols_by_id[col.id] = {
                            "id": col.id,
                            "title": col.title,
                            "type": col.type,
                            "settings": col.settings,
                        }
                except Exception:
                    pass
                cache[board.id] = cols_by_id
    return cache


def _decode_item_values(
    item_data: Dict[str, Any], columns_cache: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    """Decode item column values using the reverse of upsert's encode logic.
    
    Returns a dictionary mapping column titles (or IDs) to decoded Python values.
    """
    board_id = item_data.get("board", {}).get("id") if isinstance(item_data.get("board"), dict) else None
    if not board_id:
        board_id = str(item_data.get("board_id", ""))
    
    cols_by_id = columns_cache.get(str(board_id), {})
    decoded: Dict[str, Any] = {}
    
    for col_value in item_data.get("column_values", []):
        col_id = col_value.get("id")
        col_meta = cols_by_id.get(str(col_id), {})
        col_type = col_meta.get("type") or col_value.get("type")
        col_title = col_meta.get("title") or col_value.get("title") or col_id
        
        # Decode the value using the reverse of encode
        decoded_val = _decode_value(col_type, col_value)
        decoded[col_title] = decoded_val
    
    return decoded


def _retry_with_backoff(
    func,
    *args,
    max_retries: int = 4,
    **kwargs
) -> Any:
    """Execute a function with exponential backoff retry on RateLimitError."""
    last_error: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except RateLimitError as e:
            last_error = e
            if attempt < max_retries - 1:
                # Exponential backoff: 1s, 2s, 4s, 8s
                wait_time = 2 ** attempt
                time.sleep(wait_time)
            continue
        except Exception as e:
            # Non-rate-limit errors are raised immediately
            raise
    if last_error:
        raise last_error
    return None


def build_workspace_board_item_tree(
    session: Session,
    *,
    page_size_workspaces: int = 100,
    page_size_boards: int = 100,
    page_size_items: int = 200,
    items_batch_size: int = 20,
    num_threads: int = 4,
    max_retries: int = 4,
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
            num_threads=num_threads,
            max_retries=max_retries,
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


def build_detailed_workspace_board_item_tree(
    session: Session,
    *,
    page_size_workspaces: int = 100,
    page_size_boards: int = 100,
    page_size_items: int = 200,
    items_batch_size: int = 20,
    include_decoded_values: bool = True,
    num_threads: int = 4,
    max_retries: int = 4,
) -> List[Workspace]:
    """Return an OO tree with Workspaces, Boards, and Items with detailed column data.

    Extends build_workspace_board_item_tree by:
    - Fetching full column values for each item (with proper type decoding).
    - Attaching decoded column values to Item objects via a 'decoded_values' attribute.
    - Using the same value decoders as the safe upsert helper (reversed mapping).

    Returns: ``list[Workspace]`` where each ``Workspace`` has ``boards: list[Board]``
      (attached attribute) and each ``Board`` has ``items: list[Item]`` (attached attribute).
      Each ``Item`` has an optional ``decoded_values: dict[str, Any]`` attribute mapping
      column titles to decoded Python values.

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

    # 3) Fetch detailed items (with column values) for all boards in batches
    board_id_to_items: Dict[str, List[Dict[str, Any]]] = {}
    if all_board_ids:
        board_id_to_items = _batched_get_detailed_items_for_boards(
            client,
            all_board_ids,
            page_size=page_size_items,
            batch_size=items_batch_size,
            num_threads=num_threads,
            max_retries=max_retries,
        )

    # 4) Build columns cache for efficient value decoding
    columns_cache: Dict[str, Dict[str, Any]] = {}
    if include_decoded_values:
        # Pre-cache all columns for all boards
        for board_id in all_board_ids:
            bd_obj = board_id_to_board.get(board_id)
            if bd_obj is None:
                continue
            try:
                cols_by_id: Dict[str, Any] = {}
                for col in bd_obj.columns:
                    cols_by_id[col.id] = {
                        "id": col.id,
                        "title": col.title,
                        "type": col.type,
                        "settings": col.settings,
                    }
                columns_cache[board_id] = cols_by_id
            except Exception:
                columns_cache[board_id] = {}

    # 5) Attach items to Board objects with decoded values
    for bid, rows in board_id_to_items.items():
        bd_obj = board_id_to_board.get(bid)
        if bd_obj is None:
            continue
        for item_data in rows:
            iid = str(item_data.get("id"))
            it_obj = Item(
                id=iid,
                name=item_data.get("name"),
                board_id=bid,
                state=item_data.get("state"),
                updated_at=item_data.get("updated_at"),
            )
            it_obj._session = session
            
            # Attach decoded column values if requested
            if include_decoded_values:
                try:
                    decoded_vals = _decode_item_values(item_data, columns_cache)
                    it_obj.decoded_values = decoded_vals  # type: ignore[attr-defined]
                except Exception:
                    it_obj.decoded_values = {}  # type: ignore[attr-defined]
            
            bd_obj.items.append(it_obj)  # type: ignore[attr-defined]

    return workspaces


__all__ = [
    "build_workspace_board_item_tree",
    "build_detailed_workspace_board_item_tree",
]



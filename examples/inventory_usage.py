from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict


# Ensure repository "src" is importable when running this script directly
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from monpy import MondayClient, Session, build_workspace_board_item_tree, build_detailed_workspace_board_item_tree  # noqa: E402


def _load_config() -> Dict[str, Any]:
    """Load config from tests/config.json file."""
    cfg = Path(__file__).resolve().parents[1] / "tests" / "config.json"
    if cfg.exists():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _build_client_from_config() -> MondayClient | None:
    """Build MondayClient using API token from tests/config.json. Returns None if unavailable."""
    config = _load_config()
    token = config.get("MONDAY_API_TOKEN") or config.get("token")
    if not token:
        return None
    return MondayClient(token=token)


class _FakeMondayClient:
    """Minimal fake client to exercise the inventory helper offline."""

    def iter_workspaces(self, *, page_size: int = 25, fields: list[str] | None = None):
        data = [
            {"id": "w1", "name": "Workspace A"},
            {"id": "w2", "name": "Workspace B"},
        ]
        for row in data:
            yield row

    def iter_boards(
        self,
        *,
        page_size: int = 100,
        workspace_id: str | None = None,
        state: str | list[str] | None = "active",
        fields: list[str] | None = None,
    ):
        boards_by_ws = {
            "w1": [
                {"id": "b1", "name": "Board 1", "workspace_id": "w1"},
                {"id": "b2", "name": "Board 2", "workspace_id": "w1"},
            ],
            "w2": [
                {"id": "b3", "name": "Board 3", "workspace_id": "w2"},
            ],
        }
        for row in boards_by_ws.get(str(workspace_id), []):
            yield row

    def iter_items(
        self,
        board_id: str,
        *,
        page_size: int = 200,
        state: str | list[str] | None = "active",
        fields: list[str] | None = None,
        start_cursor: str | None = None,
    ):
        items_by_board = {
            "b1": [{"id": "i1", "name": "Item 1"}, {"id": "i2", "name": "Item 2"}],
            "b2": [{"id": "i3", "name": "Item 3"}],
            "b3": [],
        }
        for row in items_by_board.get(str(board_id), []):
            yield row

    def get_item_values(self, item_id: str, *, include_board: bool = False, parse_json_values: bool = True):
        """Return mock detailed item data with column values for the detailed inventory function."""
        items = {
            "i1": {
                "id": "i1",
                "name": "Item 1",
                "state": "active",
                "updated_at": "2025-01-15T10:00:00Z",
                "board": {"id": "b1", "name": "Board 1"},
                "column_values": [
                    {"id": "status_col", "title": "Status", "type": "status", "value": '{"index":1}', "text": "In Progress"},
                    {"id": "date_col", "title": "Due Date", "type": "date", "value": '{"date":"2025-12-31"}', "text": "2025-12-31"},
                    {"id": "text_col", "title": "Description", "type": "text", "value": "Task details", "text": "Task details"},
                ],
            },
            "i2": {
                "id": "i2",
                "name": "Item 2",
                "state": "active",
                "updated_at": "2025-01-14T09:30:00Z",
                "board": {"id": "b1", "name": "Board 1"},
                "column_values": [
                    {"id": "status_col", "title": "Status", "type": "status", "value": '{"index":0}', "text": "Not Started"},
                    {"id": "date_col", "title": "Due Date", "type": "date", "value": '{"date":"2025-02-28"}', "text": "2025-02-28"},
                    {"id": "text_col", "title": "Description", "type": "text", "value": "Another task", "text": "Another task"},
                ],
            },
            "i3": {
                "id": "i3",
                "name": "Item 3",
                "state": "active",
                "updated_at": "2025-01-13T14:15:00Z",
                "board": {"id": "b2", "name": "Board 2"},
                "column_values": [
                    {"id": "status_col", "title": "Status", "type": "status", "value": '{"index":2}', "text": "Done"},
                ],
            },
        }
        item_data = items.get(str(item_id), {"id": item_id, "name": "Unknown", "column_values": []})
        if not include_board:
            item_data.pop("board", None)
        return item_data

    def get_columns(self, board_id: str, fields: list[str] | None = None):
        """Return mock column metadata for boards."""
        columns_by_board = {
            "b1": [
                {"id": "status_col", "title": "Status", "type": "status", "settings": {}},
                {"id": "date_col", "title": "Due Date", "type": "date", "settings": {}},
                {"id": "text_col", "title": "Description", "type": "text", "settings": {}},
            ],
            "b2": [
                {"id": "status_col", "title": "Status", "type": "status", "settings": {}},
            ],
        }
        return columns_by_board.get(str(board_id), [])


def main() -> int:
    client = _build_client_from_config()
    if client is None:
        print("No tests/config.json token found; using a fake client for offline demo.")
        client = _FakeMondayClient()  # type: ignore[assignment]
    session = Session(client)  # type: ignore[arg-type]

    print("=" * 70)
    print("BASIC INVENTORY (workspace/board/item structure only)")
    print("=" * 70)
    t1 = time.time()
    tree = build_workspace_board_item_tree(
        session,
        num_threads=8,      # Fetch 4 boards concurrently
        max_retries=4,      # Retry rate-limited requests up to 4 times with exponential backoff
    )
    t2 = time.time()
    print(t2 - t1)

    for ws in tree:
        print(f"Workspace: {ws.name or ''} ({ws.id})")
        boards = getattr(ws, "boards", [])
        for b in boards:
            items = getattr(b, "items", [])
            print(f"  - Board: {b.name or ''} ({b.id}) items={len(items)}")
            print(items[0])

    print("\n" + "=" * 70)
    print("DETAILED INVENTORY (with decoded column values)")
    print("=" * 70)
    """
    detailed_tree = build_detailed_workspace_board_item_tree(session, include_decoded_values=True)

    for ws in detailed_tree:
        print(f"\nWorkspace: {ws.name or ''} ({ws.id})")
        boards = getattr(ws, "boards", [])
        for b in boards:
            items = getattr(b, "items", [])
            print(f"  Board: {b.name or ''} ({b.id})")
            for item in items:
                print(f"    - Item: {item.name} ({item.id})")
                decoded = getattr(item, "decoded_values", {})
                if decoded:
                    for col_title, col_value in decoded.items():
                        print(f"        {col_title}: {col_value}")
                else:
                    print("        (no decoded values)")

    print("\n" + "=" * 70)
    print("DETAILED INVENTORY (with multithreading and retry options)")
    print("=" * 70)
    detailed_tree_threaded = build_detailed_workspace_board_item_tree(
        session,
        include_decoded_values=True,
        num_threads=4,      # Use 4 threads to fetch items in parallel
        max_retries=4,      # Retry rate-limited requests up to 4 times with exponential backoff
    )

    for ws in detailed_tree_threaded:
        print(f"\nWorkspace: {ws.name or ''} ({ws.id})")
        boards = getattr(ws, "boards", [])
        for b in boards:
            items = getattr(b, "items", [])
            print(f"  Board: {b.name or ''} ({b.id}) - {len(items)} items")
    """
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



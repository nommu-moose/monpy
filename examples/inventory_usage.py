from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict


# Ensure repository "src" is importable when running this script directly
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from monpy import MondayClient, Session, build_workspace_board_item_tree  # noqa: E402


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


def main() -> int:
    client = _build_client_from_config()
    if client is None:
        print("No tests/config.json token found; using a fake client for offline demo.")
        client = _FakeMondayClient()  # type: ignore[assignment]
    session = Session(client)  # type: ignore[arg-type]

    tree = build_workspace_board_item_tree(session)

    for ws in tree:
        wname = ws.get("workspace_name") or ""
        wid = ws.get("workspace_id") or ""
        print(f"Workspace: {wname} ({wid})")
        boards = ws.get("boards") or []
        for b in boards:
            bname = b.get("board_name") or ""
            bid = b.get("board_id") or ""
            items = b.get("items") or []
            print(f"  - Board: {bname} ({bid}) items={len(items)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())



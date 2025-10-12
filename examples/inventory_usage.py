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


def _build_client_from_config() -> MondayClient:
    """Build MondayClient using API token from tests/config.json."""
    config = _load_config()
    token = config.get("MONDAY_API_TOKEN") or config.get("token")
    if not token:
        raise SystemExit("Live example requires tests/config.json with MONDAY_API_TOKEN or token")
    client = MondayClient(token=token)
    return client


def main() -> int:
    client = _build_client_from_config()
    session = Session(client)

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



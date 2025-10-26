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

from monpy import MondayClient, get_inventory  # noqa: E402


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


def main() -> int:
    client = _build_client_from_config()
    if not client:
        print("No tests/config.json token found. Please provide your Monday.com API token in that file.")
        print('e.g. {"token": "your-api-token-here"}')
        return 1

    print("Fetching inventory... (this may take a moment for large accounts)")

    # The get_inventory helper fetches all workspaces, their boards, and all items on those boards.
    # It returns a hierarchical structure of objects.
    # You can pass arguments like `num_threads` to speed up fetching.
    inventory = get_inventory(client=client, num_threads=8, max_retries=3)

    print("\n" + "=" * 70)
    print("INVENTORY HIERARCHY")
    print("=" * 70)

    for workspace in inventory:
        print(f"Workspace: {workspace.name} (ID: {workspace.id})")

        # The 'boards' attribute is dynamically attached by the inventory helper
        for board in getattr(workspace, "boards", []):
            print(f"  - Board: {board.name} (ID: {board.id})")

            # The 'items' attribute is also dynamically attached
            items = getattr(board, "items", [])
            print(f"    ({len(items)} items)")
            for item in items:
                print(f"    - Item: {item.name} (ID: {item.id})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

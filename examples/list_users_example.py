from __future__ import annotations

from typing import Any, Dict
from pathlib import Path
import json
import sys


# Ensure repository "src" is importable when running this script directly
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from monpy import MondayClient  # noqa: E402
from monpy.helpers import fetch_all_account_users  # noqa: E402


def _load_config() -> Dict[str, Any]:
    """Load config from tests/config.json file (ignored by git)."""
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
        print("No tests/config.json token found; please create it to run this example.")
        return 1

    users = fetch_all_account_users(client)
    print(f"Total users: {len(users)}\n")
    for idx, u in enumerate(users, 1):
        print(f"[{idx}] account_id: {u.account_id}")
        print(f"    email: {u.email}")
        print(f"    first_name: {u.first_name}")
        print(f"    last_name: {u.last_name}")
        print(f"    phone_number: {u.phone_number}")
        print(f"    teams: {', '.join(u.teams) if u.teams else ''}")
        print(f"    status: {u.status}")
        print(f"    department: {u.department or ''}")
        print(f"    user_role: {u.user_role}")
        print("")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



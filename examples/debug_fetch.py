import json
import inspect
from pathlib import Path
from typing import Any, Dict

from monpy import MondayClient
from monpy.oo import Session
from monpy.helpers import fetch_board_data, enable_graphql_trace


def _load_config() -> Dict[str, Any]:
    cfg = Path(__file__).resolve().parents[1] / "tests" / "config.json"
    if cfg.exists():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def main() -> None:
    cfg = _load_config()
    token = cfg.get("MONDAY_API_TOKEN") or cfg.get("token")
    if not token:
        raise SystemExit("Set MONDAY_API_TOKEN in tests/config.json")

    client = MondayClient(token=token, dev_mode=True, max_retries=6, backoff=1.5)
    client.retries = 2

    # Toggle to see every GraphQL call; noisy but useful
    # enable_graphql_trace(client, print_success=False)

    sess = Session(client, values_cache_ttl=2.0)

    print("fetch_board_data source:", inspect.getsourcefile(fetch_board_data))

    def log(msg: str) -> None:
        print(msg)

    rows = fetch_board_data(
        sess,
        workspace_name="People & Talent Ops",
        board_name="People",
        columns={
            "First Name": "text",
            "Last Name": "text",
            "Phone": "phone",
            "Email": "email",
            "Candidate Category": "status",
            "GER": "status",
            "ENG": "status",
            "BUL": "status",
            "HUN": "status",
            "GDPR Date": "date",
            "Gender": "status",
        },
        state="active",
        include_subitems=False,
        batch_size=100,
        max_retries=6,
        debug=True,
        logger=log,
    )

    print("Final count:", len(rows))


if __name__ == "__main__":
    main()



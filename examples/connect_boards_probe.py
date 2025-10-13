from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


# Ensure repository "src" is importable when running this script directly
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from monpy import MondayClient  # noqa: E402
from monpy.exceptions import FeatureNotSupported, MondayAPIError  # noqa: E402
from monpy.oo import Session  # noqa: E402
from monpy.oo.enums import BoardKind, ColumnType  # noqa: E402
from monpy.oo.columns.defaults import ConnectBoardsDefaults  # noqa: E402


def _load_config() -> Dict[str, Any]:
    cfg = ROOT / "tests" / "config.json"
    if cfg.exists():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _build_client_from_config() -> MondayClient:
    config = _load_config()
    token = config.get("MONDAY_API_TOKEN") or config.get("token")
    if not token:
        raise SystemExit("Missing MONDAY_API_TOKEN in tests/config.json")
    return MondayClient(token=token)


@dataclass
class CreatedResources:
    workspace_id: Optional[str] = None
    board_a_id: Optional[str] = None
    board_b_id: Optional[str] = None


def create_min_env(sess: Session) -> CreatedResources:
    ts = str(int(time.time()))
    ws = sess.client.create_workspace(name=f"monpy-connect-probe-{ts}", kind="open", description="probe connect boards")
    ws_id = str(ws["id"]) if isinstance(ws, dict) else str(getattr(ws, "id", ""))

    b1 = sess.create_board(workspace_id=ws_id, name=f"probe-A-{ts}", board_kind=BoardKind.PUBLIC.value)
    b2 = sess.create_board(workspace_id=ws_id, name=f"probe-B-{ts}", board_kind=BoardKind.PUBLIC.value)
    return CreatedResources(workspace_id=ws_id, board_a_id=str(b1.id), board_b_id=str(b2.id))


def cleanup(sess: Session, res: CreatedResources) -> None:
    # Best-effort cleanup: try deleting workspace first (removes contained boards)
    try:
        if res.workspace_id:
            sess.client.delete_workspace(res.workspace_id)
            return
    except Exception:
        pass
    # Fallback: archive boards individually
    for bid in (res.board_a_id, res.board_b_id):
        if not bid:
            continue
        try:
            sess.client.archive_board(bid)
        except Exception:
            pass


def try_create_connect_column(sess: Session, board_id: str, target_board_id: str) -> dict | None:
    bd = sess.board(board_id)
    try:
        col = bd.create_column(
            title="Related",
            column_type="board_relation",
            defaults=ConnectBoardsDefaults(
                board_ids=[int(target_board_id)],
                allow_multiple_items=True,
                allow_create_reflection_column=True,
            ),
        )
        # Validate metadata exposure
        got = sess.client.get_column(board_id, col.id)
        return got
    except FeatureNotSupported as e:
        print("FeatureNotSupported while creating connect boards column:")
        print(str(e))
        return None
    except MondayAPIError as e:
        print("MondayAPIError while creating connect boards column:")
        try:
            errs = getattr(e, "errors", [])
            print(json.dumps(errs, indent=2))
        except Exception:
            print(str(e))
        return None


def main() -> int:
    client = _build_client_from_config()
    sess = Session(client)

    res = CreatedResources()
    try:
        res = create_min_env(sess)
        print(f"Created workspace={res.workspace_id} boards A={res.board_a_id}, B={res.board_b_id}")

        # Attempt to create connect boards column from A -> B
        print("Attempting to create connect boards column on Board A linking to Board B...")
        meta = try_create_connect_column(sess, res.board_a_id or "", res.board_b_id or "")
        if meta:
            print("Created connect boards column. Metadata:")
            print(json.dumps(meta, indent=2))
            cb_ids = (meta or {}).get("connected_board_ids") or []
            print(f"connected_board_ids = {cb_ids}")
        else:
            print("Connect boards creation not available; please create manually in the UI and re-run if needed.")

        return 0
    finally:
        time.sleep(20)
        cleanup(sess, res)


if __name__ == "__main__":
    raise SystemExit(main())



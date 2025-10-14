from __future__ import annotations

import time
import uuid
import pytest


pytestmark = pytest.mark.live


def _unique_name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def test_pagination_workspaces_and_boards_live(client_live, _test_config):
    # Configurable sizes to support fast vs full runs
    ws_count = int(_test_config.get("PG_WS_COUNT", 3))
    bd_count = int(_test_config.get("PG_BOARD_COUNT", 4))
    page_size = int(_test_config.get("PG_PAGE_SIZE", 3))

    prefix = _unique_name("monpy-pg-ws")
    created_ws_ids: list[str] = []
    try:
        for i in range(ws_count):
            ws = client_live.create_workspace(name=f"{prefix}-{i+1}", kind="open")
            created_ws_ids.append(str(ws.get("id")))

        # Iterate over workspaces and collect our own
        seen_ids: list[str] = []
        for ws in client_live.iter_workspaces(page_size=page_size, fields=("id", "name")):
            name = str(ws.get("name") or "")
            if name.startswith(prefix + "-"):
                seen_ids.append(str(ws.get("id")))

        assert set(created_ws_ids).issubset(set(seen_ids))

        # For boards: create a single workspace and several boards in it
        ws_for_boards = client_live.create_workspace(name=_unique_name("monpy-pg-ws2"), kind="open")
        wbid = str(ws_for_boards.get("id"))
        created_ws_ids.append(wbid)  # include for cleanup

        board_prefix = _unique_name("monpy-pg-bd")
        created_board_ids: list[str] = []
        for j in range(bd_count):
            bd = client_live.create_board(name=f"{board_prefix}-{j+1}", board_kind="public", workspace_id=wbid)
            created_board_ids.append(str(bd.get("id")))

        # Iterate boards with small page size
        seen_board_ids: list[str] = []
        for bd in client_live.iter_boards(page_size=page_size, workspace_id=wbid, fields=("id", "name")):
            if str(bd.get("name") or "").startswith(board_prefix + "-"):
                seen_board_ids.append(str(bd.get("id")))

        assert set(created_board_ids).issubset(set(seen_board_ids))

    finally:
        # Cleanup: delete the temporary workspaces (which deletes contained boards)
        for wsid in created_ws_ids:
            try:
                client_live.delete_workspace(wsid)
            except Exception:
                # Best-effort cleanup; ignore failures
                pass



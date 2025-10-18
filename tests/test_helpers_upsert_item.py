from __future__ import annotations

import time
from datetime import date

import pytest

from monpy import MondayClient
from monpy.exceptions import MondayAPIError
from monpy.helpers import (
    BoardSpec,
    ColumnSpec,
    ItemSpec,
    StatusColor,
    StatusDefaults,
    StatusOption,
    WorkspaceSpec,
    upsert_item,
    upsert_item_from_dicts,
)
import random


def _mk_cols(target_item_id: str | None = None) -> list[ColumnSpec]:
    cols: list[ColumnSpec] = [
        ColumnSpec(type="name", title="Name", value="main"),
        ColumnSpec(type="text", title="Text", value="hello"),
        ColumnSpec(type="numbers", title="Number", value=7),
        ColumnSpec(type="status", title="Status", value={"index": 1}),
        ColumnSpec(type="date", title="Due Date", value=date.today()),
        ColumnSpec(type="email", title="Email", value={"email": "u@example.com", "text": "User"}),
        ColumnSpec(type="people", title="Assignee", value=[]),
        ColumnSpec(
            type="connect_boards",
            title="Related",
            defaults={"boardIds": []},
            value=[target_item_id] if target_item_id else [],
        ),
        ColumnSpec(type="tags", title="Tags", value=[]),
    ]
    return cols


@pytest.mark.live
@pytest.mark.slow
def test_upsert_item_end_to_end(client_live):
    ts = str(int(time.time()))

    # Workspace/board specs
    ws = WorkspaceSpec(name=f"monpy-helper-{ts}", kind="open", description="helper upsert test")
    bd = BoardSpec(name=f"monpy-helper-board-{ts}")

    # Create a related board and seed an item to link
    ws_raw = client_live.create_workspace(name=f"monpy-helper-rel-{ts}", kind="open", description="related")
    bd_rel = client_live.create_board(name=f"rel-{ts}", workspace_id=ws_raw["id"])
    g_rel = client_live.create_group(bd_rel["id"], title="grp-rel")
    target = client_live.create_item(bd_rel["id"], group_id=g_rel["id"], item_name="target")

    # Explicit columns with connect boards defaults pointing to the related board
    cols = [
        ColumnSpec(type="name", title="Name", value="main"),
        ColumnSpec(type="text", title="Text", value="hello"),
        ColumnSpec(type="numbers", title="Number", value=7),
        ColumnSpec(type="status", title="Status", value={"index": 1}),
        ColumnSpec(type="date", title="Due Date", value=date.today()),
        ColumnSpec(type="email", title="Email", value={"email": "u@example.com", "text": "User"}),
        ColumnSpec(type="people", title="Assignee", value=[]),
        ColumnSpec(
            type="connect_boards",
            title="Related",
            defaults={"boardIds": [int(bd_rel["id"])], "allowMultipleItems": True},
            value=[int(target["id"])],
        ),
        ColumnSpec(type="tags", title="Tags", value=[]),
    ]

    res = None
    ws_id = None
    bd_id = None
    try:
        # Initial create
        res = upsert_item(
            client_live,
            workspace=ws,
            board=bd,
            item=ItemSpec(name="main"),
            columns=cols,
            group_name="grp1",
        )
        ws_id = res["workspace_id"]
        bd_id = res["board_id"]

        assert ws_id and bd_id and res["item_id"]
        item_id = res["item_id"]

        # Verify values reflected
        got = client_live.get_item_values(item_id, include_board=True)
        assert got.get("id")

        # Update round (change text and status)
        cols_update = [
            ColumnSpec(type="text", title="Text", value="world", column_id=res["column_ids"]["Text"]),
            ColumnSpec(type="status", title="Status", value={"index": 2}, column_id=res["column_ids"]["Status"]),
        ]
        res2 = upsert_item(
            client_live,
            workspace=WorkspaceSpec(name=ws.name, id=ws_id),
            board=BoardSpec(name=bd.name, id=bd_id),
            item=ItemSpec(name="main", id=item_id),
            columns=cols_update,
        )
        assert res2["item_id"] == item_id
    finally:
        # cleanup: best-effort – deleting the workspace removes contained boards/items
        try:
            if ws_id:
                client_live.delete_workspace(ws_id)
        except Exception:
            # fallback to archiving if workspace deletion is restricted
            try:
                if bd_id:
                    client_live.archive_board(bd_id)
            except Exception:
                pass
        try:
            client_live.delete_workspace(ws_raw["id"])  # related workspace
        except Exception:
            try:
                client_live.archive_board(bd_rel["id"])  # type: ignore[index]
            except Exception:
                pass


def test_upsert_item_from_dicts_minimal(client_live):
    ts = str(int(time.time()))
    out = None
    ws_id = None
    bd_id = None
    try:
        out = upsert_item_from_dicts(
            client_live,
            workspace_name=f"monpy-helper2-{ts}",
            board_name=f"board-{ts}",
            columns_data=[
                {"type": "name", "title": "Name", "value": "main"},
                {"type": "text", "title": "Text", "value": "hello"},
                {"type": "status", "title": "Status", "value": {"index": 1}},
            ],
            group_name="grp1",
        )
        ws_id = out["workspace_id"]
        bd_id = out["board_id"]
        assert ws_id and bd_id and out["item_id"]
    finally:
        try:
            if ws_id:
                client_live.delete_workspace(ws_id)
        except Exception:
            try:
                if bd_id:
                    client_live.archive_board(bd_id)
            except Exception:
                pass


@pytest.mark.live
@pytest.mark.slow
def test_upsert_creates_status_with_labels_defaults(client_live):
    ts = str(int(time.time()))

    # Use distinct labels and colors via the OO helpers
    random.seed(int(ts))
    options = [
        StatusOption(label="Queued", color=StatusColor.ORANGE),
        StatusOption(label="Under way", color=StatusColor.TURQUOISE),
        StatusOption(label="Shipped", color=StatusColor.NAVY),
    ]
    random.shuffle(options)
    sd = StatusDefaults(options=options)
    # We need to know the shuffled order to validate the status value
    under_way_idx = [i for i, opt in enumerate(options) if opt.label == "Under way"][0]

    res = None
    ws_id = None
    bd_id = None
    try:
        # Pre-create workspace and board to guarantee we can tear them down even if creation fails mid-flight
        ws_raw = client_live.create_workspace(name=f"monpy-helper-status-{ts}", kind="open", description="status test")
        ws_id = str(ws_raw["id"])  # type: ignore[index]
        bd_raw = client_live.create_board(name=f"board-status-{ts}", workspace_id=ws_id)
        bd_id = str(bd_raw["id"])  # type: ignore[index]

        res = upsert_item(
            client_live,
            workspace=WorkspaceSpec(name=f"monpy-helper-status-{ts}", id=ws_id),
            board=BoardSpec(name=f"board-status-{ts}", id=bd_id),
            item=ItemSpec(name="main"),
            columns=[
                ColumnSpec(type="name", title="Name", value="main"),
                ColumnSpec(
                    type="status",
                    title="Status",
                    value={"index": under_way_idx},
                    defaults=sd.to_dict()
                ),
            ],
            group_name="grp1",
        )

        # Assertions
        assert res is not None
        assert res["workspace_id"] is not None
        assert res["board_id"] is not None
        item_data = res["result"]
        assert item_data["name"] == "main"
        # Find the status column by id from the upsert response
        status_cid = res["column_ids"]["Status"]
        status_cv = next(cv for cv in item_data["column_values"] if cv.get("id") == status_cid)
        assert status_cv["text"] == "Under way"
        # Fetch column settings directly from the API
        meta = client_live.get_column(res["board_id"], status_cid, fields=("id", "settings"))
        settings = meta.get("settings", {})
        labels = settings.get("labels") or []
        assert isinstance(labels, list) and len(labels) == 3
        # Labels have both "label" and "name" fields; "label" is the internal key, "name" is display
        label_texts = {lbl.get("label") or lbl.get("name") for lbl in labels if isinstance(lbl, dict)}
        assert {"Queued", "Under way", "Shipped"}.issubset(label_texts)

    finally:
        if ws_id:
            try:
                client_live.delete_workspace(ws_id)
            except Exception:
                try:
                    if bd_id:
                        client_live.archive_board(bd_id)
                except Exception:
                    pass


@pytest.mark.live
@pytest.mark.slow
def test_upsert_creates_connect_boards_with_defaults(client_live):
    ts = str(int(time.time()))

    # Related board + item
    ws_rel = client_live.create_workspace(name=f"monpy-helper-rel2-{ts}", kind="open", description="related2")
    bd_rel = client_live.create_board(name=f"rel2-{ts}", workspace_id=ws_rel["id"])
    g_rel = client_live.create_group(bd_rel["id"], title="grp-rel2")
    target = client_live.create_item(bd_rel["id"], group_id=g_rel["id"], item_name="target")

    res = None
    ws_id = None
    bd_id = None
    try:
        try:
            res = upsert_item(
                client_live,
                workspace=WorkspaceSpec(name=f"monpy-helper-cb-{ts}"),
                board=BoardSpec(name=f"board-cb-{ts}"),
                item=ItemSpec(name="main"),
                columns=[
                    ColumnSpec(type="name", title="Name", value="main"),
                    ColumnSpec(
                        type="connect_boards",
                        title="Related",
                        defaults={"boardIds": [int(bd_rel["id"])], "allowMultipleItems": True},
                        value=[int(target["id"])],
                    ),
                ],
                group_name="grp1",
            )
            ws_id = res["workspace_id"]
            bd_id = res["board_id"]
        except MondayAPIError:
            pytest.skip("Connect boards columns are not supported by this API/account")

        bid = bd_id
        cid = res["column_ids"]["Related"]

        # Verify defaults reflected on metadata
        meta = client_live.get_column(bid, cid, fields=("id", "type", "settings", "settings_str"))
        allowed = meta.get("connected_board_ids") or (meta.get("settings") or {}).get("boardIds")
        assert str(bd_rel["id"]) in {str(x) for x in (allowed or [])}

        # Verify link set
        got = client_live.get_item_values(res["item_id"], column_ids=[cid])
        rel = (got.get("column_values") or [{}])[0]
        linked = rel.get("value") if isinstance(rel.get("value"), list) else rel.get("linked_item_ids") or []
        assert str(target["id"]) in {str(x) for x in (linked or [])}
    finally:
        # cleanup both workspaces
        try:
            client_live.delete_workspace(ws_rel["id"])  # related
        except Exception:
            try:
                client_live.archive_board(bd_rel["id"])  # type: ignore[index]
            except Exception:
                pass
        try:
            if ws_id:
                client_live.delete_workspace(ws_id)
        except Exception:
            try:
                if bd_id:
                    client_live.archive_board(bd_id)
            except Exception:
                pass



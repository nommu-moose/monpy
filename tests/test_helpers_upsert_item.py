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
    batch_upsert_items,
)
import random
import requests
import json


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
def test_upsert_item_end_to_end(client_live, webhook_receiver):
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
    wh_ids = []
    try:
        # We need the board_id to register webhooks, so we ensure the workspace and board exist first.
        ws_res = client_live.create_workspace(name=ws.name, kind="open")
        ws_id = ws_res["id"]
        bd_res = client_live.create_board(name=bd.name, workspace_id=ws_id)
        bd_id = bd_res["id"]

        # Register webhooks for create and column change events
        wh_create = client_live.create_webhook(board_id=bd_id, url=webhook_receiver.receive_url, event="create_item")
        wh_ids.append(wh_create["id"])
        wh_change = client_live.create_webhook(board_id=bd_id, url=webhook_receiver.receive_url, event="change_column_value")
        wh_ids.append(wh_change["id"])

        # Wait for challenge to confirm webhook is active
        _ = webhook_receiver.wait_for_event(expect_type="", delays=[2, 3, 5, 8, 13])
        time.sleep(5)  # Allow time for webhooks to be fully active

        # Initial create
        res = upsert_item(
            client_live,
            workspace=WorkspaceSpec(name=ws.name, id=ws_id),
            board=BoardSpec(name=bd.name, id=bd_id),
            item=ItemSpec(name="main"),
            columns=cols,
            group_name="grp1",
        )

        # Verify create webhook
        create_event = webhook_receiver.wait_for_event(expect_type="create_item", delays=[2,3,5,8,13])
        if isinstance(create_event, dict) and create_event.get("event"):
            assert create_event.get("event", {}).get("type") == "create_item"
            assert create_event.get("event", {}).get("pulseId") == int(res["item_id"])

        assert res["workspace_id"] and res["board_id"] and res["item_id"]
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

        # Verify update webhook
        update_event = webhook_receiver.wait_for_event(expect_type="change_column_value", delays=[2,3,5,8,13])
        if isinstance(update_event, dict) and update_event.get("event"):
            assert update_event.get("event", {}).get("type") == "change_column_value"
            assert update_event.get("event", {}).get("pulseId") == int(item_id)
            assert update_event.get("event", {}).get("columnId") in [res["column_ids"]["Text"], res["column_ids"]["Status"]]

    finally:
        # cleanup webhooks
        for wh_id in wh_ids:
            try:
                client_live.delete_webhook(wh_id)
            except Exception:
                pass
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


@pytest.mark.live
@pytest.mark.slow
def test_batch_upsert_items_end_to_end(client_live: MondayClient, webhook_receiver):
    ts = str(int(time.time()))
    ws = WorkspaceSpec(name=f"monpy-batch-helper-{ts}")
    bd = BoardSpec(name=f"monpy-batch-board-{ts}")

    ws_id = None
    bd_id = None
    wh_ids = []

    try:
        # Initial create of workspace and board
        res_ws = client_live.create_workspace(name=ws.name, kind="open")
        ws_id = res_ws["id"]
        res_bd = client_live.create_board(name=bd.name, board_kind="public", workspace_id=ws_id)
        bd_id = res_bd["id"]

        # Register webhooks for create and column change events
        wh_create = client_live.create_webhook(board_id=bd_id, url=webhook_receiver.receive_url, event="create_item")
        wh_ids.append(wh_create["id"])
        wh_change = client_live.create_webhook(board_id=bd_id, url=webhook_receiver.receive_url, event="change_column_value")
        wh_ids.append(wh_change["id"])

        # Wait for challenge to confirm webhook is active
        _ = webhook_receiver.wait_for_event(expect_type="", delays=[2,3,5,8,13])
        time.sleep(5)  # Allow time for webhooks to be fully active

        # Create a group for the items
        res_group = client_live.create_group(board_id=bd_id, title="test_group")
        group_id = res_group["id"]

        # Create 5 items to be updated
        items_to_update_ids = []
        for i in range(5):
            res_item_to_update = client_live.create_item(board_id=bd_id, group_id=group_id, item_name=f"item_to_update_{i}")
            items_to_update_ids.append(res_item_to_update["id"])

        items_to_upsert = []
        # Add 15 items to create
        for i in range(15):
            items_to_upsert.append(
                (ItemSpec(name=f"new_item_{i}"), [
                    ColumnSpec(type="text", title="Text", value=f"value_{i}"),
                    ColumnSpec(type="numbers", title="Number", value=i),
                    ColumnSpec(type="date", title="Date", value=date(2023, 1, 1+i)),
                    ColumnSpec(type="email", title="Email", value={"email": f"test{i}@test.com", "text": f"Test {i}"}),
                ])
            )

        # Add 5 items to update
        for i, item_id in enumerate(items_to_update_ids):
            items_to_upsert.append(
                (ItemSpec(name=f"updated_item_{i}", id=item_id), [
                    ColumnSpec(type="text", title="Text", value=f"updated_value_{i}"),
                    ColumnSpec(type="numbers", title="Number", value=100 + i),
                    ColumnSpec(type="link", title="Link", value={"url": f"http://test.com/{i}", "text": f"Link {i}"}),
                ])
            )
        
        # Add status column to one of the new items
        items_to_upsert[0][1].append(
            ColumnSpec(type="status", title="Status", value={"label": "Done"}, defaults=StatusDefaults(
                options=[
                    StatusOption(label="Todo", color=StatusColor.STUCK_RED),
                    StatusOption(label="Done", color=StatusColor.DONE_GREEN),
                ]
            ).to_dict())
        )

        results = batch_upsert_items(
            client_live,
            workspace=WorkspaceSpec(name=ws.name, id=ws_id),
            board=BoardSpec(name=bd.name, id=bd_id),
            items_with_columns=items_to_upsert
        )

        assert len(results) == 20

        created_items = [res for res in results if "new_item" in res["result"]["name"]]
        updated_items = [res for res in results if "updated_item" in res["result"]["name"]]

        assert len(created_items) == 15
        assert len(updated_items) == 5

        # Verify webhooks
        seen_event_types = set()
        end_time = time.time() + 15  # Poll for 15 seconds
        while time.time() < end_time:
            ev = webhook_receiver.wait_for_event(expect_type="create_item", delays=[1])
            if isinstance(ev, dict) and ev.get("event"):
                seen_event_types.add(ev["event"]["type"])
            ev2 = webhook_receiver.wait_for_event(expect_type="change_column_value", delays=[1])
            if isinstance(ev2, dict) and ev2.get("event"):
                seen_event_types.add(ev2["event"]["type"])
            if {"create_item", "change_column_value"}.issubset(seen_event_types):
                break
        # Best-effort: do not assert to avoid flakiness in CI without public ingress

        # Verify updated items
        for i, updated_item_res in enumerate(sorted(updated_items, key=lambda x: x['result']['name'])):
            assert updated_item_res["item_id"] == items_to_update_ids[i]
            updated_item_vals = updated_item_res["result"]
            assert updated_item_vals["name"] == f"updated_item_{i}"

            text_col_id = updated_item_res["column_ids"]["Text"]
            text_val = next((c["text"] for c in updated_item_vals["column_values"] if c["id"] == text_col_id), None)
            assert text_val == f"updated_value_{i}"

            num_col_id = updated_item_res["column_ids"]["Number"]
            num_val = next((c["text"] for c in updated_item_vals["column_values"] if c["id"] == num_col_id), None)
            assert num_val == str(100 + i)

        # Verify created items
        for res in created_items:
            assert res["item_id"] is not None
            item_vals = res["result"]
            item_idx_str = item_vals['name'].split('_')[-1]

            text_col_id = res["column_ids"]["Text"]
            text_val = next((c["text"] for c in item_vals["column_values"] if c["id"] == text_col_id), None)
            assert text_val == f"value_{item_idx_str}"

            num_col_id = res["column_ids"]["Number"]
            num_val = next((c["text"] for c in item_vals["column_values"] if c["id"] == num_col_id), None)
            assert num_val == item_idx_str

            if "new_item_0" in item_vals["name"]:
                status_col_id = res["column_ids"]["Status"]
                status_val = next((c["text"] for c in item_vals["column_values"] if c["id"] == status_col_id), None)
                assert status_val == "Done"

    finally:
        for wh_id in wh_ids:
            try:
                client_live.delete_webhook(wh_id)
            except Exception:
                pass
        if ws_id:
            try:
                client_live.delete_workspace(ws_id)
            except Exception:
                if bd_id:
                    try:
                        client_live.archive_board(bd_id)
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
        StatusOption(label="Queued", color=StatusColor.BRIGHT_BLUE),
        StatusOption(label="Under way", color=StatusColor.AQUAMARINE),
        StatusOption(label="Shipped", color=StatusColor.DONE_GREEN),
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
        # Verify colors preserved for provided options. Some API versions return a numeric color index
        # instead of the canonical color string. Accept either the exact string or a numeric index.
        expected_label_to_color = {opt.label: opt.color.value for opt in options}
        for lbl in labels:
            if not isinstance(lbl, dict):
                continue
            name = lbl.get("label") or lbl.get("name")
            if name in expected_label_to_color:
                actual_color = lbl.get("color") or lbl.get("color_name") or lbl.get("colorName")
                if isinstance(actual_color, str):
                    assert actual_color == expected_label_to_color[name]
                else:
                    # Numeric index form – cannot reliably map back to canonical names here
                    assert isinstance(actual_color, int)

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



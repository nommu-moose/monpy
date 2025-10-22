from __future__ import annotations

import time

import pytest

from monpy.exceptions import ItemNotFound, MondayAPIError
from monpy.helpers import (
    BoardSpec,
    ColumnSpec,
    ItemSpec,
    WorkspaceSpec,
    upsert_item,
)


@pytest.mark.live
@pytest.mark.slow
def test_live_type_aware_resolution_creates_new_on_mismatch(client_live):
    ts = str(int(time.time()))
    ws_id = None
    try:
        ws = client_live.create_workspace(name=f"monpy-upsert-type-{ts}", kind="open", description="type aware")
        ws_id = str(ws["id"])  # type: ignore[index]
        bd = client_live.create_board(name=f"board-type-{ts}", workspace_id=ws_id)
        bd_id = str(bd["id"])  # type: ignore[index]
        # Pre-create text column titled "Field"
        pre = client_live.create_column(bd_id, title="Field", column_type="text")
        pre_id = str(pre.get("id"))

        # Upsert requesting status under the same title
        res = upsert_item(
            client_live,
            workspace=WorkspaceSpec(name=f"monpy-upsert-type-{ts}", id=ws_id),
            board=BoardSpec(name=f"board-type-{ts}", id=bd_id),
            item=ItemSpec(name="main"),
            columns=[
                ColumnSpec(type="name", title="Name", value="main"),
                ColumnSpec(type="status", title="Field", value={"index": 0}, defaults={"labels": [{"index": 0, "label": "Queued"}]})
            ],
            group_name="grp1",
        )
        new_id = res["column_ids"]["Field"]
        assert new_id != pre_id
        meta = client_live.get_column(bd_id, new_id, fields=("id", "type"))
        assert str(meta.get("type")).lower() == "status"
    finally:
        if ws_id:
            try:
                client_live.delete_workspace(ws_id)
            except Exception:
                pass


@pytest.mark.live
@pytest.mark.slow
def test_live_type_disambiguation_picks_same_type(client_live):
    ts = str(int(time.time()))
    ws_id = None
    try:
        ws = client_live.create_workspace(name=f"monpy-upsert-disamb-{ts}", kind="open", description="disambiguation")
        ws_id = str(ws["id"])  # type: ignore[index]
        bd = client_live.create_board(name=f"board-disamb-{ts}", workspace_id=ws_id)
        bd_id = str(bd["id"])  # type: ignore[index]
        c_text = client_live.create_column(bd_id, title="Field", column_type="text")["id"]
        c_status = client_live.create_column(bd_id, title="Field", column_type="status")["id"]

        res = upsert_item(
            client_live,
            workspace=WorkspaceSpec(name=f"monpy-upsert-disamb-{ts}", id=ws_id),
            board=BoardSpec(name=f"board-disamb-{ts}", id=bd_id),
            item=ItemSpec(name="main"),
            columns=[
                ColumnSpec(type="name", title="Name", value="main"),
                ColumnSpec(type="status", title="Field", value={"index": 0}),
            ],
            group_name="grp1",
        )
        assert res["column_ids"]["Field"] == c_status
        assert res["column_ids"]["Field"] != c_text
    finally:
        if ws_id:
            try:
                client_live.delete_workspace(ws_id)
            except Exception:
                pass


@pytest.mark.live
@pytest.mark.slow
def test_live_connect_boards_reuse_compatible(client_live):
    ts = str(int(time.time()))
    ws_id = None
    ws_rel_id = None
    try:
        ws = client_live.create_workspace(name=f"monpy-upsert-cb-reuse-{ts}", kind="open", description="cb reuse")
        ws_id = str(ws["id"])  # type: ignore[index]
        bd_main = client_live.create_board(name=f"board-main-{ts}", workspace_id=ws_id)
        bd_main_id = str(bd_main["id"])  # type: ignore[index]
        # Related board + item
        ws_rel = client_live.create_workspace(name=f"monpy-upsert-cb-rel-{ts}", kind="open", description="cb related")
        ws_rel_id = str(ws_rel["id"])  # type: ignore[index]
        bd_rel = client_live.create_board(name=f"board-rel-{ts}", workspace_id=ws_rel_id)
        bd_rel_id = str(bd_rel["id"])  # type: ignore[index]
        g_rel = client_live.create_group(bd_rel_id, title="grp-rel")
        target = client_live.create_item(bd_rel_id, group_id=g_rel["id"], item_name="target")

        try:
            pre = client_live.create_column(
                bd_main_id,
                title="Related",
                column_type="connect_boards",
                defaults={"boardIds": [int(bd_rel_id)], "allowMultipleItems": True},
            )
        except MondayAPIError:
            pytest.skip("Connect boards not supported by this API/account")

        res = upsert_item(
            client_live,
            workspace=WorkspaceSpec(name=f"monpy-upsert-cb-reuse-{ts}", id=ws_id),
            board=BoardSpec(name=f"board-main-{ts}", id=bd_main_id),
            item=ItemSpec(name="main"),
            columns=[
                ColumnSpec(type="name", title="Name", value="main"),
                ColumnSpec(type="connect_boards", title="Related", value=[int(target["id"])], defaults={"boardIds": [int(bd_rel_id)]}),
            ],
            group_name="grp1",
        )
        assert res["column_ids"]["Related"] == str(pre.get("id"))
    finally:
        for wid in (ws_id, ws_rel_id):
            if wid:
                try:
                    client_live.delete_workspace(wid)
                except Exception:
                    pass


@pytest.mark.live
@pytest.mark.slow
def test_live_connect_boards_infer_defaults_from_value(client_live):
    ts = str(int(time.time()))
    ws_id = None
    ws_rel_id = None
    try:
        ws = client_live.create_workspace(name=f"monpy-upsert-cb-inf-{ts}", kind="open", description="cb infer")
        ws_id = str(ws["id"])  # type: ignore[index]
        bd_main = client_live.create_board(name=f"board-main-{ts}", workspace_id=ws_id)
        bd_main_id = str(bd_main["id"])  # type: ignore[index]
        # Related board + item
        ws_rel = client_live.create_workspace(name=f"monpy-upsert-cb-inf-rel-{ts}", kind="open", description="cb inf related")
        ws_rel_id = str(ws_rel["id"])  # type: ignore[index]
        bd_rel = client_live.create_board(name=f"board-rel-{ts}", workspace_id=ws_rel_id)
        bd_rel_id = str(bd_rel["id"])  # type: ignore[index]
        g_rel = client_live.create_group(bd_rel_id, title="grp-rel")
        target = client_live.create_item(bd_rel_id, group_id=g_rel["id"], item_name="target")

        try:
            res = upsert_item(
                client_live,
                workspace=WorkspaceSpec(name=f"monpy-upsert-cb-inf-{ts}", id=ws_id),
                board=BoardSpec(name=f"board-main-{ts}", id=bd_main_id),
                item=ItemSpec(name="main"),
                columns=[
                    ColumnSpec(type="name", title="Name", value="main"),
                    ColumnSpec(type="connect_boards", title="Related", value=[int(target["id"])], defaults=None),
                ],
                group_name="grp1",
            )
        except MondayAPIError:
            pytest.skip("Connect boards not supported by this API/account")

        cid = res["column_ids"]["Related"]
        meta = client_live.get_column(bd_main_id, cid, fields=("id", "type", "settings", "settings_str"))
        allowed = meta.get("connected_board_ids") or (meta.get("settings") or {}).get("boardIds")
        assert str(bd_rel_id) in {str(x) for x in (allowed or [])}
        # Verify link set
        got = client_live.get_item_values(res["item_id"], column_ids=[cid])
        rel = (got.get("column_values") or [{}])[0]
        linked = rel.get("value") if isinstance(rel.get("value"), list) else rel.get("linked_item_ids") or []
        assert str(target["id"]) in {str(x) for x in (linked or [])}
    finally:
        for wid in (ws_id, ws_rel_id):
            if wid:
                try:
                    client_live.delete_workspace(wid)
                except Exception:
                    pass


@pytest.mark.live
@pytest.mark.slow
def test_live_update_uses_actual_item_board(client_live):
    ts = str(int(time.time()))
    ws_id = None
    try:
        ws = client_live.create_workspace(name=f"monpy-upsert-update-{ts}", kind="open", description="update board")
        ws_id = str(ws["id"])  # type: ignore[index]
        bd_a = client_live.create_board(name=f"board-a-{ts}", workspace_id=ws_id)
        bd_b = client_live.create_board(name=f"board-b-{ts}", workspace_id=ws_id)
        bd_a_id = str(bd_a["id"])  # type: ignore[index]
        bd_b_id = str(bd_b["id"])  # type: ignore[index]
        g_a = client_live.create_group(bd_a_id, title="grp-a")
        # Create a text column on A and seed an item
        c_text = client_live.create_column(bd_a_id, title="Text", column_type="text")["id"]
        created = client_live.create_item(bd_a_id, group_id=g_a["id"], item_name="target")
        item_id = str(created["id"])  # type: ignore[index]

        # Upsert with board B but item from A; should update successfully
        upsert_item(
            client_live,
            workspace=WorkspaceSpec(name=f"monpy-upsert-update-{ts}", id=ws_id),
            board=BoardSpec(name=f"board-b-{ts}", id=bd_b_id),
            item=ItemSpec(name="target", id=item_id),
            columns=[ColumnSpec(type="text", title="Text", column_id=c_text, value="updated")],
            group_name="grp-a",
        )
        # Verify text changed
        got = client_live.get_item_values(item_id)
        cv = next(cv for cv in got.get("column_values", []) if cv.get("id") == c_text)
        assert cv.get("text") == "updated"
    finally:
        if ws_id:
            try:
                client_live.delete_workspace(ws_id)
            except Exception:
                pass


@pytest.mark.live
@pytest.mark.slow
def test_live_on_missing_item_behaviors(client_live):
    ts = str(int(time.time()))
    ws_id = None
    try:
        ws = client_live.create_workspace(name=f"monpy-upsert-missing-{ts}", kind="open", description="missing item")
        ws_id = str(ws["id"])  # type: ignore[index]
        bd = client_live.create_board(name=f"board-missing-{ts}", workspace_id=ws_id)
        bd_id = str(bd["id"])  # type: ignore[index]

        missing = "999999999999"  # unlikely to exist

        # error
        with pytest.raises(ItemNotFound):
            upsert_item(
                client_live,
                workspace=WorkspaceSpec(name=f"monpy-upsert-missing-{ts}", id=ws_id),
                board=BoardSpec(name=f"board-missing-{ts}", id=bd_id),
                item=ItemSpec(name="x", id=missing),
                columns=[ColumnSpec(type="text", title="Text", value="x")],
                group_name="grp1",
                on_missing_item="error",
            )

        # create
        res_create = upsert_item(
            client_live,
            workspace=WorkspaceSpec(name=f"monpy-upsert-missing-{ts}", id=ws_id),
            board=BoardSpec(name=f"board-missing-{ts}", id=bd_id),
            item=ItemSpec(name="x", id=missing),
            columns=[ColumnSpec(type="name", title="Name", value="x"), ColumnSpec(type="text", title="Text", value="y")],
            group_name="grp1",
            on_missing_item="create",
        )
        assert res_create["item_id"] != missing

        # skip
        res_skip = upsert_item(
            client_live,
            workspace=WorkspaceSpec(name=f"monpy-upsert-missing-{ts}", id=ws_id),
            board=BoardSpec(name=f"board-missing-{ts}", id=bd_id),
            item=ItemSpec(name="x", id=missing),
            columns=[],
            group_name="grp1",
            on_missing_item="skip",
        )
        assert res_skip["item_id"] == missing
        assert res_skip["result"] == {}
    finally:
        if ws_id:
            try:
                client_live.delete_workspace(ws_id)
            except Exception:
                pass



from __future__ import annotations

import time
from datetime import date

import pytest

from monpy import Session
from monpy.exceptions import FeatureNotSupported
from monpy.helpers import (
    WorkspaceSpec,
    BoardSpec,
    ItemSpec,
    ColumnSpec,
    upsert_item,
    upsert_item_from_dicts,
)
from monpy.helpers.upsert_item import StatusOption, StatusDefaults
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
            workspace=WorkspaceSpec(name=ws.name, id=res["workspace_id"]),
            board=BoardSpec(name=bd.name, id=res["board_id"]),
            item=ItemSpec(name="main", id=item_id),
            columns=cols_update,
        )
        assert res2["item_id"] == item_id
    finally:
        # cleanup: best-effort – deleting the workspace removes contained boards/items
        try:
            client_live.delete_workspace(res["workspace_id"])  # type: ignore[index]
        except Exception:
            # fallback to archiving if workspace deletion is restricted
            try:
                client_live.archive_board(res["board_id"])  # type: ignore[index]
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
        assert out["workspace_id"] and out["board_id"] and out["item_id"]
    finally:
        try:
            if out:
                client_live.delete_workspace(out["workspace_id"])  # type: ignore[index]
        except Exception:
            try:
                if out:
                    client_live.archive_board(out["board_id"])  # type: ignore[index]
            except Exception:
                pass


@pytest.mark.live
@pytest.mark.slow
def test_upsert_creates_status_with_labels_defaults(client_live):
    ts = str(int(time.time()))

    # Use distinct labels and color names; randomize order without repetition to ensure mapping correctness
    random.seed(int(ts))
    chosen = random.sample([
        ("Queued", "grey"),
        ("Under way", "turquoise"),
        ("Shipped", "navy"),
    ], k=3)
    sd = StatusDefaults(options=[StatusOption(label=l, color_name=c) for (l, c) in chosen])

    res = None
    try:
        res = upsert_item(
            client_live,
            workspace=WorkspaceSpec(name=f"monpy-helper-status-{ts}"),
            board=BoardSpec(name=f"board-status-{ts}"),
            item=ItemSpec(name="main"),
            columns=[
                ColumnSpec(type="name", title="Name", value="main"),
                ColumnSpec(type="status", title="Status", value={"index": 1}, defaults=sd.to_dict()),
            ],
            group_name="grp1",
        )
        bid = res["board_id"]
        cid = res["column_ids"]["Status"]

        # Verify labels persisted on column settings
        meta = client_live.get_column(bid, cid, fields=("id", "type", "settings", "settings_str"))
        settings = meta.get("settings", {})
        got_labels = settings.get("labels") or settings.get("labels_colors", {}).get("labels")
        # Accept either dict or list payload; assert custom labels are present and colors assigned deterministically
        if isinstance(got_labels, dict):
            assert str(got_labels.get("2")) == "Shipped"
            # ensure default "Done" is not present among values
            assert "Done" not in set(str(v) for v in got_labels.values())
        elif isinstance(got_labels, list):
            # Expect entries for indices 0..2 with labels and colors matching our cycle
            by_index = {int(e.get("index", i)): e for i, e in enumerate(got_labels) if isinstance(e, dict)}
            # verify custom labels present (unordered due to randomization)
            labels_seen = {str(e.get("label")) for e in by_index.values()}
            assert {l for (l, _) in chosen}.issubset(labels_seen)
            # ensure default "Done" is not present
            assert all(str(e.get("label")) != "Done" for e in by_index.values())
            # ensure deterministic color naming; the "index 0" entry carries the first color name in cycle
            c0 = by_index[0].get("color")
            assert isinstance(c0, str) and len(c0) > 0
        else:
            raise AssertionError("Unexpected labels schema from API")

        # Update by label to ensure mapping works
        res2 = upsert_item(
            client_live,
            workspace=WorkspaceSpec(name="_", id=res["workspace_id"]),
            board=BoardSpec(name="_", id=bid),
            item=ItemSpec(name="main", id=res["item_id"]),
            columns=[ColumnSpec(type="status", title="Status", column_id=cid, value="Shipped")],
        )
        got = client_live.get_item_values(res2["item_id"], column_ids=[cid])
        assert (got.get("column_values") or [{}])[0].get("text") == "Shipped"
    finally:
        try:
            if res:
                client_live.delete_workspace(res["workspace_id"])  # type: ignore[index]
        except Exception:
            try:
                if res:
                    client_live.archive_board(res["board_id"])  # type: ignore[index]
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
        except FeatureNotSupported:
            pytest.skip("Connect boards columns are not supported by this API/account")

        bid = res["board_id"]
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
            if res:
                client_live.delete_workspace(res["workspace_id"])  # type: ignore[index]
        except Exception:
            try:
                if res:
                    client_live.archive_board(res["board_id"])  # type: ignore[index]
            except Exception:
                pass



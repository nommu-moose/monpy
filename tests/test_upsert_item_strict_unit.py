from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple
import importlib

import pytest

from monpy.exceptions import ColumnNotFound, ItemNotFound, MondayAPIError
from monpy.helpers.upsert_item import (
    BoardSpec,
    ColumnSpec,
    ItemSpec,
    WorkspaceSpec,
    upsert_item,
)


class FakeClient:
    def __init__(self) -> None:
        self.columns_by_board: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self.items_by_id: Dict[str, Dict[str, Any]] = {}
        self.groups_by_board: Dict[str, List[Dict[str, Any]]] = {}
        self.next_col = 1
        self.next_item = 1
        self.update_calls: List[Tuple[str, str, Dict[str, Any]]] = []
        self.safe_update_exc: Optional[MondayAPIError] = None

    # -------------- minimal columns API --------------
    def get_columns(self, board_id: str, *, fields=None, parse_settings: bool = True) -> List[Dict[str, Any]]:
        cols = list(self.columns_by_board.get(board_id, {}).values())
        # Attach connected_board_ids convenience if settings present
        out = []
        for c in cols:
            cc = dict(c)
            typ = str(cc.get("type", "")).lower()
            settings = cc.get("settings", {}) or {}
            if typ in ("board_relation", "connect_boards"):
                board_ids = (
                    cc.get("connected_board_ids")
                    or settings.get("boardIds")
                    or settings.get("board_ids")
                    or settings.get("connected_boards")
                    or []
                )
                cc["connected_board_ids"] = [str(b) for b in board_ids]
            out.append(cc)
        return out

    def get_column(self, board_id: str, column_id: str, *, fields=None, parse_settings: bool = True) -> Dict[str, Any]:
        col = self.columns_by_board.get(board_id, {}).get(column_id)
        if not col:
            raise ColumnNotFound(f"Column {column_id} not found on board {board_id}")
        return dict(col)

    def create_column(self, board_id: str, *, title: str, column_type: str, defaults: Optional[Mapping[str, Any]] = None, description: Optional[str] = None, fields=None) -> Dict[str, Any]:
        col_id = f"c{self.next_col}"
        self.next_col += 1
        tnorm = str(column_type or "").lower()
        if tnorm == "connect_boards":
            tnorm = "board_relation"
        settings: Dict[str, Any] = {}
        if isinstance(defaults, Mapping):
            settings = dict(defaults)
        col = {
            "id": col_id,
            "title": title,
            "type": tnorm,
            "settings": settings,
        }
        # annotate connected ids for convenience
        if tnorm == "board_relation":
            board_ids = (
                settings.get("boardIds")
                or settings.get("board_ids")
                or settings.get("connected_boards")
                or []
            )
            col["connected_board_ids"] = [str(b) for b in board_ids]
        self.columns_by_board.setdefault(board_id, {})[col_id] = col
        return dict(col)

    # -------------- minimal items API --------------
    def update_item_values(self, board_id: str, item_id: str, *, column_values: Dict[str, Any]) -> None:
        self.update_calls.append((board_id, item_id, dict(column_values)))

    def safe_update_item_values(self, board_id: str, item_id: str, *, column_values: Dict[str, Any]) -> None:
        if self.safe_update_exc is not None:
            exc = self.safe_update_exc
            self.safe_update_exc = None
            raise exc
        self.update_item_values(board_id, item_id, column_values=column_values)

    def create_item(self, board_id: str, *, group_id: str, item_name: str, column_values: Dict[str, Any]) -> Dict[str, Any]:
        iid = f"i{self.next_item}"
        self.next_item += 1
        self.items_by_id[iid] = {"id": iid, "board_id": board_id, "name": item_name, "column_values": dict(column_values)}
        return {"id": iid}

    def get_item_values(self, item_id: str, *, include_board: bool = False, **_: Any) -> Dict[str, Any]:
        itm = self.items_by_id.get(item_id)
        if not itm:
            raise ItemNotFound(f"Item {item_id} not found")
        out = {"id": itm["id"], "name": itm.get("name", "")}
        if include_board:
            out["board"] = {"id": itm["board_id"], "name": f"Board-{itm['board_id']}"}
        out["column_values"] = []
        return out

    # -------------- minimal groups API --------------
    def list_groups(self, board_id: str) -> List[Dict[str, Any]]:
        return self.groups_by_board.get(board_id, [{"id": "grp1", "title": "grp1"}])

    def create_group(self, board_id: str, *, title: str) -> Dict[str, Any]:
        g = {"id": f"grp-{title}", "title": title}
        self.groups_by_board.setdefault(board_id, []).append(g)
        return g


# ---------------------------- fixtures ----------------------------


@pytest.fixture()
def fake_env(monkeypatch):
    client = FakeClient()
    # Bypass workspace/board/group resolvers to keep tests offline/simple
    up_mod = importlib.import_module("monpy.helpers.upsert_item")
    monkeypatch.setattr(up_mod, "_ensure_workspace", lambda c, w: "ws1", raising=True)
    def _ensure_board(_client, spec, *, workspace_id: str) -> str:  # noqa: ARG001
        return getattr(spec, "id") or "b1"
    monkeypatch.setattr(up_mod, "_ensure_board", _ensure_board, raising=True)
    monkeypatch.setattr(up_mod, "_ensure_group", lambda c, b, **k: "grp1", raising=True)
    return client


# ---------------------------- tests ----------------------------


def test_type_mismatch_creates_new_column(monkeypatch, fake_env: FakeClient):
    client = fake_env
    # Pre-existing text column with the same title
    client.create_column("b1", title="Field", column_type="text")
    # Request status under same title
    res = upsert_item(
        client,
        workspace=WorkspaceSpec(name="ws"),
        board=BoardSpec(name="bd", id="b1"),
        item=ItemSpec(name="main"),
        columns=[ColumnSpec(type="status", title="Field", value={"index": 0}, defaults={"labels": [{"index": 0, "label": "Queued"}]})],
        group_name="grp1",
    )
    # Column id should not be the text column id
    text_id = next(iter(client.columns_by_board["b1"]))
    status_id = res["column_ids"]["Field"]
    assert status_id != text_id
    # Ensure a status column now exists
    col = client.get_column("b1", status_id)
    assert col["type"] == "status"


def test_type_disambiguation_picks_same_type(monkeypatch, fake_env: FakeClient):
    client = fake_env
    c_text = client.create_column("b1", title="Field", column_type="text")["id"]
    c_status = client.create_column("b1", title="Field", column_type="status")["id"]
    res = upsert_item(
        client,
        workspace=WorkspaceSpec(name="ws"),
        board=BoardSpec(name="bd", id="b1"),
        item=ItemSpec(name="main"),
        columns=[ColumnSpec(type="status", title="Field", value={"index": 0})],
        group_name="grp1",
    )
    assert res["column_ids"]["Field"] == c_status
    assert res["column_ids"]["Field"] != c_text


def test_reuse_compatible_connect_boards(fake_env: FakeClient):
    client = fake_env
    # Pre-existing connect boards allows 200 and 201
    client.create_column("b1", title="Related", column_type="board_relation", defaults={"boardIds": [200, 201]})
    res = upsert_item(
        client,
        workspace=WorkspaceSpec(name="ws"),
        board=BoardSpec(name="bd", id="b1"),
        item=ItemSpec(name="main"),
        columns=[ColumnSpec(type="connect_boards", title="Related", value=[], defaults={"boardIds": [200]})],
        group_name="grp1",
    )
    # Should reuse existing column (id equals the only column on b1)
    existing_id = next(iter(client.columns_by_board["b1"]))
    assert res["column_ids"]["Related"] == existing_id


def test_infer_connect_defaults_from_values(fake_env: FakeClient):
    client = fake_env
    # Seed an item on board 200; value will reference it
    client.items_by_id["2001"] = {"id": "2001", "board_id": "200", "name": "t"}

    res = upsert_item(
        client,
        workspace=WorkspaceSpec(name="ws"),
        board=BoardSpec(name="bd", id="b1"),
        item=ItemSpec(name="main"),
        columns=[ColumnSpec(type="connect_boards", title="Related", value=["2001"])],
        group_name="grp1",
    )
    cid = res["column_ids"]["Related"]
    meta = client.get_column("b1", cid)
    assert "connected_board_ids" in meta
    assert "200" in set(meta.get("connected_board_ids") or [])


def test_item_board_id_used_for_updates(monkeypatch, fake_env: FakeClient):
    client = fake_env
    # Prepare boards: b2 is the actual item board
    c2 = client.create_column("b2", title="Text", column_type="text")["id"]
    # Seed an item on b2
    created = client.create_item("b2", group_id="grp1", item_name="t", column_values={})
    item_id = created["id"]
    # Call upsert specifying a different board id (b1) – should still update on b2
    upsert_item(
        client,
        workspace=WorkspaceSpec(name="ws"),
        board=BoardSpec(name="bd", id="b1"),
        item=ItemSpec(name="t", id=item_id),
        columns=[ColumnSpec(type="text", title="Text", column_id=c2, value="v")],
        group_name="grp1",
    )
    assert client.update_calls, "expected an update call"
    used_board_id, used_item_id, _ = client.update_calls[-1]
    assert used_board_id == "b2"
    assert used_item_id == item_id


def test_on_missing_item_skip(fake_env: FakeClient):
    client = fake_env
    res = upsert_item(
        client,
        workspace=WorkspaceSpec(name="ws"),
        board=BoardSpec(name="bd", id="b1"),
        item=ItemSpec(name="t", id="i-missing"),
        columns=[],
        group_name="grp1",
        on_missing_item="skip",
    )
    assert res["item_id"] == "i-missing"
    assert res["result"] == {}
    assert not client.update_calls


def test_on_missing_item_create(fake_env: FakeClient):
    client = fake_env
    res = upsert_item(
        client,
        workspace=WorkspaceSpec(name="ws"),
        board=BoardSpec(name="bd", id="b1"),
        item=ItemSpec(name="t", id="i-missing"),
        columns=[ColumnSpec(type="text", title="Text", value="hello")],
        group_name="grp1",
        on_missing_item="create",
    )
    assert res["item_id"].startswith("i")
    assert res["result"].get("id") == res["item_id"]


def test_on_missing_item_error(fake_env: FakeClient):
    client = fake_env
    with pytest.raises(ItemNotFound):
        upsert_item(
            client,
            workspace=WorkspaceSpec(name="ws"),
            board=BoardSpec(name="bd", id="b1"),
            item=ItemSpec(name="t", id="i-missing"),
            columns=[ColumnSpec(type="text", title="Text", value="hello")],
            group_name="grp1",
            on_missing_item="error",
        )


def test_status_index_to_label_uses_actual_settings(fake_env: FakeClient):
    client = fake_env
    c_status = client.create_column("b1", title="Status", column_type="status", defaults={
        "labels": {"0": {"label": "Queued"}, "1": {"label": "Under way"}}
    })["id"]
    # Seed an item to update
    item_id = client.create_item("b1", group_id="grp1", item_name="t", column_values={})["id"]
    upsert_item(
        client,
        workspace=WorkspaceSpec(name="ws"),
        board=BoardSpec(name="bd", id="b1"),
        item=ItemSpec(name="t", id=item_id),
        columns=[ColumnSpec(type="status", title="Status", column_id=c_status, value={"index": 1})],
        group_name="grp1",
    )
    _, _, last_vals = client.update_calls[-1]
    assert last_vals.get(c_status) == {"label": "Under way"}


def test_aggressive_safe_updates_filters_offending(fake_env: FakeClient):
    client = fake_env
    c_ok = client.create_column("b1", title="Text", column_type="text")["id"]
    c_bad = client.create_column("b1", title="Bad", column_type="text")["id"]
    # Seed item
    item_id = client.create_item("b1", group_id="grp1", item_name="t", column_values={})["id"]
    # Configure the next safe update to raise with offending column id
    client.safe_update_exc = MondayAPIError("validation", errors=[{"extensions": {"error_data": {"column_id": c_bad}}}])
    upsert_item(
        client,
        workspace=WorkspaceSpec(name="ws"),
        board=BoardSpec(name="bd", id="b1"),
        item=ItemSpec(name="t", id=item_id),
        columns=[
            ColumnSpec(type="text", title="Text", column_id=c_ok, value="ok"),
            ColumnSpec(type="text", title="Bad", column_id=c_bad, value="bad"),
        ],
        group_name="grp1",
        aggressive_safe_updates=True,
    )
    # The final update call must not include the offending column
    _, _, last_vals = client.update_calls[-1]
    assert c_ok in last_vals
    assert c_bad not in last_vals



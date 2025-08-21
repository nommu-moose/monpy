from monpy.oo.session import Session


def test_board_item_helpers_and_filters():
    class FakeClient:
        def get_board(self, bid):
            return {"id": bid, "name": "B"}

        def list_items(self, bid, **k):
            # emulate pagination and filters
            return ([{"id": "1", "name": "Apple"}, {"id": "2", "name": "Banana"}], None)

        def get_columns(self, bid):
            return []

    b = Session(FakeClient()).board("b")
    assert b.take_items(1)
    assert b.first_item()
    filtered = b.filter_items_by_name(name_contains="ana")
    assert any(it["name"] == "Banana" for it in filtered)


def test_subitem_set_connected_and_refresh():
    class FakeClient:
        def get_subitem_values(self, sid, include_board=True):
            return {"id": sid, "name": "S", "state": "active", "updated_at": "t", "board": {"id": "b"}, "column_values": []}

        def _get_board_id_for_subitem(self, sid):
            return "b"

        def get_board(self, bid):
            return {"id": bid}

        def get_columns(self, bid):
            return [{"id": "c1", "title": "Links", "type": "connect_boards", "settings": {}}]

        def update_subitem_values(self, sid, *, column_values, board_id=None):
            assert "c1" in column_values

    sess = Session(FakeClient())
    si = sess.subitem("s1")
    si.refresh()
    si.set_connected_items(column_attr="links", linked_item_ids=[1, 2])



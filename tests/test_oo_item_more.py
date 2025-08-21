from monpy.oo.session import Session


def test_item_delete_and_refresh():
    class FakeClient:
        deleted = None
        def get_item_values(self, iid, include_board=True):
            return {"id": iid, "name": "i1", "state": "active", "updated_at": "t", "board": {"id": "b"}}
        def delete_item(self, iid):
            self.deleted = iid
    sess = Session(FakeClient())
    it = sess.item("i1")
    it.delete()
    assert getattr(sess.client, "deleted", None) == "i1"


def test_item_rename_archive_duplicate_move_methods():
    class FakeClient:
        def get_item_values(self, iid, include_board=True):
            return {"id": iid, "name": "i1", "state": "active", "updated_at": "t", "board": {"id": "b"}}
        def rename_item(self, iid, *, name):
            assert name == "New"
        def archive_item(self, iid):
            pass
        def unarchive_item(self, iid):
            pass
        def duplicate_item(self, iid, **k):
            return {"id": "ni"}
        def move_item_to_group(self, iid, **k):
            pass
        def move_item_to_board(self, iid, **k):
            return {"id": iid}

    sess = Session(FakeClient())
    it = sess.item("i1")
    it.rename("New")
    assert it.name == "New"
    it.archive()
    assert it.state == "archived"
    it.unarchive()
    assert it.state == "active"
    dup = it.duplicate(with_updates=False, with_assets=False, target_board_id="B2", target_group_id="g")
    assert dup["id"] == "ni"

    it.move_to_group("gg")
    res = it.move_to_board("B3", group_id="gg2")
    assert res["id"] == "i1"



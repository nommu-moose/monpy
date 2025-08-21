from monpy.oo.session import Session


def test_board_columns_cache_reset_on_refresh():
    class FakeClient:
        def __init__(self):
            self.calls = 0

        def get_board(self, bid):
            return {"id": bid}

        def get_columns(self, bid):
            self.calls += 1
            return [{"id": "c1", "title": "A", "type": "text", "settings": {}}]

    sess = Session(FakeClient())
    b = sess.board("b")
    # first access fills cache
    _ = b.columns
    first = sess.client.calls
    # refresh resets cache so next access refetches
    b.refresh()
    _ = b.columns
    assert sess.client.calls == first + 1


def test_board_groups_and_rename_duplicate_unarchive():
    class FakeClient:
        def get_board(self, bid):
            return {"id": bid, "name": "B", "board_kind": "public", "state": "active", "workspace_id": None, "updated_at": None}
        def get_columns(self, bid):
            return []
        def list_items(self, bid, **k):
            return ([], None)
        def rename_board(self, bid, *, name):
            pass
        def duplicate_board(self, bid, **k):
            return {"id": "NB"}
        def unarchive_board(self, bid):
            pass
        def list_groups(self, bid, **k):
            return [{"id": "g1", "title": "T", "archived": False}]
        def create_group(self, bid, **k):
            return {"id": "g2", "title": k.get("title"), "archived": False}
        def rename_group(self, bid, gid, **k):
            pass
        def archive_group(self, bid, gid):
            pass
        def delete_group(self, bid, gid):
            pass

    sess = Session(FakeClient())
    b = sess.board("B")
    b.rename("New")
    dup = b.duplicate(with_pulses=True, name="Copy")
    assert dup["id"] == "NB"
    b.unarchive()
    assert b.groups()[0]["id"] == "g1"
    g2 = b.create_group(title="New Group")
    assert g2["id"] == "g2"
    b.rename_group("g2", title="Renamed")
    b.archive_group("g2")
    b.delete_group("g2")


def test_board_subscribers_helpers():
    class FakeClient:
        def get_board(self, bid):
            return {"id": bid, "name": "B"}
        def get_columns(self, bid):
            return []
        def list_board_subscribers(self, bid, **k):
            return [{"id": "1"}]
        def add_board_subscribers(self, bid, ids, **k):
            assert ids == [1, 2]
        def remove_board_subscribers(self, bid, ids):
            assert ids == [1]

    sess = Session(FakeClient())
    b = sess.board("B")
    assert b.subscribers()[0]["id"] == "1"
    b.add_subscribers([1, 2])
    b.remove_subscribers([1])


def test_board_role_helpers():
    class FakeClient:
        def get_board(self, bid):
            return {"id": bid, "name": "B"}
        def get_columns(self, bid):
            return []
        def list_board_owners(self, bid, **k):
            return [{"id": "1"}]
        def list_board_members_by_role(self, bid, **k):
            return {"owners": [{"id": "1"}], "subscribers": [{"id": "2"}]}
        def add_board_owners(self, bid, ids):
            assert ids == [3]
        def set_board_subscriber_roles(self, bid, assignments):
            assert assignments == {4: "owner"}

    sess = Session(FakeClient())
    b = sess.board("B")
    assert b.owners()[0]["id"] == "1"
    roles = b.members_by_role()
    assert roles["subscribers"][0]["id"] == "2"
    b.add_owners([3])
    b.set_member_roles({4: "owner"})



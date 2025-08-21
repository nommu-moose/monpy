from monpy.oo.session import Session


def test_session_transaction_safe_and_batch(monkeypatch):
    calls = {"safe": 0, "batch": 0}

    class FakeClient:
        def get_item_values(self, iid, **k):
            return {"id": iid, "board": {"id": "b1"}}

        def get_board(self, bid):
            return {"id": bid}

        def get_columns(self, bid, **k):
            return [{"id": "c1", "title": "Text", "type": "text", "settings": {}}]

        def mutation(self, q, v):
            calls["batch"] += 1
            return {}

        def safe_update_item_values(self, *a, **k):
            calls["safe"] += 1

        def update_item_values(self, *a, **k):
            calls["batch"] += 1

    sess = Session(FakeClient())

    # batch mode: schedule two updates and commit
    it1 = sess.item("i1")
    it1.values.text = "a"
    it2 = sess.item("i2")
    it2.values.text = "b"
    with sess.transaction():
        it1.save()
        it2.save()
    assert calls["batch"] >= 1

    # safe mode: ensure safe path used
    calls["safe"] = 0
    it1.values.text = "x"
    with sess.transaction(safe=True):
        it1.save()
    assert calls["safe"] >= 1



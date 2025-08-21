import time

from monpy.oo.session import Session


def test_column_values_cache_ttl():
    class FakeClient:
        def __init__(self):
            self.calls = 0

        def get_item_values(self, iid, column_ids=None):
            self.calls += 1
            return {"id": iid, "column_values": [{"id": "c1", "value": {"text": "X"}, "text": "X", "type": "text"}]}

        def get_board(self, bid):
            return {"id": bid}

        def get_columns(self, bid):
            return [{"id": "c1", "title": "Text", "type": "text", "settings": {}}]

    sess = Session(FakeClient())
    sess.values_cache_ttl = 5.0
    it = sess.item("i1", board_id="b1")
    cv = it.values
    # First access triggers API call
    v1 = cv.text
    c = sess.client.calls
    # Second access within TTL hits cache (no new call)
    v2 = cv.text
    assert v1 == v2 and sess.client.calls == c
    # Now reduce TTL to 0 to force re-fetch on next access
    sess.values_cache_ttl = 0.0
    time.sleep(0.02)
    _ = cv.text
    assert sess.client.calls == c + 1



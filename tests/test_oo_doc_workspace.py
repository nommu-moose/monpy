from monpy.oo.doc import Doc
from monpy.oo.workspace import Workspace


def test_doc_read_and_replace(monkeypatch):
    class FakeClient:
        def get_all_blocks(self, doc_id, by_object_id=True, page_size=100):
            return [{"id": "b1", "type": "normal text"}, {"id": "b2", "type": "table"}]

        def mutation(self, q, v):
            return {}

        def create_doc_block(self, doc_id, *, block_type, content, after_block_id=None, fields=("id",)):
            return {"id": "blk"}

        def get_doc_text(self, doc_id, by_object_id=True, page_size=100):
            return "hello"

        _DELETABLE_DOC_BLOCK_TYPES = {"normal text", "table"}

    class Sess:
        def __init__(self):
            self.client = FakeClient()

    d = Doc(id="100").bind(Sess())
    # reading helpers just delegate
    assert d.blocks(by_object_id=False)
    assert isinstance(d.text(by_object_id=False), str)
    # replace text path (by real doc id)
    d.replace_plain_text("Hello")


def test_workspace_refresh_and_update(monkeypatch):
    class FakeClient:
        def get_workspace(self, wid):
            return {"id": wid, "name": "W", "kind": "open", "description": "D"}

        def update_workspace(self, wid, **attrs):
            return {"id": wid, **attrs}

    class Sess:
        def __init__(self):
            self.client = FakeClient()

    ws = Workspace(id="w1").bind(Sess())
    ws.refresh()
    assert ws.name == "W"
    # mark and flush changes
    ws.name = "W2"
    ws.mark_dirty("name", ws.name)
    ws.save()



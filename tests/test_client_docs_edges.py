import json

from monpy import MondayClient, MondayAPIError, DocNotFound


def test_get_doc_not_found_raises():
    c = MondayClient(token="t")
    c.query = lambda q, v: {"docs": []}
    try:
        c.get_doc("nope")
    except DocNotFound as e:
        assert "not found" in str(e)
    else:
        assert False, "expected DocNotFound"


def test_blocks_to_plaintext_fallback_string():
    blocks = [{"content": "  raw  "}]
    assert MondayClient.blocks_to_plaintext(blocks) == "raw"



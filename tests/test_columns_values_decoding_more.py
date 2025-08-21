import json

from monpy.oo.columns.values import _decode_value


def test_decode_value_edge_cases():
    # invalid JSON string should fall back
    v = _decode_value("text", {"value": "{bad", "text": None})
    assert isinstance(v, str)
    # board_relation raw list case
    v2 = _decode_value("board_relation", {"value": ["1", 2], "text": None})
    assert v2 == [1, 2]
    # link prefers url or raw/text
    v3 = _decode_value("link", {"value": "http://x", "text": "T"})
    assert v3 == "http://x"
    # default fallback when both None
    v4 = _decode_value("numbers", {"value": None, "text": None})
    assert v4 is None



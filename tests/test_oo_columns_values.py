import types
from datetime import date, datetime

from monpy.oo.columns.values import _encode_value, _decode_value, LocationValue


def test_encode_value_variants():
    assert _encode_value("text", None) == ""
    assert _encode_value("text", 5) == "5"
    assert _encode_value("numbers", 3.14) == 3.14
    assert _encode_value("status", 2) == {"index": 2}
    assert _encode_value("status", "Done") == {"label": "Done"}
    assert _encode_value("date", date(2025, 1, 1)) == {"date": "2025-01-01"}
    assert _encode_value("person", 7) == {"personsAndTeams": [{"id": 7, "kind": "person"}]}
    assert _encode_value("people", [7, 8]) == {"personsAndTeams": [{"id": 7, "kind": "person"}, {"id": 8, "kind": "person"}]}
    assert _encode_value("board_relation", [1, 2]) == {"item_ids": [1, 2]}
    assert _encode_value("tags", [9]) == {"tag_ids": [9]}
    assert _encode_value("link", ("http://x", "X")) == {"url": "http://x", "text": "X"}


def test_decode_value_variants():
    assert _decode_value("text", {"value": None, "text": "hello"}) == "hello"
    assert _decode_value("numbers", {"value": None, "text": "1.5"}) == 1.5
    assert _decode_value("status", {"value": {"index": 1}, "text": "In Progress"}) == "In Progress"
    assert _decode_value("date", {"value": {"date": "2025-01-01"}, "text": None}) == "2025-01-01"
    assert _decode_value("people", {"value": {"personsAndTeams": [{"id": 3}]}, "text": None}) == [3]
    assert _decode_value("board_relation", {"value": {"item_ids": [1, 2]}, "text": None}) == [1, 2]
    assert _decode_value("tags", {"value": {"tag_ids": [5]}, "text": None}) == [5]
    assert _decode_value("link", {"value": {"url": "http://x"}, "text": None}) == "http://x"
    assert _decode_value("doc", {"value": {"files": [{"objectId": "abc"}]}, "text": None}) == "abc"


def test_location_encode_decode_roundtrip():
    lv = LocationValue(address="1600 Amphitheatre Pkwy, Mountain View, CA", city="Mountain View", state="CA", country="United States", country_code="US", zip="94043", lat=37.4220, lng=-122.0841)
    encoded = _encode_value("location", lv)
    assert isinstance(encoded, dict) and encoded.get("address")
    decoded = _decode_value("location", {"value": encoded, "text": "Googleplex"})
    assert isinstance(decoded, LocationValue)
    assert decoded.city == "Mountain View"
    assert decoded.text == "Googleplex"

    # Accept plain string
    encoded2 = _encode_value("location", "Paris, France")
    assert encoded2 == {"address": "Paris, France"}
    decoded2 = _decode_value("location", {"value": {"address": "Paris, France"}, "text": "Paris, France"})
    assert isinstance(decoded2, LocationValue) and (decoded2.address or decoded2.text)



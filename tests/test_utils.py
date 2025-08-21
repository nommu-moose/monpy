import json
from datetime import date, datetime

import pytest

from monpy import MondayClient
from monpy.oo.utils import to_attr


def test_to_attr_basic_normalization():
    assert to_attr("Due Date") == "due_date"
    assert to_attr("Hello-World!") == "hello_world"
    assert to_attr("  A  B   ") == "a_b"


def test_to_attr_leading_digit_and_empty():
    assert to_attr("123Name") == "c_123name"
    assert to_attr("") == "value"


def test_blocks_to_plaintext_parses_json_and_strings():
    blocks = [
        {"content": json.dumps({"deltaFormat": [{"insert": "Hello\n"}]})},
        {"content": {"deltaFormat": [{"insert": "World"}]}},
        {"content": "raw text paragraph"},
        {"content": {"deltaFormat": [{"insert": "!"}]}},
    ]
    txt = MondayClient.blocks_to_plaintext(blocks)
    assert txt == "Hello\nWorld\nraw text paragraph\n!"



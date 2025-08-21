import pytest
from monpy import MondayClient


def test_requires_nonempty_token():
    with pytest.raises(ValueError):
        MondayClient(token="")


def test_session_headers_have_token_and_api_version_and_ua():
    c = MondayClient(token="abc123", api_version="2025-10")
    h = c._session.headers
    assert h["Authorization"] == "abc123"
    assert h["API-Version"] == "2025-10"
    assert h.get("User-Agent", "").startswith("monpy/")



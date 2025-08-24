import pytest


@pytest.mark.live
def test_iter_workspaces_smoke(client_live):
    # Only fetch a tiny page to avoid touching real data extensively
    got = client_live.get_all_workspaces(page_size=1, max_items=2, fields=("id",))
    assert isinstance(got, list) and len(got) <= 2



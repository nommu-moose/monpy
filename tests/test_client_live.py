import pytest


@pytest.mark.live
def test_list_workspaces_smoke(client_live):
    workspaces = client_live.list_workspaces(limit=1)
    assert isinstance(workspaces, list)



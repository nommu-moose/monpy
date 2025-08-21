from monpy import MondayClient


def test_list_workspaces_and_boards_field_selection(monkeypatch):
    c = MondayClient(token="t")
    captured = {}
    def q(query, vars):
        captured["query"] = query
        return {"workspaces": [{"id": "w"}]}
    c.query = q
    c.list_workspaces(limit=5, fields=("id",))
    assert "workspaces" in captured["query"] and "id" in captured["query"]

    captured.clear()
    def qb(q, v):
        captured["query"] = q
        return {"boards": []}
    c.query = qb
    c.list_boards(limit=1, fields=("id",))
    assert "boards" in captured["query"] and "id" in captured["query"]



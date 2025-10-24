from monpy.oo import WorkspaceKind, BoardKind, BoardState, ItemState, ColumnType


def test_workspace_kind_values():
    assert WorkspaceKind.OPEN.value == "open"
    assert BoardKind.PUBLIC.value == "public"
    assert BoardState.ACTIVE.value == "active"
    assert ItemState.DELETED.value == "deleted"
    assert ColumnType.DOC.value == "doc"



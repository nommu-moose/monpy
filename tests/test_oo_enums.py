from monpy.oo.enums import WorkspaceKind, BoardKind, BoardState, ItemState, ColumnType


def test_enums_values_exist():
    assert WorkspaceKind.OPEN.value == "open"
    assert BoardKind.PUBLIC.value == "public"
    assert BoardState.ACTIVE.value == "active"
    assert ItemState.DELETED.value == "deleted"
    assert ColumnType.DOC.value == "doc"



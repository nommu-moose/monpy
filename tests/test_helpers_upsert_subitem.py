from __future__ import annotations
import time
from datetime import date
import pytest
from monpy.helpers import (
    upsert_item,
    WorkspaceSpec,
    BoardSpec,
    ItemSpec,
    ColumnSpec,
    upsert_subitem,
    ParentItemSpec,
    SubitemSpec,
)
from monpy.exceptions import SubItemNotFound, BoardNotFound


@pytest.fixture(scope="module")
def live_workspace_and_board(client_live):
    """Creates a temporary workspace and board for the test module."""
    ts = str(int(time.time()))
    ws_name = f"monpy-subitem-helper-ws-{ts}"
    board_name = f"monpy-subitem-helper-board-{ts}"

    # Create the workspace first
    ws_res = client_live.create_workspace(name=ws_name, kind="open")
    workspace_id = ws_res["id"]

    # Create the board with subitems enabled
    board_res = client_live.create_board(
        name=board_name,
        board_kind="public",
        workspace_id=workspace_id,
    )
    board_id = board_res["id"]
    
    # Create a parent item on the board
    group_res = client_live.create_group(board_id, title="Parents")
    group_id = group_res["id"]
    item_res = client_live.create_item(board_id=board_id, group_id=group_id, item_name="Parent Item for Subitem Tests")
    parent_item_id = item_res["id"]

    yield {
        "workspace_id": workspace_id,
        "board_id": board_id,
        "parent_item_id": parent_item_id,
    }

    # Teardown
    try:
        client_live.delete_workspace(workspace_id)
    except Exception:
        pass


@pytest.mark.live
@pytest.mark.slow
class TestUpsertSubitem:
    def test_create_subitem_successfully(self, client_live, live_workspace_and_board):
        # Arrange
        parent_item_id = live_workspace_and_board["parent_item_id"]
        subitem_name = f"New Subitem {int(time.time())}"

        # Act
        result = upsert_subitem(
            client_live,
            parent_item=ParentItemSpec(id=parent_item_id),
            subitem=SubitemSpec(name=subitem_name),
            columns=[
                ColumnSpec(type="text", title="Info", value="Details"),
                ColumnSpec(type="status", title="Progress", value={"index": 0}, defaults={"labels": ["Todo", "Done"]}),
            ],
        )

        # Assert
        assert result is not None
        assert result["subitem_id"] is not None
        assert "Info" in result["column_ids"]
        assert "Progress" in result["column_ids"]
        
        subitem_data = result["result"]
        assert subitem_data["name"] == subitem_name
        
        # Verify column values
        info_val = next((cv for cv in subitem_data["column_values"] if cv["id"] == result["column_ids"]["Info"]), None)
        assert info_val is not None and info_val["text"] == "Details"

        progress_val = next((cv for cv in subitem_data["column_values"] if cv["id"] == result["column_ids"]["Progress"]), None)
        assert progress_val is not None and progress_val["text"] == "Todo"


    def test_update_subitem_by_id(self, client_live, live_workspace_and_board):
        # Arrange: Create a subitem first
        parent_item_id = live_workspace_and_board["parent_item_id"]
        subitem_name = f"Subitem to Update by ID {int(time.time())}"
        
        create_result = upsert_subitem(
            client_live,
            parent_item=ParentItemSpec(id=parent_item_id),
            subitem=SubitemSpec(name=subitem_name),
            columns=[ColumnSpec(type="text", title="Status", value="Initial")],
        )
        subitem_id = create_result["subitem_id"]

        # Act: Update the subitem by its ID
        updated_name = f"Updated Subitem {int(time.time())}"
        update_result = upsert_subitem(
            client_live,
            parent_item=ParentItemSpec(id=parent_item_id),
            subitem=SubitemSpec(id=subitem_id, name=updated_name),
            columns=[
                ColumnSpec(type="name", title="Name", value=updated_name),
                ColumnSpec(type="text", title="Status", value="Completed"),
            ],
        )

        # Assert
        assert update_result["subitem_id"] == subitem_id
        retrieved_subitem = client_live.get_subitem_values(subitem_id)
        assert retrieved_subitem["name"] == updated_name
        
        status_col_id = update_result["column_ids"]["Status"]
        status_val = next((cv for cv in retrieved_subitem["column_values"] if cv["id"] == status_col_id), None)
        assert status_val is not None and status_val["text"] == "Completed"


    def test_update_subitem_by_name(self, client_live, live_workspace_and_board):
        # Arrange: Create a subitem
        parent_item_id = live_workspace_and_board["parent_item_id"]
        subitem_name = f"Subitem to Update by Name {int(time.time())}"
        upsert_subitem(
            client_live,
            parent_item=ParentItemSpec(id=parent_item_id),
            subitem=SubitemSpec(name=subitem_name),
            columns=[ColumnSpec(type="numbers", title="Value", value=100)],
        )

        # Act: Update by name
        update_result = upsert_subitem(
            client_live,
            parent_item=ParentItemSpec(id=parent_item_id),
            subitem=SubitemSpec(name=subitem_name), # No ID
            columns=[ColumnSpec(type="numbers", title="Value", value=200)],
        )

        # Assert
        subitem_id = update_result["subitem_id"]
        retrieved_subitem = client_live.get_subitem_values(subitem_id)
        value_col_id = update_result["column_ids"]["Value"]
        value_col = next((cv for cv in retrieved_subitem["column_values"] if cv["id"] == value_col_id), None)
        assert value_col is not None and value_col["text"] == "200"

    def test_on_missing_subitem_skip(self, client_live, live_workspace_and_board):
        # Arrange
        parent_item_id = live_workspace_and_board["parent_item_id"]
        non_existent_id = "9999999999"

        # Act
        result = upsert_subitem(
            client_live,
            parent_item=ParentItemSpec(id=parent_item_id),
            subitem=SubitemSpec(id=non_existent_id, name="Should not exist"),
            columns=[],
            on_missing_subitem="skip"
        )
        # Assert
        assert result["subitem_id"] == non_existent_id
        assert not result["result"] # Empty dict for result

    def test_on_missing_subitem_error(self, client_live, live_workspace_and_board):
        # Arrange
        parent_item_id = live_workspace_and_board["parent_item_id"]
        non_existent_id = "9999999998"

        # Act & Assert
        with pytest.raises(SubItemNotFound):
            upsert_subitem(
                client_live,
                parent_item=ParentItemSpec(id=parent_item_id),
                subitem=SubitemSpec(id=non_existent_id, name="Should raise error"),
                columns=[],
                on_missing_subitem="error"
            )

    def test_parent_board_without_subtasks_column(self, client_live):
        # Arrange: Create a board without a subtasks column
        ts = str(int(time.time()))
        ws_name = f"monpy-no-subtask-ws-{ts}"
        board_name = f"monpy-no-subtask-board-{ts}"
        res = upsert_item(
            client_live,
            workspace=WorkspaceSpec(name=ws_name),
            board=BoardSpec(name=board_name),
            item=ItemSpec(name="Parent With No Subtasks"),
            columns=[], # No subtasks column
        )
        parent_item_id = res["item_id"]
        
        # Act: subitem creation should succeed even without explicit subtasks column
        result = upsert_subitem(
            client_live,
            parent_item=ParentItemSpec(id=parent_item_id),
            subitem=SubitemSpec(name="Test"),
            columns=[],
        )
        assert result["subitem_id"]
        
        # Teardown
        try:
            client_live.delete_workspace(res["workspace_id"])
        except Exception:
            pass

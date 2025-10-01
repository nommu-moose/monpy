import os
from monpy.client import MondayClient

WORKSPACE_NAME = os.getenv("WORKSPACE_NAME", "People & Talent Ops")
BOARD_NAME = os.getenv("BOARD_NAME", "People")
API_TOKEN = os.getenv("MONDAY_API_TOKEN", "eyJhbGciOiJIUzI1NiJ9.eyJ0aWQiOjUxNDE4MDU5NiwiYWFpIjoxMSwidWlkIjo3MTI0OTMwNCwiaWFkIjoiMjAyNS0wNS0xN1QxMjo0ODo0MS4zNDhaIiwicGVyIjoibWU6d3JpdGUiLCJhY3RpZCI6MjQ3MTM3MjksInJnbiI6ImV1YzEifQ.DDK4LJZwnVU67Qn6K2HRUlZYWLBaFTRE4ADeV9-AvP8")


def resolve_workspace_and_board_ids(client: MondayClient, workspace_name: str, board_name: str) -> tuple[str, str]:
    workspaces = client.list_workspaces(limit=100, fields=("id", "name"))
    ws = next((w for w in workspaces if w["name"] == workspace_name), None)
    if not ws:
        raise SystemExit(f'Workspace "{workspace_name}" not found')
    workspace_id = str(ws["id"])

    boards = client.list_boards(limit=500, workspace_id=workspace_id, fields=("id", "name"))
    b = next((x for x in boards if x["name"] == board_name), None)
    if not b:
        raise SystemExit(f'Board "{board_name}" not found in workspace "{workspace_name}"')
    return workspace_id, str(b["id"])

def _count_links_in_cv(cv: dict) -> int:
    # Prefer typed field when available
    typed = cv.get("linked_item_ids")
    if isinstance(typed, list):
        return len(typed)

    raw = cv.get("value")
    # Legacy JSON shapes (parse_json_values=True decodes strings to dict)
    if isinstance(raw, dict):
        # Newer fallback
        if isinstance(raw.get("item_ids"), list):
            return len(raw["item_ids"])
        # Older legacy shape: {"linkedPulseIds":[{"linkedPulseId":123}, ...]}
        lp = raw.get("linkedPulseIds")
        if isinstance(lp, list):
            return len(lp)
    elif isinstance(raw, list):
        return len(raw)

    return 0

def gather_item_ids(client: MondayClient, board_id: str) -> list[str]:
    ids: list[str] = []
    # Count both active and archived items; add "deleted" if you truly need them too.
    for state in ("active", "archived"):
        items = client.get_all_items(board_id, page_size=200, state=state, fields=("id",))
        ids.extend(str(it["id"]) for it in items)
    return ids

def count_connect_relationships(client: MondayClient, board_id: str) -> int:
    cols = client.get_columns(board_id, fields=("id", "type"))
    connect_col_ids = [
        str(c["id"])
        for c in cols
        if str(c.get("type", "")).lower() in ("board_relation", "connect_boards")
    ]
    if not connect_col_ids:
        return 0

    item_ids = gather_item_ids(client, board_id)
    if not item_ids:
        return 0

    total = 0
    # Fetch only the connect columns; parse_json_values=True enables legacy JSON fallback.
    rows = client.get_items_values(
        item_ids,
        column_ids=connect_col_ids,
        parse_json_values=True,
        batch_size=200,  # tune as needed
    )
    for row in rows:
        for cv in row.get("column_values", []):
            t = str(cv.get("type", "")).lower()
            if t in ("board_relation", "connect_boards"):
                total += _count_links_in_cv(cv)
    return total

if __name__ == "__main__":
    if not API_TOKEN or API_TOKEN == "YOUR_API_TOKEN_HERE":
        raise SystemExit("Set MONDAY_API_TOKEN env var (or hardcode API_TOKEN)")

    client = MondayClient(token=API_TOKEN)
    ws_id, board_id = resolve_workspace_and_board_ids(client, WORKSPACE_NAME, BOARD_NAME)
    total = count_connect_relationships(client, board_id)

    print(f'Workspace: {WORKSPACE_NAME} ({ws_id})')
    print(f'Board: {BOARD_NAME} ({board_id})')
    print(f"Total connect board relationships on this board (active + archived): {total}")
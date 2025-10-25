monpy
=====

Lightweight synchronous client for the monday.com GraphQL API.

Installation
------------

From PyPI (preferred):

```bash
pip install monpy
```

From source (local dev):

```bash
pip install -e .
```

Usage
-----

```python
from monpy import MondayClient

client = MondayClient(token="YOUR_MONDAY_API_TOKEN")
workspaces = client.list_workspaces(limit=5)
print(workspaces)
```

You can also import via the api submodule:

```python
from monpy.api import MondayClient
```

Object-oriented API (new)
-------------------------

For a linter-friendly, attribute-first API with context managers and transactions, use the OO layer:

```python
from monpy import MondayClient, Session

client = MondayClient(token="YOUR_MONDAY_API_TOKEN")
sess = Session(client)

# Load board and edit items with attribute access
board = sess.board("123456789")

# Read a column value (auto-decoded)
first = board.first_item()
item = sess.item(first["id"], board_id=board.id)
print(item.values.status)        # e.g. "Done"
print(item.values.due_date)      # e.g. "2025-01-31" (ISO date string)

# Change values in a transaction (batched commit)
from datetime import date
with sess.transaction():
    item.values.status = "Working on it"
    item.values.due_date = date(2025, 1, 31)
    # changes are batched and committed at context exit

# Safe mode will skip invalid column updates (uses safe_update internally)
with sess.transaction(safe=True):
    item.values.people = [12345, 67890]  # invalid assignees will be skipped

# Create new item via the board helper
new_item = board.create_item(group_id="topics", item_name="New task", values={})
```

Sub-items
---------

```python
sub = sess.subitem("987654321")
print(sub.values.status)
sub.values.status = "Done"
sub.save()
```

Docs & files
------------

```python
from monpy.oo.doc import Doc
from monpy.oo.file_asset import upload_to_file_column

# Replace text of a doc in a doc column
sess.client.set_full_doc_plain_text(item_id=item.id, column_id="doc_col", body_text="Hello world")

# Upload a file to Files column
with open("report.pdf", "rb") as f:
    upload_to_file_column(sess, item_id=item.id, column_id="files", file_obj=f, filename="report.pdf")
```

Board item helpers
------------------

```python
for it in board.iter_items(limit_per_page=200):
    print(it["name"])  # raw dicts for speed

top10 = board.take_items(10)
maybe = board.first_item()
by_name = board.filter_items_by_name(name_contains="invoice")
```

Code generation for strong completion
-------------------------------------

You can optionally generate a typed `Item` subclass for a board. This emits per-column properties and a `.pyi` stub for better IDE completion.

```bash
python -m monpy.oo.codegen --token YOUR_MONDAY_API_TOKEN --board-id 123456789 --out src/monpy/generated
```

This will create `src/monpy/generated/<board>_item.py` and `<board>_item.pyi`. Example use:

```python
from monpy.generated.sales_pipeline_item import SalesPipelineItem
from monpy.oo import bind_session

@bind_session(sess)
class SalesItem(SalesPipelineItem):
    pass

it = SalesItem(id=item.id)
it.status = "Done"  # property proxies to it.values.status
it.save()
```

Caching reads of column values
------------------------------

To reduce API calls while reading values in loops, you can enable a small TTL cache per item:

```python
sess = Session(client, values_cache_ttl=2.0)  # seconds
v = item.values.status  # first read fetches from API and caches
v2 = item.values.status # returned from cache if within TTL
```

Helpers
-------

- Inventory: build a Workspace → Boards → Items tree using `monpy.helpers.build_workspace_board_item_tree`.

- Item Upsert: create or update an item with automatic workspace/board/column creation using `monpy.helpers.upsert_item`.

  ```python
  from monpy.client import MondayClient
  from monpy.helpers import WorkspaceSpec, BoardSpec, ItemSpec, ColumnSpec, upsert_item

  client = MondayClient(token="...")

  res = upsert_item(
      client,
      workspace=WorkspaceSpec(name="My Workspace"),
      board=BoardSpec(name="My Board"),
      item=ItemSpec(name="My Item"),
      columns=[
          ColumnSpec(type="name", title="Name", value="My Item"),
          ColumnSpec(type="text", title="Text", value="hello"),
          ColumnSpec(type="status", title="Status", value={"index": 1}),
          ColumnSpec(type="email", title="Email", value={"email": "u@example.com", "text": "User"}),
          ColumnSpec(type="people", title="Assignee", value=[]),
          ColumnSpec(type="connect_boards", title="Related", defaults={"boardIds": []}, value=[]),
          ColumnSpec(type="tags", title="Tags", value=[]),
      ],
      group_name="grp1",
  )
  print(res["item_id"], res["board_id"])  # created and set values
  ```

## Inventory Helpers

The inventory helpers batch-fetch workspaces, boards, and items from monday.com into object-oriented structures.

### Basic Inventory

Use `build_workspace_board_item_tree()` to fetch the lightweight structure (names and IDs only):

```python
from monpy import Session, build_workspace_board_item_tree

session = Session(client)
workspaces = build_workspace_board_item_tree(session)

for ws in workspaces:
    print(f"Workspace: {ws.name}")
    for board in ws.boards:
        print(f"  Board: {board.name} ({len(board.items)} items)")
        for item in board.items:
            print(f"    Item: {item.name}")
```

### Detailed Inventory with Decoded Values

Use `build_detailed_workspace_board_item_tree()` to fetch full column values with automatic type decoding:

```python
from monpy import Session, build_detailed_workspace_board_item_tree

session = Session(client)
workspaces = build_detailed_workspace_board_item_tree(
    session,
    include_decoded_values=True,
    page_size_items=200,
    items_batch_size=20,
)

for ws in workspaces:
    print(f"Workspace: {ws.name}")
    for board in ws.boards:
        print(f"  Board: {board.name}")
        for item in board.items:
            print(f"    Item: {item.name}")
            # Access decoded column values
            decoded = getattr(item, "decoded_values", {})
            for col_title, col_value in decoded.items():
                # Values are automatically decoded from JSON/raw formats
                # - Status → string label
                # - Date → ISO date string
                # - People → list of IDs
                # - Location → LocationValue object with structured data
                # - etc.
                print(f"      {col_title}: {col_value}")
```

#### Multithreading and Rate Limit Retries

Both inventory functions support multithreaded fetching with automatic rate limit retries:

```python
from monpy import Session, build_detailed_workspace_board_item_tree

session = Session(client)
workspaces = build_detailed_workspace_board_item_tree(
    session,
    include_decoded_values=True,
    num_threads=4,          # Fetch items from 4 boards concurrently (default: 4)
    max_retries=4,          # Retry rate-limited requests up to 4 times (default: 4)
    page_size_items=200,    # Items per page
    items_batch_size=20,    # Batch size for workspaces
)
```

**Parameters:**
- `num_threads` (int, default=4): Number of concurrent threads to use for fetching items from boards. Higher values = faster but more API calls.
- `max_retries` (int, default=4): Number of retry attempts for rate-limited requests. Uses exponential backoff: 1s, 2s, 4s, 8s.

**Rate Limit Handling:**
- Automatically retries on `RateLimitError` with exponential backoff
- Non-rate-limit errors are raised immediately
- Thread-safe: each thread manages its own retry logic

#### Features

- **Automatic Type Decoding**: All column values are decoded using the same logic as the upsert helper (but reversed)
- **Multithreaded Fetching**: Fetch items from multiple boards concurrently
- **Rate Limit Retries**: Automatic exponential backoff retry on rate limits
- **OO Structure**: Returns bound OO objects (Workspace, Board, Item) with Session context
- **Optional Values**: Pass `include_decoded_values=False` to skip value decoding and improve performance
- **Comprehensive Support**: Handles all column types: text, status, date, numbers, people, board_relation, tags, location, link, doc

#### Value Decoding Examples

The function automatically decodes monday.com's raw values:

```python
# Status: raw JSON → human-readable label
"status": "In Progress"  # instead of {"index": 1}

# Date: ISO string extracted from JSON
"due_date": "2025-12-31"  # instead of {"date": "2025-12-31"}

# People: list of person IDs
"assignee": [12345, 67890]  # instead of {"personsAndTeams": [{"id": 12345, ...}]}

# Location: structured LocationValue object
"location": LocationValue(
    address="123 Main St",
    city="New York",
    state="NY",
    lat=40.7128,
    lng=-74.0060,
)

# Board Relations: list of connected item IDs
"connected_items": [101, 102]  # instead of {"item_ids": [101, 102]}
```

Development
-----------

Requirements:
- Python 3.10+
- Hatch for builds and envs: `pipx install hatch` (or `pip install hatch`)

Common tasks:

```bash
# run tests (unit only by default)
hatch run test:tests

# run ruff linters and formatter (if you have Ruff installed)
ruff check .
ruff format .

# build sdist and wheel
hatch build

# check built distributions
pipx run twine check dist/*
```

Live API tests (optional):

```bash
# Use config file (ignored by git)
cp tests/config.example.json tests/config.json
# edit tests/config.json and set MONDAY_API_TOKEN (or "token")

# run only tests marked as live
pytest -q -m live
```

Webhooks live tests and mirror helper
-------------------------------------

To exercise webhook creation and delivery end-to-end:

1) Create `tests/config.json` (ignored by git) from the example and set required keys:

```json
{
  "MONDAY_API_TOKEN": "paste-your-token-here",
  "remote_test_site": "https://utils.today-hub.com"
}
```

2) Run the live webhook mirror test, which registers several webhook events to a helper endpoint and waits for the initial challenge payload:

```bash
pytest -q tests/test_webhook_mirror.py -m live --no-cov
```

Notes:
- Some accounts/tokens may restrict webhook creation; the tests will skip gracefully when not permitted.
- The mirror endpoint exposes both a receive URL and a mirror URL that returns the last captured request. The test polls the mirror with backoff and asserts that the challenge appears.
- Extend `tests/config.json` with knobs like `MAX_RETRIES`, `BACKOFF`, or `RETRIES` if needed for your environment.

Notes
-----
- `tests/config.json` is git-ignored and can store secrets such as `MONDAY_API_TOKEN` (or `token`) for live API tests.
- The public API surface is available as `monpy.MondayClient` and `monpy.api.MondayClient`.



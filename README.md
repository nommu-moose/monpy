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



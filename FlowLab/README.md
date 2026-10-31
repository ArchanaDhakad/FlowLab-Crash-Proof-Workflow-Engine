# FlowLab

FlowLab is a small local workflow playground. Create workflows as JSON steps,
save them in SQLite, and run them from the browser.

## Requirements

- Python 3.10 or newer
- pip

## Run locally

From the `FlowLab` directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
uvicorn backend.main:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). API documentation is
available at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

The SQLite database is created automatically at `backend/flowlab.db`.

## Workflow step format

Each workflow is a JSON array. Steps run in order, and their values are stored
in a shared data object:

```json
[
  { "type": "set", "key": "message", "value": "hello" },
  { "type": "uppercase", "key": "message" },
  { "type": "set", "key": "count", "value": 2 },
  { "type": "add", "key": "count", "value": 3 }
]
```

Supported step types:

- `set`: assign any JSON value to a key.
- `add`: add a number to the numeric value at a key (starts at `0`).
- `multiply`: multiply the numeric value at a key (starts at `1`).
- `uppercase`: uppercase the text value at a key.
- `append`: append a string to the text value at a key.

## API

- `GET /api/health` — check that the API is running.
- `GET /api/workflows` — list saved workflows.
- `POST /api/workflows` — save `{ "name": "...", "steps": [...] }`.
- `DELETE /api/workflows/{id}` — delete a workflow.
- `POST /api/workflows/{id}/run` — run it with optional initial data:
  `{ "data": { "key": "value" } }`.

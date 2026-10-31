# FlowLab

FlowLab is a local workflow playground. Create workflows in the visual step
editor or through the JSON API, save them in SQLite, and run them from the browser.

## Requirements

- Python 3.10 or newer
- pip

## Run locally

From the project root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
uvicorn backend.main:app --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Interactive API
documentation is available at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

The SQLite database is created automatically at `backend/flowlab.db`.

## Dashboard sign-up and sign-in

The first visitor can create the owner account using an email address and a
password of at least 12 characters, including one lowercase letter, one
uppercase letter, one number, and one special character. The password is
stored as a salted PBKDF2 hash in `backend/flowlab.db`, not as plain text.
After the first account is created, public sign-up closes; use that email and
password to sign in later.
This local dashboard supports one owner account, and its existing workflows,
executions, and schedules remain in the same database.

For safety, create the first account in a browser on the computer running
FlowLab (`http://127.0.0.1:8000`). Then sign in from your phone on the trusted
Wi-Fi if needed.

The workflow, execution, and schedule APIs require an authenticated session.
Sessions use an HttpOnly, SameSite cookie, write operations require a CSRF
token, sessions expire after eight hours, and repeated failed sign-in attempts
are temporarily locked out. Sign out from the top bar to end the current
session. There is no email verification or password-reset flow yet, so choose
a password you can keep safe.

## Open FlowLab on a phone

`127.0.0.1` on a phone means the phone itself, not your computer. To use the
dashboard from a phone on the same trusted Wi-Fi network:

1. Stop the currently running server in its terminal with `Ctrl+C`.
2. From the project root, start it on the local network interface:

   ```powershell
   uvicorn backend.main:app --host 0.0.0.0 --port 8000
   ```

3. On the computer, run `ipconfig` and find its Wi-Fi **IPv4 Address**
   (usually similar to `192.168.1.25`).
4. On the phone, connected to the same Wi-Fi, open
   `http://192.168.1.25:8000` and replace the example address with the
   computer's IPv4 address.

If Windows Firewall asks, allow Python/Uvicorn on **Private networks** only.
Create your account the first time you open FlowLab, then sign in with that
email and password. Do not use this LAN command on public Wi-Fi, enable
router port forwarding, or expose this app to the public internet. The
dashboard now requires a password, but it does not use HTTPS on a local
network connection, so use only a trusted private Wi-Fi network.

## Backend environment settings

The backend loads `backend/.env` using a path relative to `backend/main.py`, so
the server can be launched from the project root without relying on the current
working directory. Copy `backend/.env.example` to `backend/.env` and set only
the values needed by your workflows. Never commit `.env` or real credentials.

- `RETRY_DELAY_SECONDS` sets the pause between failed attempts of a step. It
  defaults to 1 second and is limited to 0–10 seconds.
- `AUTO_RESUME_ON_START` defaults to `false`. Set it to `true`, `1`, or `yes`
  to resume interrupted executions in a background thread after startup.
- `NOTIFY_EMAIL_ON_FAILURE` optionally sends a plain-text email when a manual,
  scheduled, or auto-resumed workflow run ends as failed. SMTP must be
  configured; notification errors are logged and do not change the run result.
- `SMTP_*`, `HTTP_ALLOWED_HOSTS`, and `WORKFLOW_FILE_ROOT` configure the
  existing email, HTTP, and file workflow steps. Leave unused settings blank.

## Dashboard behavior

The root frontend is a full-viewport responsive dashboard. Its visual workflow
editor lets you add, edit, and remove built-in data, email, HTTP, and file
steps; it also lets you create, select, run, and delete workflows, inspect
step-by-step execution history, and create, pause, resume, or delete schedules.

Workflows, execution history, and schedules are stored in the local SQLite
database, so they persist across browser sessions and backend restarts. A failed
step is attempted once plus up to three retries. If it still fails, the run is
saved and can be resumed from that step, optionally with corrected input data.
Interval and daily local-time schedules are checked every five seconds while
the backend is running; schedules do not run while the backend is stopped.

## Which project folder to run

This workspace also contains an older/nested `FlowLab` copy. Use the root-level
`backend` and `frontend` folders described by the commands above; the nested copy
is separate and is not required to run this app. Keep the terminal at this
project root when starting Uvicorn. Do not open `frontend/index.html` through
VS Code Live Server or as a local file: FastAPI serves the page and its
`/static/style.css`, `/static/script.js`, and `/api/...` routes from the same
origin at `http://127.0.0.1:8000`.

## Code ka flow aur run output

- `backend/main.py` FastAPI server aur HTTP routes chalata hai. `/` par dashboard,
  `/static/...` par uske assets, aur `/api/...` par workflow, execution, resume,
  aur schedule endpoints milte hain. Server start hote waqt interrupted runs ko
  resumable mark karta hai; optional `AUTO_RESUME_ON_START` unhe background mein
  resume karta hai.
- `backend/database.py` SQLite mein workflows, executions, aur schedules save,
  read, update, aur delete karta hai. Har workflow ke steps JSON text ke roop
  mein store hote hain; successful execution steps ki progress bhi persist hoti hai.
- `backend/workflow_engine.py` steps validate karta hai, `set`, `add`, `multiply`,
  `uppercase`, `append`, SMTP `email`, allowlisted HTTPS `http`, aur restricted
  `file` operations chalata hai, retry count track karta hai, aur failed run ko
  baad mein resume karne layak state mein save karta hai.
- HTTP response aur file result workflow data mein save hote hain, jisse baad
  ke steps unke fields jaise `{{customer.body.email}}` aur
  `{{source_file.content}}` use kar sakte hain.
- `backend/email_service.py` encrypted SMTP connection se plain-text email bhejta
  hai. SMTP credentials environment variables se aate hain, workflow JSON se nahi.
- `backend/http_service.py` allowlisted public HTTPS APIs ko timeout aur response
  size limit ke saath call karta hai. API secrets environment variables se aate
  hain, workflow JSON se nahi.
- `backend/file_service.py` configured workspace folder ke andar text files ko
  read, write, append, ya check karta hai; path traversal aur out-of-folder
  symlinks ko reject karta hai.
- `frontend/index.html`, `frontend/style.css`, aur `frontend/script.js`
  dashboard ka structure, responsive appearance, aur backend API se interaction
  sambhalte hain.
- `backend/requirements.txt` Python packages aur unki supported version ranges
  batata hai.

Server start hone par terminal mein Uvicorn ke `127.0.0.1:8000` par listening ka
message aayega. Startup par SQLite file/table zaroorat padne par banegi. Browser
mein [http://127.0.0.1:8000](http://127.0.0.1:8000) kholne par workflow editor aayega;
pehle saved workflow na ho to list mein `No workflows yet. Create one to get started.`
dikhai dega.

Page par pehle se bhara example save karke **Start Workflow** karne par API
response aur dashboard history mein output kuch is tarah dikhega (execution ID
aur duration har run mein alag honge):

```json
{
  "execution_id": 3,
  "status": "completed",
  "data": {
    "message": "HELLO FLOWLAB",
    "count": 5
  },
  "log": [
    { "step": 1, "type": "set", "key": "message", "value": "hello flowlab", "attempts": 1 },
    { "step": 2, "type": "uppercase", "key": "message", "value": "HELLO FLOWLAB", "attempts": 1 },
    { "step": 3, "type": "set", "key": "count", "value": 2, "attempts": 1 },
    { "step": 4, "type": "add", "key": "count", "value": 5, "attempts": 1 }
  ],
  "failed_step": null,
  "failure_attempts": 0,
  "error": null,
  "duration_ms": 84
}
```

Result dashboard ki execution history mein per-step rows ke roop mein dikhta
hai. API ko seedha dekhne ke liye `/api/health` par `{"status":"ok"}` milega,
`/api/workflows` saved workflows ki JSON list deta hai, aur `/docs` par
interactive API documentation khulti hai. Invalid JSON/steps par browser ya API
error message dikhata hai; failed run HTTP `422` deta hai aur response ke
`X-Execution-ID` header mein us run ka resumable ID deta hai.

## Workflow steps

Steps run in order against one shared data object. They can be created with the
dashboard's visual editor or through the API as a JSON array:

```json
[
  { "type": "set", "key": "message", "value": "hello" },
  { "type": "uppercase", "key": "message" },
  { "type": "set", "key": "count", "value": 2 },
  { "type": "add", "key": "count", "value": 3 }
]
```

Supported operations:

- `set`: assign a JSON value to a key.
- `add`: add a number to a key (defaults to `0`).
- `multiply`: multiply a key's number (defaults to `1`).
- `uppercase`: uppercase a string value.
- `append`: append a string to a value.
- `email`: send a plain-text email using the backend's SMTP configuration.
  The step requires `to`, `subject`, and `body` strings. Use `{{key}}` or a
  nested path such as `{{order_response.body.email}}` in these fields to insert
  workflow data; a missing path fails the step.
- `http`: call an allowlisted public HTTPS API with a JSON request/response.
  `url`, `save_as`, and an optional method (`GET`, `POST`, `PUT`, `PATCH`, or
  `DELETE`) are supported. Add optional string-valued `headers` and a JSON
  `body`; `{{key}}` inserts workflow data and `${ENV:VARIABLE}` reads a backend
  environment variable. Save the parsed response under `save_as` and reference
  response fields in later steps, for example `{{order_response.body.id}}`.
- `file`: read/write/append UTF-8 text files, or check if a file exists. Each
  step needs a relative `path`, an operation, and a `save_as` data key.
  `write`/`append` also need string `content`; templates like `{{key}}` and
  `{{http_result.body.name}}` insert workflow values. Each action is limited to
  1 MB and paths stay within the configured file root.

Example email step:

```json
{
  "type": "email",
  "to": "{{customer_email}}",
  "subject": "Your order {{order_id}}",
  "body": "Hello {{customer_name}}, your order is being processed."
}
```

Configure SMTP in the same terminal before starting the backend. Credentials
are read from the process environment and are never saved in workflows:

```powershell
$env:SMTP_HOST = "smtp.example.com"
$env:SMTP_PORT = "587"
$env:SMTP_USERNAME = "your-account"
$env:SMTP_PASSWORD = "your-provider-app-password"
$env:SMTP_FROM_EMAIL = "workflow@example.com"
$env:SMTP_USE_SSL = "false"
uvicorn backend.main:app --port 8000
```

Port 587 uses STARTTLS; for implicit TLS (commonly port 465), set
`SMTP_PORT` to `465` and `SMTP_USE_SSL` to `true`. `SMTP_USERNAME` and
`SMTP_PASSWORD` must either both be set or both be omitted. Provider-specific
SMTP access must be enabled; for Gmail, use an app password rather than your
normal account password. Never commit real credentials.

Email is sent only when its step runs. The engine may retry a failed email step
up to three times, and resuming a run may send it again if the provider accepted
the message but the app did not persist success before interruption. Review
recipients and use care with workflows that send externally visible messages.

For HTTP actions, configure an exact comma-separated list of trusted public
API hostnames. Requests are HTTPS-only, limited to port 443, do not follow
redirects, reject non-public DNS addresses, and cap request/response bodies at
1 MB. Requests use a 15-second timeout. Credentials belong in environment
variables referenced from header values, not in saved workflow definitions:

```powershell
$env:HTTP_ALLOWED_HOSTS = "api.example.com"
$env:ORDERS_API_TOKEN = "your-provider-token"
uvicorn backend.main:app --port 8000
```

```json
{
  "type": "http",
  "method": "POST",
  "url": "https://api.example.com/v1/orders",
  "headers": {
    "Authorization": "Bearer ${ENV:ORDERS_API_TOKEN}"
  },
  "body": { "order_id": "{{order_id}}" },
  "save_as": "order_response"
}
```

HTTP action retries may repeat a request after a timeout or interrupted run.
Use idempotent methods or provider-supported idempotency keys for operations
that create or modify external data.

Set `WORKFLOW_FILE_ROOT` to an existing absolute folder that the workflow
engine is allowed to access. File paths in steps are relative to that folder;
parent directories are not created automatically. For example:

```powershell
$env:WORKFLOW_FILE_ROOT = "C:\FlowLabFiles"
uvicorn backend.main:app --port 8000
```

```json
[
  { "type": "file", "operation": "read", "path": "customers/input.txt", "save_as": "customer_file" },
  { "type": "file", "operation": "write", "path": "customers/greeting.txt", "content": "Hello {{customer_file.content}}", "save_as": "saved_file" }
]
```

## API

- `GET /api/health` — check API availability.
- `GET /api/workflows` — list saved workflows.
- `POST /api/workflows` — create a workflow with a name and steps.
- `PUT /api/workflows/{id}` — update a workflow.
- `DELETE /api/workflows/{id}` — delete a workflow.
- `POST /api/workflows/{id}/run` — run with optional initial data:
  `{ "data": { "key": "value" } }`.
- `GET /api/executions` — list persisted execution history.
- `POST /api/executions/{id}/resume` — resume a failed run, optionally
  providing corrected data.
- `DELETE /api/executions/{id}` and `DELETE /api/executions` — delete one run
  or clear execution history.
- `GET /api/schedules` — list schedules.
- `POST /api/schedules` — create an interval or daily schedule.
- `PATCH /api/schedules/{id}` — pause or resume a schedule.
- `DELETE /api/schedules/{id}` — delete a schedule.

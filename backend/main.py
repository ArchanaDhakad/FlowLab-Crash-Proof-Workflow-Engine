# UI file aur static assets ka path backend location se resolve hota hai.
import asyncio
import hashlib
import hmac
import logging
import os
import re
import secrets
import threading
import time as monotonic_time
from datetime import time
from pathlib import Path
from typing import Any

# Backend ke apne .env ko load karein, chahe server kisi bhi working directory se start ho.
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(BACKEND_DIR / ".env")

# FastAPI routes HTTP API banate hain; HTTPException client ko meaningful status deta hai.
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
# Pydantic request models incoming JSON ko validate karte hain.
from pydantic import BaseModel, Field, field_validator, model_validator

from .database import (
    claim_due_schedules,
    clear_executions,
    account_exists,
    create_initial_account,
    create_workflow,
    create_execution,
    create_schedule,
    delete_execution,
    delete_workflow,
    delete_schedule,
    get_workflow,
    get_execution,
    get_account_by_email,
    initialize_database,
    list_executions,
    list_schedules,
    list_workflows,
    recover_interrupted_executions,
    resume_execution,
    set_schedule_enabled,
    update_workflow,
)
from .email_service import send_email
from .workflow_engine import execute_persisted_execution, validate_steps


# Project root aur browser ke HTML/CSS/JS files ka folder.
PROJECT_DIR = BACKEND_DIR.parent
FRONTEND_DIR = PROJECT_DIR / "frontend"

# FastAPI application object; uvicorn isi `app` ko serve karta hai.
app = FastAPI(title="FlowLab API", version="1.0.0")
# Browser static files ko /static/... URL se load karta hai.
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
logger = logging.getLogger(__name__)
scheduler_task: asyncio.Task[None] | None = None
SESSION_COOKIE = "flowlab_session"
SESSION_MAX_AGE_SECONDS = 8 * 60 * 60
LOGIN_MAX_FAILURES = 5
LOGIN_LOCKOUT_SECONDS = 15 * 60
PASSWORD_HASH_ITERATIONS = 310_000
_sessions: dict[str, dict[str, Any]] = {}
_login_failures: dict[str, tuple[int, float]] = {}
_auth_lock = threading.Lock()


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=1024)


class SignupRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=1024)

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, password: str) -> str:
        if not re.search(r"[a-z]", password):
            raise ValueError("Add at least one lowercase letter (a-z).")
        if not re.search(r"[A-Z]", password):
            raise ValueError("Add at least one uppercase letter (A-Z).")
        if not re.search(r"\d", password):
            raise ValueError("Add at least one number (0-9).")
        if not re.search(r"[^A-Za-z0-9\s]", password):
            raise ValueError("Add at least one special character, such as !, @, #, or $.")
        return password


def _normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    return normalized


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_HASH_ITERATIONS
    )
    return f"pbkdf2_sha256${PASSWORD_HASH_ITERATIONS}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, digest_text = stored_hash.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        if not 100_000 <= iterations <= 1_000_000:
            return False
        salt = bytes.fromhex(salt_text)
        expected = bytes.fromhex(digest_text)
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations
    )
    return hmac.compare_digest(actual, expected)


_DUMMY_PASSWORD_HASH = _hash_password(secrets.token_urlsafe(32))


def _check_login_limit(client_host: str, now: float) -> None:
    with _auth_lock:
        _, blocked_until = _login_failures.get(client_host, (0, 0.0))
        if now < blocked_until:
            retry_after = max(1, int(blocked_until - now))
            raise HTTPException(
                status_code=429,
                detail=f"Too many sign-in attempts. Try again in {retry_after} seconds.",
                headers={"Retry-After": str(retry_after)},
            )


def _record_login_failure(client_host: str, now: float) -> None:
    with _auth_lock:
        failure_count, _ = _login_failures.get(client_host, (0, 0.0))
        failure_count += 1
        blocked_until = (
            now + LOGIN_LOCKOUT_SECONDS if failure_count >= LOGIN_MAX_FAILURES else 0.0
        )
        _login_failures[client_host] = (failure_count, blocked_until)


def _start_session(email: str, request: Request, response: Response) -> dict[str, str]:
    session_id = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    with _auth_lock:
        _sessions[session_id] = {
            "email": email,
            "csrf_token": csrf_token,
            "expires_at": monotonic_time.monotonic() + SESSION_MAX_AGE_SECONDS,
        }
    response.set_cookie(
        key=SESSION_COOKIE,
        value=session_id,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/",
    )
    return {"email": email, "csrf_token": csrf_token}


def _session_for(request: Request) -> dict[str, Any] | None:
    session_id = request.cookies.get(SESSION_COOKIE)
    if not session_id:
        return None
    with _auth_lock:
        session = _sessions.get(session_id)
        if session is None:
            return None
        if session["expires_at"] <= monotonic_time.monotonic():
            del _sessions[session_id]
            return None
        return session


@app.middleware("http")
async def protect_api(request: Request, call_next: Any) -> Response:
    path = request.url.path
    session = None
    if path.startswith("/api/") and path not in {
        "/api/health",
        "/api/auth/login",
        "/api/auth/signup",
        "/api/auth/session",
    }:
        session = _session_for(request)
        if session is None:
            response = JSONResponse(
                status_code=401,
                content={"detail": "Sign in to access the FlowLab workspace."},
            )
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "same-origin"
            response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
            return response
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            csrf_token = request.headers.get("X-CSRF-Token", "")
            if not hmac.compare_digest(
                csrf_token.encode("utf-8"), session["csrf_token"].encode("utf-8")
            ):
                response = JSONResponse(
                    status_code=403,
                    content={"detail": "This request could not be verified. Refresh and try again."},
                )
                response.headers["Cache-Control"] = "no-store"
                response.headers["X-Content-Type-Options"] = "nosniff"
                response.headers["X-Frame-Options"] = "DENY"
                response.headers["Referrer-Policy"] = "same-origin"
                response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
                return response

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


class WorkflowCreate(BaseModel):
    # Naya workflow: 1-120 character ka naam aur JSON steps ki list.
    name: str = Field(min_length=1, max_length=120)
    steps: list[dict[str, Any]]


class WorkflowRun(BaseModel):
    # Run ke shuru mein dene wala optional data; default khaali object hai.
    data: dict[str, Any] = Field(default_factory=dict)
    max_retries: int = Field(default=3, ge=0, le=3)


class ScheduleCreate(BaseModel):
    workflow_id: int = Field(gt=0)
    schedule_type: str
    interval_minutes: int | None = Field(default=None, ge=1, le=10080)
    run_at: str | None = None

    @model_validator(mode="after")
    def validate_schedule(self) -> "ScheduleCreate":
        if self.schedule_type == "interval":
            if self.interval_minutes is None or self.run_at is not None:
                raise ValueError("Interval schedules need interval_minutes only")
        elif self.schedule_type == "daily":
            if self.run_at is None or self.interval_minutes is not None:
                raise ValueError("Daily schedules need run_at in HH:MM format only")
            try:
                time.fromisoformat(self.run_at)
            except ValueError as error:
                raise ValueError("run_at must use HH:MM 24-hour time") from error
            if len(self.run_at) != 5:
                raise ValueError("run_at must use HH:MM 24-hour time")
        else:
            raise ValueError("schedule_type must be 'interval' or 'daily'")
        return self


class ScheduleUpdate(BaseModel):
    enabled: bool


@app.on_event("startup")
def startup() -> None:
    # Server start hote hi SQLite table ensure karein.
    initialize_database()
    interrupted = recover_interrupted_executions()
    if interrupted:
        logger.warning("Marked %s interrupted workflow runs as resumable.", len(interrupted))
        auto_resume = os.environ.get("AUTO_RESUME_ON_START", "").strip().lower()
        if auto_resume in {"true", "1", "yes"}:
            threading.Thread(
                target=_auto_resume_interrupted_runs,
                args=(interrupted,),
                name="flowlab-auto-resume",
                daemon=True,
            ).start()


@app.on_event("startup")
async def start_scheduler() -> None:
    global scheduler_task
    scheduler_task = asyncio.create_task(_schedule_loop())


@app.on_event("shutdown")
async def stop_scheduler() -> None:
    if scheduler_task is not None:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    # Browser ke root URL par frontend ka main HTML page bhejein.
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    # Simple health-check; server chal raha ho to {"status": "ok"} deta hai.
    return {"status": "ok"}


@app.post("/api/auth/login")
def login(credentials: LoginRequest, request: Request, response: Response) -> dict[str, str]:
    client_host = request.client.host if request.client else "unknown"
    now = monotonic_time.monotonic()
    _check_login_limit(client_host, now)
    email = _normalize_email(credentials.email)
    account = get_account_by_email(email)
    stored_hash = account["password_hash"] if account else _DUMMY_PASSWORD_HASH
    password_matches = _verify_password(credentials.password, stored_hash)
    if account is None or not password_matches:
        _record_login_failure(client_host, now)
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")

    with _auth_lock:
        _login_failures.pop(client_host, None)
    return _start_session(account["email"], request, response)


@app.post("/api/auth/signup")
def signup(
    credentials: SignupRequest, request: Request, response: Response
) -> dict[str, str]:
    client_host = request.client.host if request.client else "unknown"
    if client_host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(
            status_code=403,
            detail="Create the first account from this computer before signing in from another device.",
        )
    email = _normalize_email(credentials.email)
    if account_exists():
        raise HTTPException(
            status_code=409,
            detail="An owner account already exists. Sign in with its email instead.",
        )
    if not create_initial_account(email, _hash_password(credentials.password)):
        raise HTTPException(
            status_code=409,
            detail="An owner account already exists. Sign in with its email instead.",
        )
    with _auth_lock:
        _login_failures.pop(client_host, None)
    return _start_session(email, request, response)


@app.get("/api/auth/session")
def auth_session(request: Request) -> dict[str, Any]:
    session = _session_for(request)
    if session is None:
        return {"authenticated": False, "setup_required": not account_exists()}
    return {
        "authenticated": True,
        "email": session["email"],
        "setup_required": False,
        "csrf_token": session["csrf_token"],
    }


@app.post("/api/auth/logout")
def logout(request: Request, response: Response) -> dict[str, str]:
    session_id = request.cookies.get(SESSION_COOKIE)
    if session_id:
        with _auth_lock:
            _sessions.pop(session_id, None)
    response.delete_cookie(
        key=SESSION_COOKIE,
        path="/",
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
    )
    return {"status": "signed_out"}


@app.get("/api/workflows")
def workflows() -> list[dict[str, Any]]:
    # SQLite mein saved workflows ki list deta hai.
    return list_workflows()


@app.post("/api/workflows", status_code=201)
def save_workflow(workflow: WorkflowCreate) -> dict[str, Any]:
    # Extra spaces hata kar blank naam ko reject karein.
    name = workflow.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Workflow name cannot be blank")

    # Galat step format ko database mein save karne se pehle reject karein.
    try:
        validate_steps(workflow.steps)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    # Save karke naya record response mein wapas dein (HTTP 201).
    return create_workflow(name, workflow.steps)


@app.put("/api/workflows/{workflow_id}")
def edit_workflow(workflow_id: int, workflow: WorkflowCreate) -> dict[str, Any]:
    name = workflow.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Workflow name cannot be blank")
    try:
        validate_steps(workflow.steps)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    updated = update_workflow(workflow_id, name, workflow.steps)
    if updated is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return updated


@app.delete("/api/workflows/{workflow_id}", status_code=204)
def remove_workflow(workflow_id: int) -> None:
    # Workflow delete karein; ID na mile to HTTP 404 response bhejein.
    if not delete_workflow(workflow_id):
        raise HTTPException(status_code=404, detail="Workflow not found")


@app.post("/api/workflows/{workflow_id}/run")
def execute_workflow(workflow_id: int, request: WorkflowRun) -> dict[str, Any]:
    # Pehle saved workflow load karein; missing ID par run nahi ho sakta.
    workflow = get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Steps initial data par chalayein; step error ko HTTP 422 mein badlein.
    execution = create_execution(
        workflow_id, workflow["name"], workflow["steps"], request.data
    )
    result = execute_persisted_execution(execution["id"], request.max_retries)
    if result["status"] == "failed":
        _notify_failure(
            result["execution_id"],
            workflow["name"],
            result["failed_step"],
            result["error"],
        )
        raise HTTPException(
            status_code=422,
            detail=result["error"],
            headers={"X-Execution-ID": str(result["execution_id"])},
        )
    return result


@app.get("/api/executions")
def executions(limit: int = 100) -> list[dict[str, Any]]:
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
    return list_executions(limit)


@app.delete("/api/executions", status_code=204)
def remove_executions() -> None:
    clear_executions()


@app.delete("/api/executions/{execution_id}", status_code=204)
def remove_execution(execution_id: int) -> None:
    if not delete_execution(execution_id):
        raise HTTPException(status_code=404, detail="Execution not found")


@app.post("/api/executions/{execution_id}/resume")
def resume_workflow_execution(
    execution_id: int, request: WorkflowRun
) -> dict[str, Any]:
    execution = get_execution(execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    if execution["status"] != "failed":
        raise HTTPException(status_code=409, detail="Only failed executions can be resumed")
    if not resume_execution(execution_id, request.data):
        raise HTTPException(status_code=409, detail="Execution is no longer resumable")

    result = execute_persisted_execution(execution_id, request.max_retries)
    if result["status"] == "failed":
        _notify_failure(
            result["execution_id"],
            execution["workflow_name"],
            result["failed_step"],
            result["error"],
        )
        raise HTTPException(
            status_code=422,
            detail=result["error"],
            headers={"X-Execution-ID": str(result["execution_id"])},
        )
    return result


def _notify_failure(
    execution_id: int,
    workflow_name: str,
    failed_step: int | None,
    error: str | None,
) -> None:
    recipient = os.environ.get("NOTIFY_EMAIL_ON_FAILURE", "").strip()
    if not recipient:
        return
    subject = f"Workflow failed: {workflow_name}"
    body = (
        f"Workflow: {workflow_name}\n"
        f"Failed step: {failed_step if failed_step is not None else 'unknown'}\n"
        f"Error: {error or 'No error details available'}\n"
        f"Execution ID: {execution_id}\n"
    )
    try:
        send_email(recipient, subject, body)
    except Exception:
        logger.exception(
            "Failure notification for execution %s could not be sent.",
            execution_id,
        )


def _auto_resume_interrupted_runs(execution_ids: list[int]) -> None:
    for execution_id in execution_ids:
        try:
            execution = get_execution(execution_id)
            if execution is None:
                logger.error("Interrupted execution %s no longer exists.", execution_id)
                continue
            if not resume_execution(execution_id):
                logger.warning(
                    "Interrupted execution %s could not be resumed.",
                    execution_id,
                )
                continue

            # A step active at crash time may run again when this execution resumes.
            result = execute_persisted_execution(execution_id)
            if result["status"] == "failed":
                _notify_failure(
                    execution_id,
                    execution["workflow_name"],
                    result["failed_step"],
                    result["error"],
                )
                logger.error(
                    "Auto-resumed execution %s failed at step %s: %s",
                    execution_id,
                    result["failed_step"],
                    result["error"],
                )
            else:
                logger.info("Auto-resumed execution %s completed.", execution_id)
        except Exception:
            logger.exception("Could not auto-resume execution %s.", execution_id)


@app.get("/api/schedules")
def schedules() -> list[dict[str, Any]]:
    return list_schedules()


@app.post("/api/schedules", status_code=201)
def save_schedule(schedule: ScheduleCreate) -> dict[str, Any]:
    workflow = get_workflow(schedule.workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return create_schedule(
        workflow_id=workflow["id"],
        name=workflow["name"],
        schedule_type=schedule.schedule_type,
        interval_minutes=schedule.interval_minutes,
        run_at=schedule.run_at,
    )


@app.patch("/api/schedules/{schedule_id}")
def update_schedule(schedule_id: int, update: ScheduleUpdate) -> dict[str, Any]:
    schedule = set_schedule_enabled(schedule_id, update.enabled)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return schedule


@app.delete("/api/schedules/{schedule_id}", status_code=204)
def remove_schedule(schedule_id: int) -> None:
    if not delete_schedule(schedule_id):
        raise HTTPException(status_code=404, detail="Schedule not found")


async def _schedule_loop() -> None:
    while True:
        for schedule in claim_due_schedules():
            try:
                workflow = get_workflow(schedule["workflow_id"])
                if workflow is None:
                    logger.error(
                        "Schedule %s references missing workflow %s.",
                        schedule["id"],
                        schedule["workflow_id"],
                    )
                    continue
                execution = create_execution(
                    workflow["id"], workflow["name"], workflow["steps"], {}
                )
                result = await asyncio.to_thread(
                    execute_persisted_execution, execution["id"]
                )
                if result["status"] == "failed":
                    await asyncio.to_thread(
                        _notify_failure,
                        result["execution_id"],
                        workflow["name"],
                        result["failed_step"],
                        result["error"],
                    )
                    logger.error(
                        "Scheduled workflow %s failed: %s",
                        workflow["id"],
                        result["error"],
                    )
            except Exception:
                logger.exception("Could not run scheduled job %s.", schedule["id"])
        await asyncio.sleep(5)

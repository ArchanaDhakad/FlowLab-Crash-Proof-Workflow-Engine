# Workflow steps ko SQLite mein JSON text ke roop mein store/read karne ke liye.
import json
import sqlite3
# Context manager connection ko use ke baad hamesha close karta hai.
from contextlib import contextmanager
# Record ka UTC creation time banane ke liye.
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator


# Database file isi backend folder mein banegi, chahe app kahin se bhi start ho.
DATABASE_PATH = Path(__file__).resolve().parent / "flowlab.db"


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    # SQLite rows ko column-name se access karne layak banayein.
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    try:
        # Is block ke successful end par transaction commit hoti hai.
        with connection:
            yield connection
    finally:
        # Error aaye tab bhi connection resource release hona chahiye.
        connection.close()


def initialize_database() -> None:
    # Existing workflows ko alter kiye bina persistent execution/schedule tables add karein.
    with _connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS workflows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                steps TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_id INTEGER,
                workflow_name TEXT NOT NULL,
                steps TEXT NOT NULL,
                status TEXT NOT NULL,
                data TEXT NOT NULL,
                log TEXT NOT NULL,
                current_step INTEGER NOT NULL DEFAULT 1,
                failed_step INTEGER,
                failure_attempts INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                duration_ms INTEGER
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                schedule_type TEXT NOT NULL,
                interval_minutes INTEGER,
                run_at TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                next_run_at TEXT NOT NULL,
                last_run_at TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_executions_started ON executions(started_at DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_schedules_due ON schedules(enabled, next_run_at)"
        )


def account_exists() -> bool:
    with _connect() as connection:
        return connection.execute("SELECT 1 FROM accounts LIMIT 1").fetchone() is not None


def get_account_by_email(email: str) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT email, password_hash FROM accounts WHERE email = ?",
            (email,),
        ).fetchone()
    return dict(row) if row is not None else None


def create_initial_account(email: str, password_hash: str) -> bool:
    with _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute("SELECT 1 FROM accounts LIMIT 1").fetchone() is not None:
            return False
        connection.execute(
            "INSERT INTO accounts (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email, password_hash, datetime.now(timezone.utc).isoformat()),
        )
    return True


def _as_workflow(row: sqlite3.Row) -> dict[str, Any]:
    # Database row ko API/browser ke JSON-friendly Python dictionary mein badlein.
    return {
        "id": row["id"],
        "name": row["name"],
        # Steps database mein JSON text hote hain, response mein list banate hain.
        "steps": json.loads(row["steps"]),
        "created_at": row["created_at"],
    }


def create_workflow(name: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    # UTC timestamp alag time zones ke beech consistent rehta hai.
    created_at = datetime.now(timezone.utc).isoformat()
    with _connect() as connection:
        # '?' placeholders values ko SQL query se safely alag rakhte hain.
        cursor = connection.execute(
            "INSERT INTO workflows (name, steps, created_at) VALUES (?, ?, ?)",
            (name, json.dumps(steps), created_at),
        )
        # Insert hui row ki ID se complete record dobara fetch karenge.
        workflow_id = cursor.lastrowid

    workflow = get_workflow(workflow_id)
    if workflow is None:
        # Save successful dikha kar missing record ko chhupane ke bajay error dein.
        raise RuntimeError("The workflow was saved but could not be loaded")
    return workflow


def update_workflow(
    workflow_id: int, name: str, steps: list[dict[str, Any]]
) -> dict[str, Any] | None:
    with _connect() as connection:
        cursor = connection.execute(
            "UPDATE workflows SET name = ?, steps = ? WHERE id = ?",
            (name, json.dumps(steps), workflow_id),
        )
        if cursor.rowcount == 0:
            return None
        connection.execute(
            "UPDATE schedules SET name = ? WHERE workflow_id = ?",
            (name, workflow_id),
        )
    return get_workflow(workflow_id)


def get_workflow(workflow_id: int) -> dict[str, Any] | None:
    # ID ke hisaab se ek workflow dhoondhein; na mile to None return hota hai.
    with _connect() as connection:
        row = connection.execute(
            "SELECT id, name, steps, created_at FROM workflows WHERE id = ?",
            (workflow_id,),
        ).fetchone()
    return _as_workflow(row) if row is not None else None


def list_workflows() -> list[dict[str, Any]]:
    # Naye workflows pehle dikhte hain; har row ko API response format mein badlein.
    with _connect() as connection:
        rows = connection.execute(
            "SELECT id, name, steps, created_at FROM workflows ORDER BY id DESC"
        ).fetchall()
    return [_as_workflow(row) for row in rows]


def delete_workflow(workflow_id: int) -> bool:
    # Delete hui row ho to True, aur ID na mili ho to False return hota hai.
    with _connect() as connection:
        cursor = connection.execute(
            "DELETE FROM workflows WHERE id = ?", (workflow_id,)
        )
        if cursor.rowcount:
            connection.execute(
                "DELETE FROM schedules WHERE workflow_id = ?", (workflow_id,)
            )
    return cursor.rowcount > 0


def _as_execution(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "workflow_id": row["workflow_id"],
        "workflow_name": row["workflow_name"],
        "steps": json.loads(row["steps"]),
        "status": row["status"],
        "data": json.loads(row["data"]),
        "log": json.loads(row["log"]),
        "current_step": row["current_step"],
        "failed_step": row["failed_step"],
        "failure_attempts": row["failure_attempts"],
        "error": row["error"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "duration_ms": row["duration_ms"],
    }


def create_execution(
    workflow_id: int | None,
    workflow_name: str,
    steps: list[dict[str, Any]],
    initial_data: dict[str, Any],
) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc).isoformat()
    with _connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO executions (
                workflow_id, workflow_name, steps, status, data, log,
                current_step, started_at
            ) VALUES (?, ?, ?, 'running', ?, '[]', 1, ?)
            """,
            (
                workflow_id,
                workflow_name,
                json.dumps(steps),
                json.dumps(initial_data),
                started_at,
            ),
        )
        execution_id = cursor.lastrowid
    execution = get_execution(execution_id)
    if execution is None:
        raise RuntimeError("The execution was created but could not be loaded")
    return execution


def get_execution(execution_id: int) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM executions WHERE id = ?", (execution_id,)
        ).fetchone()
    return _as_execution(row) if row is not None else None


def list_executions(limit: int = 100) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM executions ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_as_execution(row) for row in rows]


def clear_executions() -> None:
    with _connect() as connection:
        connection.execute("DELETE FROM executions")


def save_execution_progress(
    execution_id: int,
    data: dict[str, Any],
    log: list[dict[str, Any]],
    current_step: int,
    status: str,
    *,
    failed_step: int | None = None,
    failure_attempts: int = 0,
    error: str | None = None,
    duration_ms: int | None = None,
) -> None:
    completed_at = (
        datetime.now(timezone.utc).isoformat()
        if status in {"completed", "failed"}
        else None
    )
    with _connect() as connection:
        cursor = connection.execute(
            """
            UPDATE executions
            SET data = ?, log = ?, current_step = ?, status = ?,
                failed_step = ?, failure_attempts = ?, error = ?,
                completed_at = ?, duration_ms = ?
            WHERE id = ?
            """,
            (
                json.dumps(data),
                json.dumps(log),
                current_step,
                status,
                failed_step,
                failure_attempts,
                error,
                completed_at,
                duration_ms,
                execution_id,
            ),
        )
        if cursor.rowcount == 0:
            raise RuntimeError(f"Execution {execution_id} does not exist")


def resume_execution(execution_id: int, data_updates: dict[str, Any] | None = None) -> bool:
    with _connect() as connection:
        row = connection.execute(
            "SELECT log, data FROM executions WHERE id = ? AND status = 'failed'",
            (execution_id,),
        ).fetchone()
        if row is None:
            return False
        log = json.loads(row["log"])
        data = json.loads(row["data"])
        data.update(data_updates or {})
        if log and "error" in log[-1]:
            log.pop()
        cursor = connection.execute(
            """
            UPDATE executions
            SET status = 'running', error = NULL, completed_at = NULL,
                duration_ms = NULL, failure_attempts = 0, log = ?, data = ?
            WHERE id = ? AND status = 'failed'
            """,
            (json.dumps(log), json.dumps(data), execution_id),
        )
    return cursor.rowcount > 0


def delete_execution(execution_id: int) -> bool:
    with _connect() as connection:
        cursor = connection.execute(
            "DELETE FROM executions WHERE id = ?", (execution_id,)
        )
    return cursor.rowcount > 0


def recover_interrupted_executions() -> list[int]:
    """Mark runs interrupted by a server restart as failed and resumable."""
    completed_at = datetime.now(timezone.utc).isoformat()
    with _connect() as connection:
        rows = connection.execute(
            "SELECT id FROM executions WHERE status = 'running'"
        ).fetchall()
        execution_ids = [row["id"] for row in rows]
        if not execution_ids:
            return []
        connection.execute(
            """
            UPDATE executions
            SET status = 'failed', error = 'Interrupted by a server restart; resume this run to continue.',
                failed_step = current_step, completed_at = ?
            WHERE status = 'running'
            """,
            (completed_at,),
        )
    return execution_ids


def _next_schedule_time(
    schedule_type: str,
    interval_minutes: int | None,
    run_at: str | None,
    after: datetime,
) -> datetime:
    local_after = after.astimezone()
    if schedule_type == "interval":
        if interval_minutes is None:
            raise ValueError("An interval schedule needs interval_minutes")
        return (local_after + timedelta(minutes=interval_minutes)).astimezone(timezone.utc)

    if schedule_type == "daily":
        if run_at is None:
            raise ValueError("A daily schedule needs run_at")
        scheduled_time = time.fromisoformat(run_at)
        next_local = datetime.combine(local_after.date(), scheduled_time).replace(
            tzinfo=local_after.tzinfo
        )
        if next_local <= local_after:
            next_local += timedelta(days=1)
        return next_local.astimezone(timezone.utc)

    raise ValueError("schedule_type must be 'interval' or 'daily'")


def _as_schedule(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "workflow_id": row["workflow_id"],
        "name": row["name"],
        "schedule_type": row["schedule_type"],
        "interval_minutes": row["interval_minutes"],
        "run_at": row["run_at"],
        "enabled": bool(row["enabled"]),
        "next_run_at": row["next_run_at"],
        "last_run_at": row["last_run_at"],
        "created_at": row["created_at"],
    }


def create_schedule(
    workflow_id: int,
    name: str,
    schedule_type: str,
    interval_minutes: int | None = None,
    run_at: str | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    next_run_at = _next_schedule_time(
        schedule_type, interval_minutes, run_at, now
    ).isoformat()
    created_at = now.isoformat()
    with _connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO schedules (
                workflow_id, name, schedule_type, interval_minutes,
                run_at, enabled, next_run_at, created_at
            ) VALUES (?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                workflow_id,
                name,
                schedule_type,
                interval_minutes,
                run_at,
                next_run_at,
                created_at,
            ),
        )
        schedule_id = cursor.lastrowid
    schedule = get_schedule(schedule_id)
    if schedule is None:
        raise RuntimeError("The schedule was created but could not be loaded")
    return schedule


def get_schedule(schedule_id: int) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM schedules WHERE id = ?", (schedule_id,)
        ).fetchone()
    return _as_schedule(row) if row is not None else None


def list_schedules() -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM schedules ORDER BY id DESC"
        ).fetchall()
    return [_as_schedule(row) for row in rows]


def set_schedule_enabled(schedule_id: int, enabled: bool) -> dict[str, Any] | None:
    now = datetime.now(timezone.utc)
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM schedules WHERE id = ?", (schedule_id,)
        ).fetchone()
        if row is None:
            return None
        values = _as_schedule(row)
        next_run_at = row["next_run_at"]
        if enabled and not values["enabled"]:
            next_run_at = _next_schedule_time(
                values["schedule_type"],
                values["interval_minutes"],
                values["run_at"],
                now,
            ).isoformat()
        connection.execute(
            "UPDATE schedules SET enabled = ?, next_run_at = ? WHERE id = ?",
            (int(enabled), next_run_at, schedule_id),
        )
    return get_schedule(schedule_id)


def delete_schedule(schedule_id: int) -> bool:
    with _connect() as connection:
        cursor = connection.execute(
            "DELETE FROM schedules WHERE id = ?", (schedule_id,)
        )
    return cursor.rowcount > 0


def claim_due_schedules() -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    now_text = now.isoformat()
    due: list[dict[str, Any]] = []
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT * FROM schedules
            WHERE enabled = 1 AND next_run_at <= ?
            ORDER BY next_run_at
            """,
            (now_text,),
        ).fetchall()
        for row in rows:
            next_run_at = _next_schedule_time(
                row["schedule_type"],
                row["interval_minutes"],
                row["run_at"],
                now,
            ).isoformat()
            cursor = connection.execute(
                """
                UPDATE schedules
                SET next_run_at = ?, last_run_at = ?
                WHERE id = ? AND enabled = 1 AND next_run_at = ?
                """,
                (next_run_at, now_text, row["id"], row["next_run_at"]),
            )
            if cursor.rowcount:
                due.append(_as_schedule(row))
    return due


def delete_schedules_for_workflow(workflow_id: int) -> None:
    with _connect() as connection:
        connection.execute(
            "DELETE FROM schedules WHERE workflow_id = ?", (workflow_id,)
        )

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


DATABASE_PATH = Path(__file__).resolve().parent / "flowlab.db"


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database() -> None:
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


def _as_workflow(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "steps": json.loads(row["steps"]),
        "created_at": row["created_at"],
    }


def create_workflow(name: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    created_at = datetime.now(timezone.utc).isoformat()
    with _connect() as connection:
        cursor = connection.execute(
            "INSERT INTO workflows (name, steps, created_at) VALUES (?, ?, ?)",
            (name, json.dumps(steps), created_at),
        )
        workflow_id = cursor.lastrowid

    workflow = get_workflow(workflow_id)
    if workflow is None:
        raise RuntimeError("The workflow was saved but could not be loaded")
    return workflow


def get_workflow(workflow_id: int) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT id, name, steps, created_at FROM workflows WHERE id = ?",
            (workflow_id,),
        ).fetchone()
    return _as_workflow(row) if row is not None else None


def list_workflows() -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT id, name, steps, created_at FROM workflows ORDER BY id DESC"
        ).fetchall()
    return [_as_workflow(row) for row in rows]


def delete_workflow(workflow_id: int) -> bool:
    with _connect() as connection:
        cursor = connection.execute("DELETE FROM workflows WHERE id = ?", (workflow_id,))
    return cursor.rowcount > 0

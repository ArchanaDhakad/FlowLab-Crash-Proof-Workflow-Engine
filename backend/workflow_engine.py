# Caller ke input data ko mutate kiye bina uski copy par workflow chalane ke liye.
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import os
import re
import time
from typing import Any
from urllib.parse import urlsplit

from .database import get_execution, save_execution_progress
from .email_service import send_email
from .file_service import execute_file_step
from .http_service import send_http_request

# Engine ke built-in data operations aur external-service/file actions.
SUPPORTED_STEP_TYPES = {
    "set", "add", "multiply", "uppercase", "append", "email", "http", "file"
}
TEMPLATE_PATTERN = re.compile(
    r"\{\{\s*([A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*)*)\s*\}\}"
)


def validate_steps(steps: list[dict[str, Any]]) -> None:
    # Empty workflow ka koi kaam nahi, isliye use reject karein.
    if not steps:
        raise ValueError("A workflow must contain at least one step")

    # Har step ko uski 1-based position ke saath validate karein.
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            raise ValueError(f"Step {index} must be a JSON object")

        # Type supported hona chahiye.
        step_type = step.get("type")
        if not isinstance(step_type, str) or step_type not in SUPPORTED_STEP_TYPES:
            supported = ", ".join(sorted(SUPPORTED_STEP_TYPES))
            raise ValueError(
                f"Step {index} has an unsupported type. Choose from: {supported}"
            )

        if step_type == "email":
            for field in ("to", "subject", "body"):
                value = step.get(field)
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(
                        f"Step {index} email must include a non-empty string '{field}'"
                    )
        elif step_type == "http":
            url = step.get("url")
            if not isinstance(url, str) or not url.strip():
                raise ValueError(f"Step {index} HTTP action must include a non-empty 'url'")
            try:
                parsed_url = urlsplit(url)
                has_valid_https_url = (
                    parsed_url.scheme.lower() == "https"
                    and bool(parsed_url.hostname)
                    and parsed_url.username is None
                    and parsed_url.password is None
                    and not parsed_url.fragment
                    and parsed_url.port in (None, 443)
                )
            except ValueError:
                has_valid_https_url = False
            if not has_valid_https_url:
                raise ValueError(
                    f"Step {index} HTTP action requires an HTTPS URL on port 443 without credentials or a fragment"
                )
            method = step.get("method", "GET")
            if not isinstance(method, str) or method.upper() not in {
                "GET", "POST", "PUT", "PATCH", "DELETE"
            }:
                raise ValueError(
                    f"Step {index} HTTP method must be GET, POST, PUT, PATCH, or DELETE"
                )
            save_as = step.get("save_as")
            if not isinstance(save_as, str) or not save_as.strip():
                raise ValueError(f"Step {index} HTTP action must include a non-empty 'save_as'")
            headers = step.get("headers", {})
            if not isinstance(headers, dict) or len(headers) > 50:
                raise ValueError(f"Step {index} HTTP headers must be an object with at most 50 entries")
            if any(
                not isinstance(name, str) or not isinstance(value, str)
                for name, value in headers.items()
            ):
                raise ValueError(f"Step {index} HTTP header names and values must be strings")
        elif step_type == "file":
            operation = step.get("operation")
            if operation not in {"read", "write", "append", "exists"}:
                raise ValueError(
                    f"Step {index} file operation must be read, write, append, or exists"
                )
            path = step.get("path")
            if not isinstance(path, str) or not path.strip():
                raise ValueError(f"Step {index} file action must include a non-empty 'path'")
            save_as = step.get("save_as")
            if not isinstance(save_as, str) or not save_as.strip():
                raise ValueError(f"Step {index} file action must include a non-empty 'save_as'")
            if operation in {"write", "append"} and not isinstance(step.get("content"), str):
                raise ValueError(
                    f"Step {index} file {operation} action must include string 'content'"
                )
        # Data operations work on a named value; email steps use to/subject/body.
        elif step_type not in {"email", "http", "file"} and (
            not isinstance(step.get("key"), str) or not step["key"].strip()
        ):
            raise ValueError(f"Step {index} must include a non-empty string 'key'")

        # Add/multiply sirf numbers par kaam karte hain; bool ko number na maanein.
        if step_type in {"add", "multiply"}:
            value = step.get("value")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"Step {index} must have a numeric 'value'")

        # Append mein jodi jaane wali value text honi zaroori hai.
        if step_type == "append" and not isinstance(step.get("value"), str):
            raise ValueError(f"Step {index} must have a string 'value'")


def run_workflow(
    steps: list[dict[str, Any]], initial_data: dict[str, Any] | None = None
) -> dict[str, Any]:
    # Run ke waqt bhi validate karein, taaki stored ya direct input dono safe hon.
    validate_steps(steps)
    # Workflow caller ke data ki copy par chalta hai aur har step ka result log karta hai.
    context = deepcopy(initial_data or {})
    log: list[dict[str, Any]] = []

    # Steps sequentially ek hi shared data object ko update karte hain.
    for index, step in enumerate(steps, start=1):
        step_type = step["type"]
        key = step.get("key", "")
        value = _apply_step(context, step, index)
        # Har step ke baad key ki current value log mein store hoti hai.
        log.append(
            {
                "step": index,
                "type": step_type,
                "key": key,
                "value": value,
            }
        )

    # API/browser ko final data aur step-by-step execution log dono milte hain.
    return {"data": context, "log": log}


def _apply_step(context: dict[str, Any], step: dict[str, Any], index: int) -> Any:
    step_type = step["type"]
    key = step.get("key", "")

    try:
        if step_type == "email":
            send_email(
                _render_email_template(step["to"], context),
                _render_email_template(step["subject"], context),
                _render_email_template(step["body"], context),
            )
            return "Email sent"
        if step_type == "http":
            result = send_http_request(step, context)
            context[step["save_as"]] = result
            return {
                "status_code": result["status_code"],
                "saved_as": step["save_as"],
            }
        if step_type == "file":
            result = execute_file_step(step, context)
            context[step["save_as"]] = result
            return {
                "operation": result["operation"],
                "path": result["path"],
                "saved_as": step["save_as"],
            }
        if step_type == "set":
            context[key] = step.get("value")
        elif step_type == "add":
            current = context.get(key, 0)
            if isinstance(current, bool) or not isinstance(current, (int, float)):
                raise ValueError(f"'{key}' must contain a number before adding")
            context[key] = current + step["value"]
        elif step_type == "multiply":
            current = context.get(key, 1)
            if isinstance(current, bool) or not isinstance(current, (int, float)):
                raise ValueError(f"'{key}' must contain a number before multiplying")
            context[key] = current * step["value"]
        elif step_type == "uppercase":
            current = context.get(key, "")
            if not isinstance(current, str):
                raise ValueError(f"'{key}' must contain text before uppercasing")
            context[key] = current.upper()
        elif step_type == "append":
            current = context.get(key, "")
            if not isinstance(current, str):
                raise ValueError(f"'{key}' must contain text before appending")
            context[key] = current + step["value"]
    except ValueError as error:
        raise ValueError(f"Step {index}: {error}") from error

    return context[key]


def _render_email_template(template: str, context: dict[str, Any]) -> str:
    """Replace {{key.path}} tokens with workflow data and reject missing values."""
    def replace(match: re.Match[str]) -> str:
        path = match.group(1)
        value: Any = context
        for key in path.split("."):
            if not isinstance(value, dict) or key not in value:
                raise ValueError(f"Email template references missing data path '{path}'")
            value = value[key]
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    return TEMPLATE_PATTERN.sub(replace, template)


def execute_persisted_execution(
    execution_id: int, max_retries: int = 3
) -> dict[str, Any]:
    execution = get_execution(execution_id)
    if execution is None:
        raise ValueError(f"Execution {execution_id} was not found")
    if execution["status"] != "running":
        raise ValueError("Only a running execution can be continued")

    steps = execution["steps"]
    validate_steps(steps)
    context = deepcopy(execution["data"])
    log = list(execution["log"])
    # A previous failure row describes the failed attempt, not a workflow step to keep.
    if log and "error" in log[-1] and log[-1]["step"] == execution["current_step"]:
        log.pop()

    started_at = datetime.fromisoformat(execution["started_at"])
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)

    try:
        retry_delay = float(os.environ.get("RETRY_DELAY_SECONDS", "1"))
        if not math.isfinite(retry_delay):
            raise ValueError("Retry delay must be finite")
        retry_delay = min(10.0, max(0.0, retry_delay))
    except (TypeError, ValueError):
        retry_delay = 1.0

    for index in range(execution["current_step"], len(steps) + 1):
        step = steps[index - 1]
        for attempt in range(1, max_retries + 2):
            try:
                value = _apply_step(context, step, index)
                log.append(
                    {
                        "step": index,
                        "type": step["type"],
                        "key": step.get("key", ""),
                        "value": value,
                        "attempts": attempt,
                    }
                )
                completed = index == len(steps)
                duration_ms = round(
                    (datetime.now(timezone.utc) - started_at).total_seconds() * 1000
                )
                save_execution_progress(
                    execution_id,
                    context,
                    log,
                    index + 1,
                    "completed" if completed else "running",
                    duration_ms=duration_ms if completed else None,
                )
                break
            except ValueError as error:
                if attempt <= max_retries:
                    if retry_delay > 0:
                        time.sleep(retry_delay)
                    continue
                log.append(
                    {
                        "step": index,
                        "type": step["type"],
                        "key": step.get("key", ""),
                        "error": str(error),
                        "attempts": attempt,
                    }
                )
                duration_ms = round(
                    (datetime.now(timezone.utc) - started_at).total_seconds() * 1000
                )
                save_execution_progress(
                    execution_id,
                    context,
                    log,
                    index,
                    "failed",
                    failed_step=index,
                    failure_attempts=attempt,
                    error=str(error),
                    duration_ms=duration_ms,
                )
                failed = get_execution(execution_id)
                if failed is None:
                    raise RuntimeError("The failed execution could not be loaded")
                return {
                    "execution_id": execution_id,
                    "status": failed["status"],
                    "data": failed["data"],
                    "log": failed["log"],
                    "failed_step": failed["failed_step"],
                    "failure_attempts": failed["failure_attempts"],
                    "error": failed["error"],
                    "duration_ms": failed["duration_ms"],
                }

    completed = get_execution(execution_id)
    if completed is None:
        raise RuntimeError("The completed execution could not be loaded")
    return {
        "execution_id": execution_id,
        "status": completed["status"],
        "data": completed["data"],
        "log": completed["log"],
        "failed_step": completed["failed_step"],
        "failure_attempts": completed["failure_attempts"],
        "error": completed["error"],
        "duration_ms": completed["duration_ms"],
    }

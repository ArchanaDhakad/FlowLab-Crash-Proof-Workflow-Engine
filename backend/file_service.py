"""Read and update files only inside an explicitly configured workflow folder."""

import json
import os
import re
import tempfile
from pathlib import Path, PureWindowsPath
from typing import Any


MAX_FILE_BYTES = 1_000_000
TEMPLATE_PATTERN = re.compile(
    r"\{\{\s*([A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*)*)\s*\}\}"
)


def _render_template(template: str, context: dict[str, Any]) -> str:
    
    def replace(match: re.Match[str]) -> str:
        path = match.group(1)
        value: Any = context
        for key in path.split("."):
            if not isinstance(value, dict) or key not in value:
                raise ValueError(f"File template references missing data path '{path}'.")
            value = value[key]
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    return TEMPLATE_PATTERN.sub(replace, template)


def _resolve_file_path(relative_path: str) -> tuple[Path, str]:
    root_value = os.environ.get("WORKFLOW_FILE_ROOT", "").strip()
    if not root_value:
        raise ValueError("File step requires the WORKFLOW_FILE_ROOT environment variable.")

    root_path = Path(root_value).expanduser()
    if not root_path.is_absolute():
        raise ValueError("WORKFLOW_FILE_ROOT must be an absolute path.")
    try:
        root = root_path.resolve(strict=True)
    except OSError as error:
        raise ValueError("WORKFLOW_FILE_ROOT must point to an existing accessible folder.") from error
    if not root.is_dir():
        raise ValueError("WORKFLOW_FILE_ROOT must point to an existing folder.")

    normalized = relative_path.replace("\\", "/")
    candidate_path = Path(relative_path)
    windows_path = PureWindowsPath(relative_path)
    if (
        not relative_path.strip()
        or "\x00" in relative_path
        or len(relative_path) > 1024
        or candidate_path.is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or ":" in relative_path
        or ".." in normalized.split("/")
    ):
        raise ValueError("File paths must be relative to WORKFLOW_FILE_ROOT without '..'.")

    try:
        target = (root / candidate_path).resolve(strict=False)
    except OSError as error:
        raise ValueError("File path could not be resolved safely.") from error
    try:
        target.relative_to(root)
    except ValueError as error:
        raise ValueError("File path must stay inside WORKFLOW_FILE_ROOT.") from error
    if target == root:
        raise ValueError("File steps require a file path inside WORKFLOW_FILE_ROOT.")

    return target, Path(normalized).as_posix()


def execute_file_step(step: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Run a bounded read, write, append, or exists check under the configured root."""
    relative_path = _render_template(step["path"], context)
    target, display_path = _resolve_file_path(relative_path)
    operation = step["operation"]

    try:
        if operation == "exists":
            result: dict[str, Any] = {
                "operation": operation,
                "path": display_path,
                "exists": target.is_file(),
            }
        elif operation == "read":
            if not target.is_file():
                raise ValueError(f"File '{display_path}' does not exist.")
            with target.open("rb") as file:
                content = file.read(MAX_FILE_BYTES + 1)
            if len(content) > MAX_FILE_BYTES:
                raise ValueError("File reads are limited to 1 MB.")
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError as error:
                raise ValueError(f"File '{display_path}' is not valid UTF-8 text.") from error
            result = {"operation": operation, "path": display_path, "content": text}
        else:
            content = _render_template(step["content"], context)
            encoded = content.encode("utf-8")
            if len(encoded) > MAX_FILE_BYTES:
                raise ValueError("File writes are limited to 1 MB per step.")
            if not target.parent.is_dir():
                raise ValueError("The parent folder for a file step must already exist.")
            if target.exists() and not target.is_file():
                raise ValueError(f"File path '{display_path}' is not a regular file.")

            if operation == "append":
                existing_size = target.stat().st_size if target.exists() else 0
                if existing_size + len(encoded) > MAX_FILE_BYTES:
                    raise ValueError("File writes are limited to 1 MB per file.")
                with target.open("ab") as file:
                    file.write(encoded)
                    file.flush()
                bytes_written = len(encoded)
            else:
                temporary_path: Path | None = None
                try:
                    with tempfile.NamedTemporaryFile(
                        mode="wb", dir=target.parent, delete=False
                    ) as temporary_file:
                        temporary_path = Path(temporary_file.name)
                        temporary_file.write(encoded)
                        temporary_file.flush()
                        os.fsync(temporary_file.fileno())
                    temporary_path.replace(target)
                finally:
                    if temporary_path is not None and temporary_path.exists():
                        temporary_path.unlink()
                bytes_written = len(encoded)

            result = {
                "operation": operation,
                "path": display_path,
                "bytes_written": bytes_written,
            }
    except OSError as error:
        raise ValueError(
            f"File {operation} failed ({type(error).__name__}) for '{display_path}'."
        ) from error

    return result

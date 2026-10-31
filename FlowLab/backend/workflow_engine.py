from copy import deepcopy
from typing import Any


SUPPORTED_STEP_TYPES = {"set", "add", "multiply", "uppercase", "append"}


def validate_steps(steps: list[dict[str, Any]]) -> None:
    if not steps:
        raise ValueError("A workflow must contain at least one step")

    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            raise ValueError(f"Step {index} must be a JSON object")

        step_type = step.get("type")
        if not isinstance(step_type, str) or step_type not in SUPPORTED_STEP_TYPES:
            supported = ", ".join(sorted(SUPPORTED_STEP_TYPES))
            raise ValueError(
                f"Step {index} has an unsupported type. Choose from: {supported}"
            )

        if not isinstance(step.get("key"), str) or not step["key"].strip():
            raise ValueError(f"Step {index} must include a non-empty string 'key'")

        if step_type in {"add", "multiply"}:
            value = step.get("value")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"Step {index} must have a numeric 'value'")

        if step_type == "append" and not isinstance(step.get("value"), str):
            raise ValueError(f"Step {index} must have a string 'value'")


def run_workflow(
    steps: list[dict[str, Any]], initial_data: dict[str, Any] | None = None
) -> dict[str, Any]:
    validate_steps(steps)
    context = deepcopy(initial_data or {})
    log: list[dict[str, Any]] = []

    for index, step in enumerate(steps, start=1):
        step_type = step["type"]
        key = step["key"]

        try:
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

        log.append(
            {
                "step": index,
                "type": step_type,
                "key": key,
                "value": context[key],
            }
        )

    return {"data": context, "log": log}

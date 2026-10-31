from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .database import (
    create_workflow,
    delete_workflow,
    get_workflow,
    initialize_database,
    list_workflows,
)
from .workflow_engine import run_workflow, validate_steps


BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI(title="FlowLab API", version="1.0.0")
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    steps: list[dict[str, Any]]


class WorkflowRun(BaseModel):
    data: dict[str, Any] = Field(default_factory=dict)


@app.on_event("startup")
def startup() -> None:
    initialize_database()


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/workflows")
def workflows() -> list[dict[str, Any]]:
    return list_workflows()


@app.post("/api/workflows", status_code=201)
def save_workflow(workflow: WorkflowCreate) -> dict[str, Any]:
    name = workflow.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Workflow name cannot be blank")

    try:
        validate_steps(workflow.steps)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    return create_workflow(name, workflow.steps)


@app.delete("/api/workflows/{workflow_id}", status_code=204)
def remove_workflow(workflow_id: int) -> None:
    if not delete_workflow(workflow_id):
        raise HTTPException(status_code=404, detail="Workflow not found")


@app.post("/api/workflows/{workflow_id}/run")
def execute_workflow(workflow_id: int, request: WorkflowRun) -> dict[str, Any]:
    workflow = get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    try:
        result = run_workflow(workflow["steps"], request.data)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    return result

// Default workflow example shown in the editor and restored by "Load example".
const exampleSteps = [
  { type: "set", key: "message", value: "hello flowlab" },
  { type: "uppercase", key: "message" },
  { type: "set", key: "count", value: 2 },
  { type: "add", key: "count", value: 3 },
];

// Cache the page elements so event handlers can read/update them.
const form = document.querySelector("#workflow-form");
const nameInput = document.querySelector("#workflow-name");
const stepsInput = document.querySelector("#workflow-steps");
const formMessage = document.querySelector("#form-message");
const workflowList = document.querySelector("#workflow-list");
const runOutput = document.querySelector("#run-output");
const outputContent = document.querySelector("#output-content");
const saveButton = form.querySelector('button[type="submit"]');

// Pre-fill the editor with readable JSON when the page first loads.
stepsInput.value = JSON.stringify(exampleSteps, null, 2);

// Show save/delete feedback with optional success/error styling.
function showMessage(message, type = "") {
  formMessage.textContent = message;
  formMessage.className = `form-message ${type}`.trim();
}

// Send an HTTP request to the backend and turn unsuccessful responses into errors.
async function request(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
  });

  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch {
      // Keep the HTTP status message when the server response is not JSON.
    }
    throw new Error(message);
  }

  return response.status === 204 ? null : response.json();
}

// Build one saved-workflow card and attach its Run and Delete button handlers.
function makeWorkflowCard(workflow) {
  const card = document.createElement("article");
  card.className = "workflow-card";

  const top = document.createElement("div");
  top.className = "workflow-card-top";
  const details = document.createElement("div");
  const title = document.createElement("h3");
  title.textContent = workflow.name;
  const meta = document.createElement("p");
  meta.className = "workflow-meta";
  meta.textContent = `${workflow.steps.length} step${workflow.steps.length === 1 ? "" : "s"} · ${new Date(workflow.created_at).toLocaleString()}`;
  details.append(title, meta);
  top.append(details);

  const actions = document.createElement("div");
  actions.className = "workflow-actions";
  const runButton = document.createElement("button");
  runButton.className = "run-button";
  runButton.type = "button";
  runButton.textContent = "▶ Run";
  runButton.addEventListener("click", () => runWorkflow(workflow.id, runButton));

  const deleteButton = document.createElement("button");
  deleteButton.className = "delete-button";
  deleteButton.type = "button";
  deleteButton.textContent = "Delete";
  deleteButton.addEventListener("click", () => removeWorkflow(workflow.id, deleteButton));
  actions.append(runButton, deleteButton);

  card.append(top, actions);
  return card;
}

// Fetch all saved workflows and render loading, empty, success, or error state.
async function loadWorkflows() {
  workflowList.replaceChildren();
  const loading = document.createElement("div");
  loading.className = "empty-state";
  loading.textContent = "Loading workflows…";
  workflowList.append(loading);

  try {
    const workflows = await request("/api/workflows");
    workflowList.replaceChildren();
    if (workflows.length === 0) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = "No workflows yet. Create one to get started.";
      workflowList.append(empty);
      return;
    }
    workflows.forEach((workflow) => workflowList.append(makeWorkflowCard(workflow)));
  } catch (error) {
    const failed = document.createElement("div");
    failed.className = "empty-state";
    failed.textContent = `Could not load workflows: ${error.message}`;
    workflowList.replaceChildren(failed);
  }
}

// Run a saved workflow without extra starting data and display its JSON result/error.
async function runWorkflow(workflowId, button) {
  button.disabled = true;
  button.textContent = "Running…";
  try {
    const result = await request(`/api/workflows/${workflowId}/run`, {
      method: "POST",
      body: JSON.stringify({ data: {} }),
    });
    outputContent.textContent = JSON.stringify(result, null, 2);
    runOutput.hidden = false;
  } catch (error) {
    outputContent.textContent = error.message;
    runOutput.hidden = false;
  } finally {
    button.disabled = false;
    button.textContent = "▶ Run";
  }
}

// Delete a saved workflow, refresh the list, and show success/error feedback.
async function removeWorkflow(workflowId, button) {
  button.disabled = true;
  try {
    await request(`/api/workflows/${workflowId}`, { method: "DELETE" });
    await loadWorkflows();
    showMessage("Workflow deleted.", "success");
  } catch (error) {
    button.disabled = false;
    showMessage(error.message, "error");
  }
}

// Validate the editor JSON in the browser, then ask the backend to save the workflow.
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  showMessage("");
  saveButton.disabled = true;

  let steps;
  try {
    steps = JSON.parse(stepsInput.value);
    if (!Array.isArray(steps)) {
      throw new Error("Steps must be a JSON array.");
    }
  } catch (error) {
    showMessage(`Invalid steps JSON: ${error.message}`, "error");
    saveButton.disabled = false;
    return;
  }

  try {
    await request("/api/workflows", {
      method: "POST",
      body: JSON.stringify({ name: nameInput.value.trim(), steps }),
    });
    nameInput.value = "";
    showMessage("Workflow saved.", "success");
    await loadWorkflows();
  } catch (error) {
    showMessage(error.message, "error");
  } finally {
    saveButton.disabled = false;
  }
});

// UI controls: restore example, reload saved workflows, or hide the current run result.
document.querySelector("#load-example").addEventListener("click", () => {
  stepsInput.value = JSON.stringify(exampleSteps, null, 2);
});
document.querySelector("#refresh-workflows").addEventListener("click", loadWorkflows);
document.querySelector("#clear-output").addEventListener("click", () => {
  runOutput.hidden = true;
  outputContent.textContent = "";
});

loadWorkflows();

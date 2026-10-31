// Starter JSON shown in the workflow editor when a user requests an example.
const exampleSteps = [
  { type: "set", key: "message", value: "hello flowlab" },
  { type: "uppercase", key: "message" },
  { type: "set", key: "count", value: 2 },
  { type: "add", key: "count", value: 3 },
];

const stepIcons = {
  set: "◇",
  add: "+",
  multiply: "×",
  uppercase: "Aa",
  append: "↗",
  email: "✉",
  http: "↗",
  file: "▤",
};

const workflowSelect = document.querySelector("#workflow-select");
const workflowList = document.querySelector("#workflow-list");
const workflowTitle = document.querySelector("#workflow-title");
const workflowDescription = document.querySelector("#workflow-description");
const workflowStatus = document.querySelector("#workflow-status");
const stepFlow = document.querySelector("#step-flow");
const historyBody = document.querySelector("#history-body");
const workflowDialog = document.querySelector("#workflow-dialog");
const workflowForm = document.querySelector("#workflow-form");
const stepDraftList = document.querySelector("#step-draft-list");
const stepTypeSelect = document.querySelector("#step-type");
const stepFields = document.querySelector("#step-fields");
const stepHint = document.querySelector("#step-hint");
const stepError = document.querySelector("#step-error");
const addStepButton = document.querySelector("#add-step");
const loginScreen = document.querySelector("#login-screen");
const loginForm = document.querySelector("#login-form");
const loginError = document.querySelector("#login-error");
const loginCopy = document.querySelector("#login-copy");
const authToggle = document.querySelector("#auth-toggle");
const authToggleCopy = document.querySelector("#auth-toggle-copy");
const confirmPasswordField = document.querySelector("#confirm-password-field");
const scheduleForm = document.querySelector("#schedule-form");
const scheduleList = document.querySelector("#schedule-list");
const apiStatus = document.querySelector("#api-status");
const apiStatusText = document.querySelector("#api-status-text");

let workflows = [];
let executions = [];
let schedules = [];
let selectedWorkflowId = "";
let draftSteps = [];
let editingStepIndex = -1;
let csrfToken = "";
let isAuthenticated = false;
let registrationOpen = false;
let authMode = "signup";

function setApiStatus(connected) {
  apiStatus.classList.toggle("connected", connected);
  apiStatus.classList.toggle("disconnected", !connected);
  apiStatusText.textContent = connected ? "API connected" : "API disconnected";
}

function showLogin(message = "") {
  isAuthenticated = false;
  csrfToken = "";
  loginError.textContent = message;
  loginError.hidden = !message;
  loginScreen.hidden = false;
  document.body.classList.add("login-required");
  document.querySelector("#login-password").value = "";
  document.querySelector("#confirm-password").value = "";
  document.querySelector("#login-email").focus();
}

function setAuthMode(mode) {
  authMode = mode;
  const isSignup = mode === "signup";
  loginCopy.textContent = isSignup
    ? "Create the owner account for this FlowLab workspace."
    : "Sign in with the email and password you registered.";
  document.querySelector("#login-title").textContent = isSignup
    ? "Create your account"
    : "Welcome back";
  document.querySelector("#login-submit").textContent = isSignup ? "Create account" : "Sign in";
  document.querySelector("#login-password").autocomplete = isSignup ? "new-password" : "current-password";
  confirmPasswordField.hidden = !isSignup;
  document.querySelector("#password-requirements").hidden = !isSignup;
  document.querySelector("#confirm-password").required = isSignup;
  document.querySelector("#login-password").minLength = isSignup ? 12 : 1;
  authToggle.hidden = !registrationOpen;
  authToggleCopy.hidden = !registrationOpen;
  authToggleCopy.textContent = isSignup
    ? "Already created your account?"
    : "First time using this FlowLab?";
  authToggle.textContent = isSignup ? "Sign in instead" : "Create the owner account";
}

function hideLogin() {
  isAuthenticated = true;
  loginScreen.hidden = true;
  document.body.classList.remove("login-required");
  loginError.hidden = true;
}

// Keep requests on the FastAPI origin; include saved run IDs on execution errors.
async function request(url, options = {}) {
  let response;
  try {
    response = await fetch(url, {
      ...options,
      headers: {
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(csrfToken && !["GET", "HEAD", "OPTIONS"].includes((options.method || "GET").toUpperCase())
          && url !== "/api/auth/login" ? { "X-CSRF-Token": csrfToken } : {}),
        ...options.headers,
      },
    });
  } catch (error) {
    setApiStatus(false);
    throw new Error("Cannot reach the FlowLab API. Start the backend and open http://127.0.0.1:8000.");
  }

  if (!response.ok) {
    if (response.status === 401 && url !== "/api/auth/login") {
      showLogin("Your sign-in expired. Please sign in again.");
    }
    const outdatedAuthEndpoint = response.status === 404
      && ["/api/auth/login", "/api/auth/signup"].includes(url);
    let message = outdatedAuthEndpoint
      ? "The running server does not have the updated sign-in feature. Stop it with Ctrl+C, restart FlowLab, then refresh this page."
      : `Request failed (${response.status})`;
    if (!outdatedAuthEndpoint) {
      try {
        const body = await response.json();
        if (typeof body.detail === "string") {
          message = body.detail;
        } else if (Array.isArray(body.detail)) {
          message = body.detail
            .map((item) => item.msg)
            .filter((item) => typeof item === "string")
            .join("; ") || message;
        }
      } catch {
        // Keep the HTTP status when the server response is not JSON.
      }
    }
    const error = new Error(message);
    error.executionId = response.headers.get("X-Execution-ID");
    error.status = response.status;
    throw error;
  }

  setApiStatus(true);
  return response.status === 204 ? null : response.json();
}

async function loadAuthenticatedDashboard() {
  await Promise.all([loadWorkflows(), loadExecutions(), loadSchedules()]);
}

async function initializeAuthentication() {
  try {
    const session = await request("/api/auth/session");
    if (!session.authenticated) {
      registrationOpen = session.setup_required;
      setAuthMode(registrationOpen ? "signup" : "login");
      showLogin();
      return;
    }
    csrfToken = session.csrf_token;
    hideLogin();
    await loadAuthenticatedDashboard();
  } catch (error) {
    if (error.status === 401) {
      showLogin();
      return;
    }
    setApiStatus(false);
    showLogin(`Cannot connect to FlowLab. Start the server and try again. ${error.message}`);
  }
}

function selectedWorkflow() {
  return workflows.find((workflow) => String(workflow.id) === selectedWorkflowId) || null;
}

function formatTime(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}

function formatValue(value) {
  if (value === undefined) return "No output";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

function stepTitle(step) {
  return {
    set: "Set value",
    add: "Add number",
    multiply: "Multiply number",
    uppercase: "Uppercase text",
    append: "Append text",
    email: "Send email",
    http: "HTTP request",
    file: "File action",
  }[step.type] || step.type;
}

function stepIcon(step) {
  return stepIcons[step.type] || "◇";
}

function stepSubtitle(step) {
  if (step.type === "email") return `To ${step.to}`;
  if (step.type === "http") {
    try {
      return `${step.method || "GET"} · ${new URL(step.url).host}`;
    } catch {
      return `${step.method || "GET"} · ${step.url}`;
    }
  }
  if (step.type === "file") return `${step.operation} · ${step.path}`;
  return step.key;
}

function historyResult(entry) {
  if (entry.type === "email") return "Email sent";
  if (entry.type === "http") {
    const status = entry.value?.status_code;
    const savedAs = entry.value?.saved_as;
    return `HTTP ${status ?? "response"} · saved as ${savedAs || "workflow data"}`;
  }
  if (entry.type === "file") {
    return `${entry.value?.operation || "File action"} · ${entry.value?.path || ""}`;
  }
  return formatValue(entry.value);
}

function lastExecution(workflowId) {
  return executions.find((execution) => String(execution.workflow_id) === String(workflowId));
}

function setWorkflowStatus(status) {
  workflowStatus.className = `status-badge status-${status.toLowerCase()}`;
  workflowStatus.textContent = status;
}

function renderStepFlow(workflow) {
  stepFlow.replaceChildren();
  document.querySelector("#step-summary").textContent = workflow
    ? `${workflow.steps.length} ${workflow.steps.length === 1 ? "step" : "steps"}`
    : "0 steps";
  if (!workflow) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "Create a workflow to see its steps here.";
    stepFlow.append(empty);
    return;
  }

  const latest = lastExecution(workflow.id);
  const completedSteps = new Set(
    latest ? latest.log.filter((entry) => !entry.error).map((entry) => entry.step) : [],
  );
  workflow.steps.forEach((step, index) => {
    if (index > 0) {
      const connector = document.createElement("span");
      connector.className = "step-connector";
      connector.setAttribute("aria-hidden", "true");
      connector.textContent = "→";
      stepFlow.append(connector);
    }

    const card = document.createElement("article");
    const completed = completedSteps.has(index + 1);
    const failed = latest?.status === "failed" && latest.failed_step === index + 1;
    card.className = `step-card${completed ? " step-complete" : ""}${failed ? " step-failed" : ""}`;
    const icon = document.createElement("span");
    icon.className = "step-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = stepIcon(step);
    const title = document.createElement("strong");
    title.textContent = stepTitle(step);
    const key = document.createElement("span");
    key.className = "step-key";
    key.textContent = stepSubtitle(step);
    const status = document.createElement("span");
    status.className = "step-status";
    status.textContent = failed ? "Failed" : completed ? "Completed" : "Ready";
    card.append(icon, title, key, status);
    stepFlow.append(card);
  });
}

function renderWorkflowDetails() {
  const workflow = selectedWorkflow();
  workflowSelect.value = workflow ? String(workflow.id) : "";
  document.querySelector("#delete-workflow").disabled = !workflow;
  document.querySelector("#edit-workflow").disabled = !workflow;
  document.querySelector("#run-workflow").disabled = !workflow;
  workflowTitle.textContent = workflow ? workflow.name : "Your workflows";
  document.querySelector("#breadcrumb-workflow").textContent = workflow?.name || "Select a workflow";
  workflowDescription.textContent = workflow
    ? `${workflow.steps.length} steps · Saved ${formatTime(workflow.created_at)}`
    : "Select a saved workflow or create a new one to get started.";
  setWorkflowStatus(workflow ? (lastExecution(workflow.id)?.status || "Ready") : "Ready");
  renderStepFlow(workflow);
}

function renderWorkflowSelect() {
  workflowSelect.replaceChildren();
  if (workflows.length === 0) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No saved workflows";
    workflowSelect.append(option);
  } else {
    workflows.forEach((workflow) => {
      const option = document.createElement("option");
      option.value = String(workflow.id);
      option.textContent = workflow.name;
      workflowSelect.append(option);
    });
    if (!workflows.some((workflow) => String(workflow.id) === selectedWorkflowId)) {
      selectedWorkflowId = String(workflows[0].id);
    }
  }
  renderWorkflowDetails();
}

function renderWorkflowCards() {
  workflowList.replaceChildren();
  if (workflows.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "No workflows saved yet.";
    workflowList.append(empty);
    return;
  }
  workflows.forEach((workflow) => {
    const card = document.createElement("article");
    card.className = "saved-workflow";
    const selectButton = document.createElement("button");
    selectButton.className = "saved-workflow-select";
    selectButton.type = "button";
    selectButton.textContent = `${workflow.name} · ${workflow.steps.length} steps`;
    selectButton.setAttribute("aria-pressed", String(String(workflow.id) === selectedWorkflowId));
    selectButton.addEventListener("click", () => {
      selectedWorkflowId = String(workflow.id);
      renderWorkflowSelect();
      renderWorkflowCards();
    });
    const removeButton = document.createElement("button");
    removeButton.className = "saved-workflow-delete";
    removeButton.type = "button";
    removeButton.textContent = "Delete";
    removeButton.addEventListener("click", () => deleteWorkflow(workflow.id));
    card.append(selectButton, removeButton);
    workflowList.append(card);
  });
}

function createHistoryRow(execution, entry, entryIndex) {
  const row = document.createElement("tr");
  const stepCell = document.createElement("td");
  stepCell.textContent = entry
    ? `${execution.workflow_name} · ${stepTitle({ type: entry.type })}`
    : `${execution.workflow_name} · Step ${execution.failed_step || execution.current_step}`;
  const statusCell = document.createElement("td");
  const status = document.createElement("span");
  const failed = entry?.error || (!entry && execution.status === "failed");
  status.className = `history-status ${failed ? "history-failed" : "history-success"}`;
  status.textContent = failed ? "Failed" : execution.status === "completed" ? "Success" : "Saved";
  statusCell.append(status);
  const timeCell = document.createElement("td");
  timeCell.textContent = entryIndex === 0 ? formatTime(execution.started_at) : "—";
  const durationCell = document.createElement("td");
  durationCell.textContent = entryIndex === 0 && execution.duration_ms !== null
    ? `${execution.duration_ms} ms`
    : entry?.attempts > 1 ? `${entry.attempts} attempts` : "—";
  const outputCell = document.createElement("td");
  outputCell.className = "history-output";
  if (failed) {
    const error = document.createElement("span");
    error.textContent = entry?.error || execution.error || "Step failed";
    outputCell.append(error);
    const resumeButton = document.createElement("button");
    resumeButton.className = "resume-button";
    resumeButton.type = "button";
    resumeButton.dataset.executionId = execution.id;
    resumeButton.textContent = "Retry / Resume";
    outputCell.append(resumeButton);
  } else {
    outputCell.textContent = entry ? historyResult(entry) : execution.error || "Run interrupted";
  }
  row.append(stepCell, statusCell, timeCell, durationCell, outputCell);
  return row;
}

function renderHistory() {
  historyBody.replaceChildren();
  document.querySelector("#execution-count").textContent = executions.length;
  if (executions.length === 0) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.className = "table-empty";
    cell.colSpan = 5;
    cell.textContent = "No workflow runs yet. Start a workflow to see its execution log.";
    row.append(cell);
    historyBody.append(row);
    return;
  }
  executions.forEach((execution) => {
    const entries = [...execution.log];
    if (entries.length === 0 || (
      execution.status === "failed" && !entries.some((entry) => entry.error)
    )) entries.push(null);
    entries.forEach((entry, index) => {
      historyBody.append(createHistoryRow(execution, entry, index));
    });
  });
}

async function loadWorkflows() {
  const refreshButton = document.querySelector("#refresh-workflows");
  refreshButton.disabled = true;
  try {
    workflows = await request("/api/workflows");
    document.querySelector("#workflow-count").textContent = workflows.length;
    document.querySelector("#saved-summary").textContent =
      `${workflows.length} ${workflows.length === 1 ? "workflow" : "workflows"}`;
    renderWorkflowSelect();
    renderWorkflowCards();
  } catch (error) {
    workflowList.replaceChildren();
    const failure = document.createElement("div");
    failure.className = "empty-state error-message";
    failure.textContent = error.message;
    workflowList.append(failure);
    setWorkflowStatus("Offline");
  } finally {
    refreshButton.disabled = false;
  }
}

async function loadExecutions() {
  try {
    executions = await request("/api/executions?limit=100");
    renderHistory();
    renderWorkflowDetails();
  } catch (error) {
    historyBody.replaceChildren();
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.className = "table-empty error-message";
    cell.colSpan = 5;
    cell.textContent = `Could not load run history: ${error.message}`;
    row.append(cell);
    historyBody.append(row);
  }
}

async function loadSchedules() {
  try {
    schedules = await request("/api/schedules");
    document.querySelector("#schedule-count").textContent = schedules.length;
    renderSchedules();
  } catch (error) {
    scheduleList.replaceChildren();
    const failure = document.createElement("div");
    failure.className = "empty-state error-message";
    failure.textContent = error.message;
    scheduleList.append(failure);
  }
}

function renderSchedules() {
  scheduleList.replaceChildren();
  if (schedules.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "No schedules yet. Add one to run a workflow automatically.";
    scheduleList.append(empty);
    return;
  }
  schedules.forEach((schedule) => {
    const row = document.createElement("article");
    row.className = "saved-workflow schedule-card";
    const details = document.createElement("span");
    const workflowName = workflows.find((workflow) => workflow.id === schedule.workflow_id)?.name || schedule.name;
    const repeat = schedule.schedule_type === "daily"
      ? `Daily at ${schedule.run_at} (server time)`
      : `Every ${schedule.interval_minutes} minutes`;
    details.textContent = `${workflowName} · ${repeat} · next ${formatTime(schedule.next_run_at)}`;
    const actions = document.createElement("div");
    actions.className = "schedule-actions";
    const toggle = document.createElement("button");
    toggle.className = "saved-workflow-delete";
    toggle.type = "button";
    toggle.dataset.action = "toggle";
    toggle.dataset.scheduleId = schedule.id;
    toggle.textContent = schedule.enabled ? "Pause" : "Resume";
    const remove = document.createElement("button");
    remove.className = "saved-workflow-delete";
    remove.type = "button";
    remove.dataset.action = "delete";
    remove.dataset.scheduleId = schedule.id;
    remove.textContent = "Delete";
    actions.append(toggle, remove);
    row.append(details, actions);
    scheduleList.append(row);
  });
}

async function runWorkflow() {
  const workflow = selectedWorkflow();
  if (!workflow) return;
  const runButton = document.querySelector("#run-workflow");
  runButton.disabled = true;
  runButton.textContent = "Running…";
  setWorkflowStatus("Running");
  try {
    await request(`/api/workflows/${workflow.id}/run`, {
      method: "POST",
      body: JSON.stringify({ data: {}, max_retries: 3 }),
    });
  } catch (error) {
    if (!error.executionId) window.alert(error.message);
  } finally {
    await loadExecutions();
    runButton.disabled = false;
    runButton.innerHTML = '<span aria-hidden="true">▶</span> Start Workflow';
  }
}

async function resumeExecution(executionId) {
  const rawData = window.prompt(
    "Optional JSON object to update workflow data before retrying/resuming.\nExample: {\"count\":2}\nLeave {} if no correction is needed.",
    "{}",
  );
  if (rawData === null) return;
  let data;
  try {
    data = JSON.parse(rawData);
    if (!data || Array.isArray(data) || typeof data !== "object") {
      throw new Error("Resume data must be a JSON object.");
    }
  } catch (error) {
    window.alert(error.message);
    return;
  }
  try {
    await request(`/api/executions/${executionId}/resume`, {
      method: "POST",
      body: JSON.stringify({ data, max_retries: 3 }),
    });
  } catch (error) {
    if (!error.executionId) window.alert(error.message);
  } finally {
    await loadExecutions();
  }
}

async function deleteWorkflow(workflowId) {
  const workflow = workflows.find((item) => item.id === workflowId);
  if (workflow && !window.confirm(`Delete "${workflow.name}" and its schedules?`)) return;
  try {
    await request(`/api/workflows/${workflowId}`, { method: "DELETE" });
    workflows = workflows.filter((item) => item.id !== workflowId);
    schedules = schedules.filter((item) => item.workflow_id !== workflowId);
    if (selectedWorkflowId === String(workflowId)) selectedWorkflowId = "";
    renderWorkflowSelect();
    renderWorkflowCards();
    renderSchedules();
    document.querySelector("#workflow-count").textContent = workflows.length;
    document.querySelector("#saved-summary").textContent =
      `${workflows.length} ${workflows.length === 1 ? "workflow" : "workflows"}`;
    document.querySelector("#schedule-count").textContent = schedules.length;
  } catch (error) {
    window.alert(error.message);
  }
}

function setStepError(message = "") {
  stepError.textContent = message;
  stepError.hidden = !message;
}

function addStepField({
  name,
  label,
  value = "",
  kind = "text",
  type = "text",
  options = [],
  placeholder = "",
}) {
  const wrapper = document.createElement("div");
  wrapper.className = "step-editor-field";
  const fieldLabel = document.createElement("label");
  fieldLabel.htmlFor = `step-field-${name}`;
  fieldLabel.textContent = label;
  const input = kind === "textarea"
    ? document.createElement("textarea")
    : kind === "select" ? document.createElement("select") : document.createElement("input");
  input.id = `step-field-${name}`;
  input.name = name;
  input.placeholder = placeholder;
  if (input instanceof HTMLInputElement) input.type = type;
  if (kind === "textarea") input.spellcheck = false;
  if (kind === "select") {
    options.forEach(([optionValue, optionLabel]) => {
      const option = document.createElement("option");
      option.value = optionValue;
      option.textContent = optionLabel;
      input.append(option);
    });
  }
  input.value = value;
  wrapper.append(fieldLabel, input);
  stepFields.append(wrapper);
  return input;
}

function readStepFieldValues() {
  return Object.fromEntries(
    [...stepFields.querySelectorAll("[name]")].map((field) => [field.name, field.value]),
  );
}

function renderStepFields(values = {}) {
  const type = stepTypeSelect.value;
  stepFields.replaceChildren();
  setStepError();

  if (["set", "add", "multiply", "uppercase", "append"].includes(type)) {
    addStepField({ name: "key", label: "Data key", value: values.key || "", placeholder: "" });
    if (type === "set") {
      addStepField({
        name: "value",
        label: "Value (JSON)",
        value: values.value === undefined ? "" : JSON.stringify(values.value, null, 2),
        kind: "textarea",
      });
    } else if (type === "add" || type === "multiply") {
      addStepField({
        name: "value",
        label: "Number",
        value: values.value ?? "",
        type: "number",
      });
    } else if (type === "append") {
      addStepField({ name: "value", label: "Text to append", value: values.value || "" });
    }
  } else if (type === "email") {
    addStepField({ name: "to", label: "To", value: values.to || "", placeholder: "person@example.com" });
    addStepField({ name: "subject", label: "Subject", value: values.subject || "" });
    addStepField({ name: "body", label: "Body", value: values.body || "", kind: "textarea" });
  } else if (type === "http") {
    addStepField({ name: "url", label: "HTTPS URL", value: values.url || "", placeholder: "https://api.example.com/v1/items" });
    addStepField({
      name: "method",
      label: "Method",
      value: values.method || "GET",
      kind: "select",
      options: ["GET", "POST", "PUT", "PATCH", "DELETE"].map((method) => [method, method]),
    });
    addStepField({ name: "save_as", label: "Save response as", value: values.save_as || "" });
    addStepField({
      name: "headers",
      label: "Headers (optional JSON object)",
      value: values.headers ? JSON.stringify(values.headers, null, 2) : "",
      kind: "textarea",
    });
    addStepField({
      name: "body",
      label: "Request body (optional JSON)",
      value: values.body === undefined ? "" : JSON.stringify(values.body, null, 2),
      kind: "textarea",
    });
  } else if (type === "file") {
    addStepField({
      name: "operation",
      label: "Operation",
      value: values.operation || "read",
      kind: "select",
      options: ["read", "write", "append", "exists"].map((operation) => [operation, operation]),
    });
    addStepField({ name: "path", label: "Relative file path", value: values.path || "", placeholder: "reports/output.txt" });
    addStepField({ name: "save_as", label: "Save result as", value: values.save_as || "" });
    if (["write", "append"].includes(values.operation || "read")) {
      addStepField({ name: "content", label: "Text content", value: values.content || "", kind: "textarea" });
    }
  }

  stepHint.textContent = type === "email"
    ? "Use {{key}} to insert workflow data. Email delivery requires SMTP settings in the server environment."
    : ["http", "file"].includes(type)
      ? "Use {{key}} to insert workflow data. The server needs HTTP_ALLOWED_HOSTS and WORKFLOW_FILE_ROOT configured."
      : "Use {{key}} to insert workflow data.";
}

function renderDraftSteps() {
  stepDraftList.replaceChildren();
  if (draftSteps.length === 0) {
    const empty = document.createElement("p");
    empty.className = "step-draft-empty";
    empty.textContent = "No steps yet. Choose a step type below and add your first step.";
    stepDraftList.append(empty);
    return;
  }

  draftSteps.forEach((step, index) => {
    const row = document.createElement("article");
    row.className = "step-draft-card";
    const details = document.createElement("div");
    details.className = "step-draft-details";
    const icon = document.createElement("span");
    icon.className = "step-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = stepIcon(step);
    const text = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = `${index + 1}. ${stepTitle(step)}`;
    const subtitle = document.createElement("span");
    subtitle.textContent = stepSubtitle(step) || "Configure this step";
    text.append(title, subtitle);
    details.append(icon, text);

    const actions = document.createElement("div");
    actions.className = "step-draft-actions";
    for (const [action, label] of [["edit", "Edit"], ["remove", "Remove"]]) {
      const button = document.createElement("button");
      button.className = action === "remove" ? "step-remove-button" : "step-edit-button";
      button.type = "button";
      button.dataset.stepAction = action;
      button.dataset.stepIndex = index;
      button.textContent = label;
      actions.append(button);
    }
    row.append(details, actions);
    stepDraftList.append(row);
  });
}

function stepFormError(message) {
  setStepError(message);
  const firstField = stepFields.querySelector("[name]");
  if (firstField) firstField.focus();
}

function collectStepDefinition() {
  const type = stepTypeSelect.value;
  const values = readStepFieldValues();
  const requireText = (name, label) => {
    if (!values[name]?.trim()) throw new Error(`${label} is required.`);
    return values[name].trim();
  };

  if (["set", "add", "multiply", "uppercase", "append"].includes(type)) {
    const step = { type, key: requireText("key", "Data key") };
    if (type === "set" && values.value.trim()) {
      try {
        step.value = JSON.parse(values.value);
      } catch {
        throw new Error("Value must be valid JSON, such as \"hello\" or 5.");
      }
    } else if (type === "add" || type === "multiply") {
      if (!values.value.trim() || !Number.isFinite(Number(values.value))) {
        throw new Error("A valid number is required.");
      }
      step.value = Number(values.value);
    } else if (type === "append") {
      step.value = values.value || "";
    }
    return step;
  }

  if (type === "email") {
    return {
      type,
      to: requireText("to", "To address"),
      subject: requireText("subject", "Subject"),
      body: requireText("body", "Body"),
    };
  }

  if (type === "http") {
    const url = requireText("url", "HTTPS URL");
    let parsedUrl;
    try {
      parsedUrl = new URL(url);
    } catch {
      throw new Error("Enter a valid HTTPS URL.");
    }
    if (
      parsedUrl.protocol !== "https:"
      || !parsedUrl.hostname
      || parsedUrl.username
      || parsedUrl.password
      || parsedUrl.hash
      || (parsedUrl.port && parsedUrl.port !== "443")
    ) {
      throw new Error("HTTP requests require an HTTPS URL on port 443 without credentials or a fragment.");
    }
    const step = {
      type,
      url,
      method: values.method,
      save_as: requireText("save_as", "Save response as"),
    };
    if (values.headers.trim()) {
      let headers;
      try {
        headers = JSON.parse(values.headers);
      } catch {
        throw new Error("Headers must be a valid JSON object.");
      }
      if (!headers || Array.isArray(headers) || typeof headers !== "object") {
        throw new Error("Headers must be a JSON object.");
      }
      if (Object.keys(headers).length > 50) throw new Error("Use at most 50 headers.");
      const forbidden = new Set([
        "connection", "content-length", "host", "proxy-authorization", "proxy-connection",
        "te", "trailer", "transfer-encoding", "upgrade",
      ]);
      for (const [name, value] of Object.entries(headers)) {
        if (!/^[!#$%&'*+.^_`|~0-9A-Za-z-]+$/.test(name)) {
          throw new Error("Header names must use valid HTTP token characters.");
        }
        if (forbidden.has(name.toLowerCase())) {
          throw new Error(`The "${name}" header is controlled by the engine.`);
        }
        if (typeof value !== "string") throw new Error("Header values must be strings.");
        if (/[\r\n]/.test(value) || value.length > 8192) {
          throw new Error("Header values must be single-line and at most 8192 characters.");
        }
      }
      step.headers = headers;
    }
    if (values.body.trim()) {
      try {
        step.body = JSON.parse(values.body);
      } catch {
        throw new Error("Request body must be valid JSON.");
      }
    }
    return step;
  }

  if (type === "file") {
    const operation = values.operation;
    const path = requireText("path", "Relative file path");
    const normalizedPath = path.replaceAll("\\", "/");
    if (
      path.length > 1024
      || path.includes("\0")
      || path.startsWith("/")
      || /^[A-Za-z]:/.test(path)
      || path.includes(":")
      || normalizedPath.split("/").includes("..")
    ) {
      throw new Error("Use a relative path inside WORKFLOW_FILE_ROOT; '..' and absolute paths are not allowed.");
    }
    const step = {
      type,
      operation,
      path,
      save_as: requireText("save_as", "Save result as"),
    };
    if (operation === "write" || operation === "append") {
      if (typeof values.content !== "string") throw new Error("Text content is required.");
      step.content = values.content;
    }
    return step;
  }

  throw new Error("Choose a supported step type.");
}

function resetStepComposer() {
  editingStepIndex = -1;
  stepTypeSelect.value = "set";
  document.querySelector("#step-composer-title").textContent = "Add a step";
  addStepButton.textContent = "＋ Add step";
  renderStepFields();
}

function openWorkflowDialog(workflow = null) {
  workflowForm.reset();
  const title = workflowDialog.querySelector(".dialog-heading h2");
  title.textContent = workflow ? "Edit workflow" : "Create a workflow";
  workflowForm.dataset.workflowId = workflow ? String(workflow.id) : "";
  document.querySelector("#workflow-name").value = workflow?.name || "";
  document.querySelector("#form-message").textContent = "";
  draftSteps = workflow
    ? JSON.parse(JSON.stringify(workflow.steps))
    : JSON.parse(JSON.stringify(exampleSteps));
  renderDraftSteps();
  resetStepComposer();
  workflowDialog.showModal();
  document.querySelector("#workflow-name").focus();
}

workflowForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const submitButton = workflowForm.querySelector('button[type="submit"]');
  submitButton.disabled = true;
  const message = document.querySelector("#form-message");
  message.textContent = "";
  message.className = "form-message";
  if (!document.querySelector("#workflow-name").value.trim()) {
    message.textContent = "Workflow name is required.";
    message.classList.add("error-message");
    submitButton.disabled = false;
    document.querySelector("#workflow-name").focus();
    return;
  }
  if (draftSteps.length === 0) {
    message.textContent = "Add at least one workflow step.";
    message.classList.add("error-message");
    submitButton.disabled = false;
    return;
  }
  try {
    const workflowId = workflowForm.dataset.workflowId;
    const saved = await request(
      workflowId ? `/api/workflows/${workflowId}` : "/api/workflows",
      {
      method: workflowId ? "PUT" : "POST",
      body: JSON.stringify({
        name: document.querySelector("#workflow-name").value.trim(),
        steps: draftSteps,
      }),
      },
    );
    selectedWorkflowId = String(saved.id);
    workflowDialog.close();
    await loadWorkflows();
  } catch (error) {
    message.textContent = error.message;
    message.classList.add("error-message");
  } finally {
    submitButton.disabled = false;
  }
});

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const submitButton = document.querySelector("#login-submit");
  submitButton.disabled = true;
  loginError.hidden = true;
  const password = document.querySelector("#login-password").value;
  if (authMode === "signup" && password !== document.querySelector("#confirm-password").value) {
    loginError.textContent = "The passwords do not match.";
    loginError.hidden = false;
    submitButton.disabled = false;
    return;
  }
  try {
    const session = await request(authMode === "signup" ? "/api/auth/signup" : "/api/auth/login", {
      method: "POST",
      body: JSON.stringify({
        email: document.querySelector("#login-email").value.trim(),
        password,
      }),
    });
    csrfToken = session.csrf_token;
    registrationOpen = false;
    setAuthMode("login");
    hideLogin();
    document.querySelector("#login-password").value = "";
    document.querySelector("#confirm-password").value = "";
    await loadAuthenticatedDashboard();
  } catch (error) {
    loginError.textContent = error.message;
    loginError.hidden = false;
  } finally {
    submitButton.disabled = false;
  }
});

document.querySelectorAll(".password-visibility").forEach((button) => {
  button.addEventListener("click", () => {
    const input = document.getElementById(button.dataset.passwordTarget);
    const reveal = input.type === "password";
    input.type = reveal ? "text" : "password";
    button.textContent = reveal ? "Hide" : "Show";
    button.setAttribute("aria-pressed", String(reveal));
    button.setAttribute(
      "aria-label",
      `${reveal ? "Hide" : "Show"} ${input.id === "confirm-password" ? "confirm password" : "password"}`,
    );
  });
});

authToggle.addEventListener("click", () => {
  setAuthMode(authMode === "signup" ? "login" : "signup");
  loginError.hidden = true;
  document.querySelector("#login-password").value = "";
  document.querySelector("#confirm-password").value = "";
});

document.querySelector("#logout-button").addEventListener("click", async () => {
  try {
    await request("/api/auth/logout", { method: "POST", body: "{}" });
    window.location.reload();
  } catch (error) {
    window.alert(error.message);
  }
});

document.querySelector("#step-type").addEventListener("change", () => renderStepFields());
stepFields.addEventListener("change", (event) => {
  if (event.target.name !== "operation") return;
  renderStepFields(readStepFieldValues());
});
addStepButton.addEventListener("click", () => {
  try {
    const step = collectStepDefinition();
    if (editingStepIndex < 0) draftSteps.push(step);
    else draftSteps[editingStepIndex] = step;
    renderDraftSteps();
    resetStepComposer();
  } catch (error) {
    stepFormError(error.message);
  }
});
stepDraftList.addEventListener("click", (event) => {
  const button = event.target.closest("[data-step-action]");
  if (!button) return;
  const index = Number(button.dataset.stepIndex);
  if (button.dataset.stepAction === "remove") {
    draftSteps.splice(index, 1);
    if (editingStepIndex === index) resetStepComposer();
    else if (editingStepIndex > index) editingStepIndex -= 1;
    renderDraftSteps();
    return;
  }
  editingStepIndex = index;
  const step = draftSteps[index];
  stepTypeSelect.value = step.type;
  document.querySelector("#step-composer-title").textContent = `Edit step ${index + 1}`;
  addStepButton.textContent = "Save step";
  renderStepFields(step);
  stepTypeSelect.focus();
});

scheduleForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const workflow = selectedWorkflow();
  if (!workflow) {
    window.alert("Create or select a workflow before adding a schedule.");
    return;
  }
  const scheduleType = document.querySelector("#schedule-type").value;
  const body = {
    workflow_id: workflow.id,
    schedule_type: scheduleType,
    ...(scheduleType === "interval"
      ? { interval_minutes: Number(document.querySelector("#schedule-interval").value) }
      : { run_at: document.querySelector("#schedule-time").value }),
  };
  const submit = scheduleForm.querySelector('button[type="submit"]');
  submit.disabled = true;
  try {
    await request("/api/schedules", { method: "POST", body: JSON.stringify(body) });
    await loadSchedules();
  } catch (error) {
    window.alert(error.message);
  } finally {
    submit.disabled = false;
  }
});

document.querySelector("#new-workflow").addEventListener("click", () => openWorkflowDialog());
document.querySelector("#edit-workflow").addEventListener("click", () => {
  const workflow = selectedWorkflow();
  if (workflow) openWorkflowDialog(workflow);
});
document.querySelector("#load-example").addEventListener("click", () => {
  draftSteps = JSON.parse(JSON.stringify(exampleSteps));
  renderDraftSteps();
  resetStepComposer();
});
document.querySelector("#close-dialog").addEventListener("click", () => workflowDialog.close());
document.querySelector("#cancel-dialog").addEventListener("click", () => workflowDialog.close());
document.querySelector("#refresh-workflows").addEventListener("click", async () => {
  await Promise.all([loadWorkflows(), loadExecutions(), loadSchedules()]);
});
document.querySelector("#run-workflow").addEventListener("click", runWorkflow);
document.querySelector("#delete-workflow").addEventListener("click", () => {
  const workflow = selectedWorkflow();
  if (workflow) deleteWorkflow(workflow.id);
});
workflowSelect.addEventListener("change", () => {
  selectedWorkflowId = workflowSelect.value;
  renderWorkflowDetails();
  renderWorkflowCards();
});
document.querySelector("#clear-history").addEventListener("click", async () => {
  if (!window.confirm("Clear all saved execution history?")) return;
  try {
    await request("/api/executions", { method: "DELETE" });
    executions = [];
    renderHistory();
    renderWorkflowDetails();
  } catch (error) {
    window.alert(error.message);
  }
});
historyBody.addEventListener("click", (event) => {
  const button = event.target.closest("[data-execution-id]");
  if (button) resumeExecution(Number(button.dataset.executionId));
});
document.querySelector("#schedule-type").addEventListener("change", (event) => {
  const daily = event.target.value === "daily";
  document.querySelector("#interval-label").hidden = daily;
  document.querySelector("#schedule-interval").hidden = daily;
  document.querySelector("#time-label").hidden = !daily;
  document.querySelector("#schedule-time").hidden = !daily;
});
scheduleList.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-schedule-id]");
  if (!button) return;
  const scheduleId = Number(button.dataset.scheduleId);
  try {
    if (button.dataset.action === "delete") {
      await request(`/api/schedules/${scheduleId}`, { method: "DELETE" });
    } else {
      const schedule = schedules.find((item) => item.id === scheduleId);
      await request(`/api/schedules/${scheduleId}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !schedule.enabled }),
      });
    }
    await loadSchedules();
  } catch (error) {
    window.alert(error.message);
  }
});

renderHistory();
initializeAuthentication();
window.setInterval(() => {
  if (!isAuthenticated) return;
  loadExecutions();
  loadSchedules();
}, 15000);

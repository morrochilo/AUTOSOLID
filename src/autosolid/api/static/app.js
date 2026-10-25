"use strict";

const API = "/api/v1";
const SOURCE_LIMIT_BYTES = 20 * 1024 * 1024;

const state = {
  projects: [],
  project: null,
  sources: [],
  approvals: [],
  spec: null,
  specSha256: null,
  loadedRevision: null,
  dirty: false,
};

const ui = {};
let busyDepth = 0;

document.addEventListener("DOMContentLoaded", init);

function init() {
  ui.health = document.getElementById("health");
  ui.createForm = document.getElementById("create-project-form");
  ui.projectName = document.getElementById("project-name");
  ui.createProject = document.getElementById("create-project");
  ui.refreshProjects = document.getElementById("refresh-projects");
  ui.projectList = document.getElementById("project-list");
  ui.projectEmpty = document.getElementById("project-empty");
  ui.emptyState = document.getElementById("empty-state");
  ui.workspace = document.getElementById("workspace");
  ui.projectTitle = document.getElementById("project-title");
  ui.projectMeta = document.getElementById("project-meta");
  ui.specRevision = document.getElementById("spec-revision");
  ui.specHash = document.getElementById("spec-hash");
  ui.status = document.getElementById("status");
  ui.reloadSpec = document.getElementById("reload-spec");
  ui.newTemplate = document.getElementById("new-template");
  ui.validateSpec = document.getElementById("validate-spec");
  ui.saveSpec = document.getElementById("save-spec");
  ui.editorState = document.getElementById("editor-state");
  ui.specEditor = document.getElementById("spec-editor");
  ui.diagnostics = document.getElementById("diagnostics");
  ui.diagnosticCount = document.getElementById("diagnostic-count");
  ui.questions = document.getElementById("questions");
  ui.questionCount = document.getElementById("question-count");
  ui.specViewer = document.getElementById("spec-viewer");
  ui.sourceForm = document.getElementById("source-form");
  ui.sourceFile = document.getElementById("source-file");
  ui.uploadSource = document.getElementById("upload-source");
  ui.sourceCount = document.getElementById("source-count");
  ui.sources = document.getElementById("sources");
  ui.approvalForm = document.getElementById("approval-form");
  ui.approvalState = document.getElementById("approval-state");
  ui.approvalTarget = document.getElementById("approval-target");
  ui.approver = document.getElementById("approver");
  ui.approvalNote = document.getElementById("approval-note");
  ui.approvalConfirm = document.getElementById("approval-confirm");
  ui.confirmRevision = document.getElementById("confirm-revision");
  ui.approveRevision = document.getElementById("approve-revision");
  ui.approvalCount = document.getElementById("approval-count");
  ui.approvals = document.getElementById("approvals");

  if (!ui.createForm || !ui.specEditor || !ui.sourceForm || !ui.approvalForm) {
    return;
  }

  ui.createForm.addEventListener("submit", (event) => {
    event.preventDefault();
    run(createProject);
  });
  ui.refreshProjects.addEventListener("click", () => run(refreshProjects));
  ui.reloadSpec.addEventListener("click", () => run(loadSpec));
  ui.newTemplate.addEventListener("click", insertTemplate);
  ui.validateSpec.addEventListener("click", () => run(validateSpec));
  ui.saveSpec.addEventListener("click", () => run(saveSpec));
  ui.sourceForm.addEventListener("submit", (event) => {
    event.preventDefault();
    run(uploadSource);
  });
  ui.sourceFile.addEventListener("change", syncSourceControls);
  ui.specEditor.addEventListener("input", () => {
    state.dirty = true;
    ui.editorState.textContent = "Sin guardar";
    renderApprovalPanel();
  });
  ui.approvalForm.addEventListener("submit", (event) => {
    event.preventDefault();
    run(approveRevision);
  });
  for (const control of [
    ui.approver,
    ui.approvalNote,
    ui.approvalConfirm,
  ]) {
    if (control) {
      control.addEventListener("input", renderApprovalPanel);
      control.addEventListener("change", renderApprovalPanel);
    }
  }

  renderSources();
  renderApprovalPanel();
  syncSourceControls();
  run(refreshHealth);
  run(refreshProjects);
}

function run(action) {
  busyDepth += 1;
  syncBusy();
  Promise.resolve()
    .then(action)
    .catch((error) => {
      showUnexpectedError(error);
    })
    .finally(() => {
      busyDepth = Math.max(0, busyDepth - 1);
      syncBusy();
    });
}

function syncBusy() {
  const busy = busyDepth > 0;
  for (const button of [
    ui.createProject,
    ui.refreshProjects,
    ui.reloadSpec,
    ui.newTemplate,
    ui.validateSpec,
    ui.saveSpec,
  ]) {
    if (button) {
      button.disabled = busy;
    }
  }
  if (ui.projectName) {
    ui.projectName.disabled = busy;
  }
  if (ui.specEditor) {
    ui.specEditor.readOnly = busy;
  }
  if (ui.projectList) {
    ui.projectList.classList.toggle("is-disabled", busy);
    for (const button of ui.projectList.querySelectorAll("button")) {
      button.disabled = busy;
    }
  }
  if (ui.sourceFile) {
    ui.sourceFile.disabled = busy;
  }
  if (ui.sources) {
    for (const button of ui.sources.querySelectorAll("button")) {
      button.disabled = busy;
    }
  }
  syncSourceControls();
  renderApprovalPanel();
  document.body.classList.toggle("is-busy", busy);
}

function syncSourceControls() {
  if (!ui.uploadSource) {
    return;
  }
  const hasFile = Boolean(
    ui.sourceFile && ui.sourceFile.files && ui.sourceFile.files.length > 0
  );
  ui.uploadSource.disabled = busyDepth > 0 || !state.project || !hasFile;
}

async function request(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("Accept", "application/json");
  if (typeof options.body === "string") {
    headers.set("Content-Type", "application/json");
  }

  let response;
  try {
    response = await fetch(path, { ...options, headers });
  } catch {
    const networkError = new Error("No se pudo conectar con el servicio local.");
    networkError.code = "NETWORK_ERROR";
    throw networkError;
  }

  const text = await response.text();
  let body = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = null;
    }
  }

  if (!response.ok) {
    const error = new Error(
      body && body.error && body.error.message
        ? body.error.message
        : `Error HTTP ${response.status}`
    );
    error.code =
      body && body.error && body.error.code
        ? body.error.code
        : "HTTP_ERROR";
    error.details =
      body && body.error && body.error.details
        ? body.error.details
        : null;
    error.status = response.status;
    throw error;
  }

  return { body, headers: response.headers, status: response.status };
}

async function refreshHealth() {
  try {
    const { body } = await request(`${API}/health`);
    if (body && body.status === "ok") {
      ui.health.textContent = "Servicio local activo";
      ui.health.className = "health health-ok";
    } else {
      ui.health.textContent = "Estado desconocido";
      ui.health.className = "health health-pending";
    }
  } catch {
    ui.health.textContent = "Servicio no disponible";
    ui.health.className = "health health-error";
  }
}

async function refreshProjects({ autoSelect = true } = {}) {
  try {
    const { body } = await request(`${API}/projects`);
    state.projects = Array.isArray(body) ? body : [];

    if (state.project) {
      const current = state.projects.find(
        (project) => project.id === state.project.id
      );
      if (current) {
        state.project = current;
        if (
          state.loadedRevision !== null &&
          current.current_revision !== state.loadedRevision
        ) {
          setStatus(
            `Hay una revisión más reciente (${current.current_revision}). ` +
              `El editor sigue basado en la revisión ${state.loadedRevision}; ` +
              "usa «Cargar actual» antes de guardar.",
            "warn"
          );
        }
      } else {
        clearSelection();
        setStatus("El proyecto seleccionado ya no existe.", "warn");
      }
    }

    renderProjects();
    renderProjectHeader();
    renderApprovalPanel();

    if (!state.project && autoSelect && state.projects.length > 0) {
      await selectProject(state.projects[0].id);
    } else {
      updateVisibility();
    }
  } catch (error) {
    showApiError("No se pudieron cargar los proyectos.", error);
  } finally {
    ui.refreshProjects.disabled = busyDepth > 0;
  }
}

function renderProjects() {
  ui.projectList.replaceChildren();

  for (const project of state.projects) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "project-item";
    button.disabled = busyDepth > 0;
    if (state.project && state.project.id === project.id) {
      button.setAttribute("aria-current", "true");
    }

    const name = document.createElement("strong");
    name.textContent = project.name;
    const meta = document.createElement("span");
    meta.textContent = `Revisión ${project.current_revision}`;
    button.append(name, meta);

    button.addEventListener("click", () => {
      run(() => selectProject(project.id));
    });
    ui.projectList.append(button);
  }

  ui.projectEmpty.hidden = state.projects.length > 0;
}

async function selectProject(projectId) {
  setStatus("Cargando proyecto…", "busy");

  try {
    const { body } = await request(
      `${API}/projects/${encodeURIComponent(projectId)}`
    );
    state.project = body;
    state.sources = [];
    state.approvals = [];
    state.spec = null;
    state.specSha256 = null;
    state.loadedRevision = null;
    state.dirty = false;
    ui.specEditor.value = "";
    ui.editorState.textContent = "Cargando…";
    if (ui.sourceFile) {
      ui.sourceFile.value = "";
    }
    if (ui.approvalForm) {
      ui.approvalForm.reset();
    }
    renderSources();
    renderApprovals();
    renderApprovalPanel();
    renderViewer({});
    renderDiagnostics([], "Cargando…");
    renderQuestions(null);
    renderProjects();
    renderProjectHeader();
    updateVisibility();
    await loadSpec();
    await refreshSources();
    syncSourceControls();
  } catch (error) {
    showApiError("No se pudo abrir el proyecto.", error);
  }
}

async function createProject() {
  const name = ui.projectName.value.trim();
  if (!name) {
    setStatus("Escribe un nombre de proyecto.", "error");
    ui.projectName.focus();
    return;
  }

  setStatus("Creando proyecto…", "busy");

  try {
    const { body } = await request(`${API}/projects`, {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    ui.projectName.value = "";
    await refreshProjects({ autoSelect: false });
    await selectProject(body.id);
    setStatus(`Proyecto "${body.name}" creado.`, "ok");
  } catch (error) {
    showApiError("No se pudo crear el proyecto.", error);
  }
}

async function loadSpec({ quiet = false } = {}) {
  if (!state.project) {
    return false;
  }

  if (!quiet) {
    setStatus("Cargando revisión…", "busy");
  }

  try {
    const { body, headers } = await request(
      `${API}/projects/${encodeURIComponent(state.project.id)}/cadspec`
    );
    applySpec(body, headers);
    await refreshApprovals({ quiet: true });
    if (!quiet) {
      setStatus(`Revisión ${body.revision} cargada.`, "ok");
    }
    return true;
  } catch (error) {
    if (error.code === "CADSPEC_NOT_FOUND") {
      applyTemplate();
      await refreshApprovals({ quiet: true });
      if (!quiet) {
        setStatus(
          "El proyecto todavía no tiene una revisión. Se cargó una plantilla vacía.",
          "warn"
        );
      }
      return true;
    }
    if (error.code === "PROJECT_NOT_FOUND") {
      clearSelection();
      showApiError("El proyecto ya no existe.", error);
      return false;
    }
    showApiError("No se pudo cargar la especificación.", error);
    return false;
  }
}

function applySpec(spec, headers) {
  state.spec = spec;
  state.specSha256 = headers.get("X-CadSpec-SHA256") || null;
  state.loadedRevision = spec.revision;
  state.dirty = false;
  ui.specEditor.value = JSON.stringify(spec, null, 2);
  ui.editorState.textContent = "Cargada";
  renderViewer(spec);
  renderDiagnostics([], "Aún sin validar.");
  renderQuestions(spec);
  renderProjectHeader();
  renderApprovalPanel();
  updateVisibility();
}

function applyTemplate() {
  if (!state.project) {
    return;
  }

  const template = {
    schema_version: "0.1.0",
    project_id: state.project.id,
    revision: state.project.current_revision,
    units: { length: "mm", angle: "deg" },
    sources: [],
    evidence: [],
    parameters: {},
    references: [],
    sketches: [],
    features: [],
    open_questions: [],
    assumptions: [],
  };

  state.spec = template;
  state.specSha256 = null;
  state.loadedRevision = state.project.current_revision;
  state.dirty = true;
  ui.specEditor.value = JSON.stringify(template, null, 2);
  ui.editorState.textContent = "Plantilla";
  renderViewer(template);
  renderDiagnostics([], "Aún sin validar.");
  renderQuestions(template);
  renderProjectHeader();
  renderApprovalPanel();
  updateVisibility();
}

function insertTemplate() {
  if (!state.project) {
    return;
  }
  applyTemplate();
  setStatus("Plantilla vacía cargada; todavía no se ha guardado.", "warn");
}

async function refreshSources({ quiet = false } = {}) {
  if (!state.project) {
    state.sources = [];
    renderSources();
    return;
  }

  try {
    const { body } = await request(
      `${API}/projects/${encodeURIComponent(state.project.id)}/sources`
    );
    state.sources = Array.isArray(body) ? body : [];
    renderSources();
  } catch (error) {
    state.sources = [];
    renderSources();
    if (!quiet) {
      showApiError("No se pudieron cargar las fuentes.", error);
    }
  }
}

function renderSources() {
  if (!ui.sources) {
    return;
  }
  ui.sourceCount.textContent = String(state.sources.length);
  ui.sources.replaceChildren();

  if (state.sources.length === 0) {
    ui.sources.append(emptyItem("No hay fuentes cargadas."));
    return;
  }

  for (const source of state.sources) {
    const item = document.createElement("li");
    item.className = "source-item";

    const info = document.createElement("div");
    info.className = "source-info";
    const name = document.createElement("span");
    name.className = "source-name";
    name.textContent = source.filename || "Fuente sin nombre";
    const meta = document.createElement("span");
    meta.className = "source-meta";
    meta.textContent =
      `${source.kind || "desconocido"} · ${formatBytes(source.byte_size)} · ` +
      shortHash(source.sha256);
    meta.title = source.sha256 ? `SHA-256 ${source.sha256}` : "";
    info.append(name, meta);

    const actions = document.createElement("div");
    actions.className = "source-actions";

    const download = document.createElement("a");
    download.className = "button ghost small";
    download.href =
      `${API}/projects/${encodeURIComponent(source.project_id)}` +
      `/sources/${encodeURIComponent(source.id)}/content`;
    download.textContent = "Descargar";
    download.setAttribute("download", "");

    const reference = document.createElement("button");
    reference.type = "button";
    reference.className = "button secondary small";
    reference.textContent = "Añadir al CadSpec";
    reference.disabled = busyDepth > 0;
    reference.addEventListener("click", () => {
      run(() => addSourceReference(source));
    });

    actions.append(download, reference);
    item.append(info, actions);
    ui.sources.append(item);
  }
}

async function uploadSource() {
  if (!state.project) {
    return;
  }
  const file =
    ui.sourceFile && ui.sourceFile.files
      ? ui.sourceFile.files[0]
      : null;
  if (!file) {
    setStatus("Selecciona un archivo antes de añadir la fuente.", "warn");
    return;
  }
  if (file.size === 0) {
    setStatus("El archivo está vacío.", "error");
    return;
  }
  if (file.size > SOURCE_LIMIT_BYTES) {
    setStatus(
      `El archivo supera el límite de ${formatBytes(SOURCE_LIMIT_BYTES)}.`,
      "error"
    );
    return;
  }

  setStatus("Añadiendo fuente…", "busy");
  try {
    const { body, status } = await request(
      `${API}/projects/${encodeURIComponent(state.project.id)}/sources` +
        `?filename=${encodeURIComponent(file.name)}`,
      {
        method: "POST",
        body: file,
        headers: {
          "Content-Type": file.type || "application/octet-stream",
        },
      }
    );
    ui.sourceFile.value = "";
    await refreshSources({ quiet: true });
    await refreshProjects({ autoSelect: false });
    syncSourceControls();
    const label = status === 201 ? "Fuente añadida" : "La fuente ya existía";
    setStatus(
      `${label}: ${body && body.filename ? body.filename : file.name}.`,
      "ok"
    );
  } catch (error) {
    if (error.code === "SOURCE_TOO_LARGE") {
      setStatus(
        `El archivo supera el límite de ${formatBytes(SOURCE_LIMIT_BYTES)}.`,
        "error"
      );
      return;
    }
    showApiError("No se pudo añadir la fuente.", error);
  }
}

function addSourceReference(source) {
  if (!state.project) {
    return;
  }
  let spec;
  try {
    spec = readEditor();
  } catch (error) {
    showApiError("No se pudo añadir la fuente al editor.", error);
    return;
  }
  if (spec.project_id !== state.project.id) {
    setStatus(
      "El project_id del editor no coincide con el proyecto seleccionado.",
      "error"
    );
    return;
  }
  if (!Array.isArray(spec.sources)) {
    setStatus("El campo sources del editor debe ser una lista.", "error");
    return;
  }
  const alreadyReferenced = spec.sources.some(
    (item) =>
      item &&
      (item.id === source.id ||
        (item.sha256 === source.sha256 && item.kind === source.kind))
  );
  if (alreadyReferenced) {
    setStatus("La fuente ya está referenciada en el editor.", "warn");
    return;
  }

  spec.sources.push({
    id: source.id,
    kind: source.kind,
    sha256: source.sha256,
  });
  state.spec = spec;
  ui.specEditor.value = JSON.stringify(spec, null, 2);
  ui.editorState.textContent = "Sin guardar";
  state.dirty = true;
  renderViewer(spec);
  renderDiagnostics([], "Aún sin validar.");
  renderQuestions(spec);
  renderApprovalPanel();
  setStatus(
    `Fuente "${source.filename}" añadida al editor. ` +
      "Valida y guarda la revisión para persistir la referencia.",
    "ok"
  );
}

function formatBytes(value) {
  if (!Number.isFinite(value) || value < 0) {
    return "tamaño desconocido";
  }
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KiB`;
  }
  return `${(value / (1024 * 1024)).toFixed(1)} MiB`;
}

function shortHash(value) {
  return value ? `${value.slice(0, 12)}…` : "sin hash";
}

function readEditor() {
  let parsed;
  try {
    parsed = JSON.parse(ui.specEditor.value);
  } catch (error) {
    const invalid = new Error("El editor no contiene JSON válido.");
    invalid.code = "JSON_INVALID";
    invalid.details = { position: error instanceof SyntaxError ? "revisar" : null };
    throw invalid;
  }

  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    const invalid = new Error("La especificación debe ser un objeto JSON.");
    invalid.code = "JSON_INVALID";
    throw invalid;
  }
  return parsed;
}

async function validateSpec() {
  if (!state.project) {
    return;
  }

  let spec;
  try {
    spec = readEditor();
  } catch (error) {
    ui.editorState.textContent = "JSON inválido";
    showApiError("No se pudo validar.", error);
    return;
  }

  setStatus("Validando especificación…", "busy");

  try {
    const { body } = await request(
      `${API}/projects/${encodeURIComponent(state.project.id)}/cadspec/validate`,
      { method: "POST", body: JSON.stringify(spec) }
    );

    state.spec = spec;
    renderViewer(spec);
    renderQuestions(spec);
    renderDiagnostics(body.diagnostics || []);
    renderProjectHeader();

    if (body.valid) {
      ui.editorState.textContent = "Válida (sin guardar)";
      setStatus(
        "Especificación válida. Todavía no se ha guardado.",
        "ok"
      );
    } else {
      ui.editorState.textContent = "Con errores";
      setStatus(
        "La validación encontró errores. Corrige el JSON antes de guardar.",
        "error"
      );
    }
  } catch (error) {
    showApiError("No se pudo validar la especificación.", error);
  }
}

async function saveSpec() {
  if (!state.project) {
    return;
  }

  let spec;
  try {
    spec = readEditor();
  } catch (error) {
    ui.editorState.textContent = "JSON inválido";
    showApiError("No se pudo guardar.", error);
    return;
  }

  // Save against the revision the editor was loaded from, not the latest
  // project metadata, so a stale editor can never overwrite an external change.
  const expectedRevision =
    state.loadedRevision !== null
      ? state.loadedRevision
      : state.project.current_revision;

  setStatus("Guardando revisión…", "busy");

  try {
    const { body, headers } = await request(
      `${API}/projects/${encodeURIComponent(state.project.id)}/cadspec`,
      {
        method: "PUT",
        body: JSON.stringify({
          expected_revision: expectedRevision,
          spec,
        }),
      }
    );

    state.spec = body;
    state.specSha256 = headers.get("X-CadSpec-SHA256") || null;
    state.loadedRevision = body.revision;
    state.project.current_revision = body.revision;
    state.dirty = false;

    ui.specEditor.value = JSON.stringify(body, null, 2);
    ui.editorState.textContent = "Guardada";
    renderViewer(body);
    renderQuestions(body);
    renderDiagnostics([], "Sin diagnósticos.");
    renderProjectHeader();
    await refreshProjects({ autoSelect: false });
    await refreshApprovals({ quiet: true });
    renderApprovalPanel();
    setStatus(`Revisión ${body.revision} guardada.`, "ok");
  } catch (error) {
    if (error.code === "SPEC_INVALID" && Array.isArray(error.details)) {
      renderDiagnostics(error.details);
      ui.editorState.textContent = "Con errores";
      setStatus(
        "El servidor rechazó la especificación; no se guardó ninguna revisión.",
        "error"
      );
      return;
    }

    if (error.code === "REVISION_CONFLICT") {
      const current =
        error.details && error.details.current_revision !== undefined
          ? error.details.current_revision
          : "desconocida";
      const message =
        `Conflicto de revisión: el servidor tiene la revisión ${current}. ` +
        "No se guardó nada.";
      setStatus(message, "warn");
      await refreshProjects({ autoSelect: false });
      const reloaded = await loadSpec({ quiet: true });
      if (reloaded && state.project) {
        setStatus(
          `${message} Se recargó la revisión ${state.project.current_revision}.`,
          "warn"
        );
      }
      return;
    }

    showApiError("No se pudo guardar la revisión.", error);
  }
}

async function refreshApprovals({ quiet = false } = {}) {
  if (!state.project) {
    state.approvals = [];
    renderApprovals();
    renderApprovalPanel();
    return;
  }

  try {
    const { body } = await request(
      `${API}/projects/${encodeURIComponent(state.project.id)}/approvals`
    );
    state.approvals = Array.isArray(body) ? body : [];
    renderApprovals();
    renderApprovalPanel();
  } catch (error) {
    state.approvals = [];
    renderApprovals();
    renderApprovalPanel();
    if (!quiet) {
      showApiError("No se pudieron cargar las aprobaciones.", error);
    }
  }
}

function currentApprovalForLoadedRevision() {
  if (!state.project || state.loadedRevision === null) {
    return null;
  }
  return (
    state.approvals.find(
      (approval) =>
        approval &&
        approval.scope === "design" &&
        approval.revision === state.loadedRevision &&
        approval.status === "valid"
    ) || null
  );
}

function canApproveRevision() {
  return Boolean(
    state.project &&
      !state.dirty &&
      state.specSha256 &&
      state.loadedRevision !== null &&
      state.loadedRevision === state.project.current_revision &&
      !currentApprovalForLoadedRevision()
  );
}

function syncApprovalControls() {
  if (!ui.approveRevision) {
    return;
  }
  const busy = busyDepth > 0;
  ui.approveRevision.disabled = busy || !canApproveRevision();
  for (const control of [
    ui.approver,
    ui.approvalNote,
    ui.approvalConfirm,
  ]) {
    if (control) {
      control.disabled = busy;
    }
  }
}

function renderApprovalPanel() {
  if (!ui.approvalState || !ui.approvalTarget) {
    return;
  }

  if (ui.confirmRevision) {
    ui.confirmRevision.textContent =
      state.loadedRevision !== null ? String(state.loadedRevision) : "—";
  }

  let label = "Sin revisión";
  let kind = "neutral";
  let message = "Selecciona un proyecto y guarda una revisión para aprobarla.";
  const approval = currentApprovalForLoadedRevision();

  if (state.project) {
    if (state.loadedRevision === null) {
      message = "El proyecto no tiene una revisión cargada.";
    } else if (!state.specSha256) {
      message =
        "La revisión cargada todavía no tiene hash. " +
        "Guarda la revisión antes de aprobar.";
    } else if (state.loadedRevision !== state.project.current_revision) {
      label = "Desactualizada";
      kind = "stale";
      message =
        `La revisión cargada (${state.loadedRevision}) no es la actual ` +
        `(${state.project.current_revision}). Usa «Cargar actual» antes de aprobar.`;
    } else if (state.dirty) {
      label = "Sin guardar";
      kind = "stale";
      message =
        `Hay cambios sin guardar en la revisión ${state.loadedRevision}. ` +
        "Guarda o recarga antes de aprobar.";
    } else if (approval) {
      label = "Vigente";
      kind = "valid";
      message =
        `Revisión ${approval.revision} aprobada por ${approval.approved_by} ` +
        `el ${formatDate(approval.created_at)}.`;
    } else {
      label = "Pendiente";
      kind = "pending";
      message =
        `Revisión ${state.loadedRevision} con SHA-256 ` +
        `${shortHash(state.specSha256)}. Aún no tiene aprobación.`;
    }
  }

  ui.approvalState.textContent = label;
  ui.approvalState.className = `state-badge state-${kind}`;
  ui.approvalTarget.textContent = message;
  syncApprovalControls();
}

function renderApprovals() {
  if (!ui.approvals) {
    return;
  }
  ui.approvalCount.textContent = String(state.approvals.length);
  ui.approvals.replaceChildren();

  if (state.approvals.length === 0) {
    ui.approvals.append(emptyItem("Sin aprobaciones registradas."));
    return;
  }

  // The API returns oldest first; show the most recent decision first.
  const approvals = [...state.approvals].reverse();
  for (const approval of approvals) {
    const valid = approval.status === "valid";
    const item = document.createElement("li");
    item.className = `approval-item ${valid ? "is-valid" : "is-stale"}`;

    const head = document.createElement("div");
    head.className = "approval-item-head";
    const revision = document.createElement("strong");
    revision.textContent = `Revisión ${approval.revision}`;
    const badge = document.createElement("span");
    badge.className = `state-badge small ${valid ? "state-valid" : "state-stale"}`;
    badge.textContent = valid ? "Vigente" : "Obsoleto";
    head.append(revision, badge);

    const meta = document.createElement("div");
    meta.className = "approval-meta";
    meta.textContent =
      `${approval.approved_by || "Revisor desconocido"} · ` +
      `${approval.scope || "design"} · ${formatDate(approval.created_at)}`;

    const hash = document.createElement("div");
    hash.className = "approval-hash";
    hash.textContent = shortHash(approval.revision_sha256);
    hash.title = approval.revision_sha256
      ? `SHA-256 ${approval.revision_sha256}`
      : "";

    item.append(head, meta, hash);

    if (approval.note) {
      const note = document.createElement("p");
      note.className = "approval-note";
      note.textContent = approval.note;
      item.append(note);
    }

    ui.approvals.append(item);
  }
}

async function approveRevision() {
  if (!state.project) {
    return;
  }

  const revision = state.loadedRevision;
  const sha256 = state.specSha256;
  if (!canApproveRevision()) {
    setStatus(
      "La revisión cargada no se puede aprobar en este momento. " +
        "Comprueba que esté guardada, que sea la actual y que no tenga cambios sin guardar.",
      "warn"
    );
    renderApprovalPanel();
    return;
  }

  const approvedBy = ui.approver ? ui.approver.value.trim() : "";
  if (!approvedBy) {
    setStatus("Escribe el nombre del revisor.", "error");
    if (ui.approver) {
      ui.approver.focus();
    }
    return;
  }
  if (!ui.approvalConfirm || !ui.approvalConfirm.checked) {
    setStatus("Confirma que revisaste la revisión antes de aprobarla.", "warn");
    return;
  }

  const note = ui.approvalNote ? ui.approvalNote.value.trim() : "";
  setStatus(`Registrando la aprobación de la revisión ${revision}…`, "busy");

  try {
    const { status } = await request(
      `${API}/projects/${encodeURIComponent(state.project.id)}/approvals`,
      {
        method: "POST",
        body: JSON.stringify({
          revision,
          sha256,
          scope: "design",
          approved_by: approvedBy,
          note: note || null,
        }),
      }
    );

    if (ui.approvalNote) {
      ui.approvalNote.value = "";
    }
    if (ui.approvalConfirm) {
      ui.approvalConfirm.checked = false;
    }
    await refreshProjects({ autoSelect: false });
    await refreshApprovals({ quiet: true });
    renderApprovalPanel();
    setStatus(
      status === 201
        ? `Revisión ${revision} aprobada por ${approvedBy}. No se construyó nada.`
        : `La revisión ${revision} ya estaba aprobada. No se construyó nada.`,
      "ok"
    );
  } catch (error) {
    if (error.code === "REVISION_CONFLICT") {
      setStatus(
        "La revisión cargada ya no es la actual. No se registró la aprobación.",
        "warn"
      );
      await refreshProjects({ autoSelect: false });
      await refreshApprovals({ quiet: true });
      renderApprovalPanel();
      return;
    }

    if (error.code === "APPROVAL_HASH_MISMATCH") {
      setStatus(
        "El hash cargado no coincide con la revisión del servidor. " +
          "No se registró la aprobación; recarga la revisión.",
        "warn"
      );
      await refreshApprovals({ quiet: true });
      renderApprovalPanel();
      return;
    }

    if (error.code === "APPROVAL_BLOCKED" && Array.isArray(error.details)) {
      renderDiagnostics(error.details);
      ui.editorState.textContent = "Con errores";
      setStatus(
        "La revisión no cumple las condiciones para aprobarse. " +
          "Corrige los diagnósticos y guarda otra revisión.",
        "error"
      );
      return;
    }

    showApiError("No se pudo registrar la aprobación.", error);
  }
}

function renderProjectHeader() {
  if (!state.project) {
    ui.projectTitle.textContent = "—";
    ui.projectMeta.textContent = "";
    ui.specRevision.textContent = "—";
    updateHash(null);
    return;
  }

  ui.projectTitle.textContent = state.project.name;
  ui.projectMeta.textContent =
    `ID ${state.project.id} · Creado ${formatDate(state.project.created_at)}` +
    ` · Actualizado ${formatDate(state.project.updated_at)}`;
  const displayedRevision =
    state.loadedRevision !== null
      ? state.loadedRevision
      : state.project.current_revision;
  ui.specRevision.textContent = String(displayedRevision);
  updateHash(state.specSha256);
}

function updateHash(hash) {
  if (!hash) {
    ui.specHash.textContent = "Sin hash";
    ui.specHash.title = "";
    return;
  }
  ui.specHash.textContent = `${hash.slice(0, 16)}…`;
  ui.specHash.title = `SHA-256 ${hash}`;
}

function renderViewer(value) {
  let text;
  try {
    text = JSON.stringify(value, null, 2);
  } catch {
    text = String(value);
  }
  ui.specViewer.textContent = text === undefined ? "{}" : text;
}

function renderDiagnostics(items, emptyMessage = "Sin diagnósticos.") {
  const diagnostics = Array.isArray(items) ? items : [];
  ui.diagnosticCount.textContent = String(diagnostics.length);
  ui.diagnostics.replaceChildren();

  if (diagnostics.length === 0) {
    ui.diagnostics.append(emptyItem(emptyMessage));
    return;
  }

  for (const diagnostic of diagnostics) {
    const severity = allowedSeverity(diagnostic.severity, "error");
    const item = document.createElement("li");
    item.className = `item severity-${severity}`;

    const head = document.createElement("div");
    head.className = "item-head";
    const code = document.createElement("code");
    code.className = "item-code";
    code.textContent = diagnostic.code || "REQUEST_INVALID";
    const severityLabel = document.createElement("span");
    severityLabel.className = "item-severity";
    severityLabel.textContent = severity;
    head.append(code, severityLabel);

    const path = document.createElement("div");
    path.className = "item-path";
    path.textContent = diagnostic.path || "$";

    const message = document.createElement("p");
    message.className = "item-message";
    message.textContent = diagnostic.message || "Sin mensaje.";

    item.append(head, path, message);
    ui.diagnostics.append(item);
  }
}

function renderQuestions(spec) {
  const allQuestions =
    spec && Array.isArray(spec.open_questions) ? spec.open_questions : [];
  const questions = allQuestions.filter(
    (question) => question && question.status !== "resolved"
  );

  ui.questionCount.textContent = String(questions.length);
  ui.questions.replaceChildren();

  if (questions.length === 0) {
    ui.questions.append(emptyItem("Sin preguntas abiertas."));
    return;
  }

  for (const question of questions) {
    const severity = allowedSeverity(question.severity, "minor");
    const item = document.createElement("li");
    item.className = `item severity-${severity}`;

    const head = document.createElement("div");
    head.className = "item-head";
    const code = document.createElement("code");
    code.className = "item-code";
    code.textContent = question.id || "PREGUNTA";
    const severityLabel = document.createElement("span");
    severityLabel.className = "item-severity";
    severityLabel.textContent = severity;
    head.append(code, severityLabel);

    const message = document.createElement("p");
    message.className = "item-message";
    message.textContent = question.text || "Sin texto.";

    item.append(head, message);
    ui.questions.append(item);
  }
}

function emptyItem(message) {
  const item = document.createElement("li");
  item.className = "empty";
  item.textContent = message;
  return item;
}

function allowedSeverity(value, fallback) {
  return ["error", "warning", "info", "critical", "major", "minor"].includes(
    value
  )
    ? value
    : fallback;
}

function setStatus(message, kind = "info") {
  ui.status.textContent = message || "";
  ui.status.className = message ? `status is-${kind}` : "status";
}

function showApiError(prefix, error) {
  const details = formatDetails(error && error.details);
  const message =
    error && error.message ? error.message : "Error desconocido.";
  setStatus(`${prefix} ${message}${details ? ` · ${details}` : ""}`, "error");
}

function showUnexpectedError(error) {
  const message =
    error && error.message ? error.message : "Error desconocido.";
  setStatus(`Error inesperado: ${message}`, "error");
}

function formatDetails(details) {
  if (!details) {
    return "";
  }
  if (Array.isArray(details)) {
    return details
      .map((item) => {
        if (item && typeof item === "object") {
          return item.message || item.code || JSON.stringify(item);
        }
        return String(item);
      })
      .join(" · ");
  }
  if (typeof details === "object") {
    return Object.entries(details)
      .map(([key, value]) => `${key}: ${String(value)}`)
      .join(" · ");
  }
  return String(details);
}

function formatDate(value) {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return new Intl.DateTimeFormat("es", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function clearSelection() {
  state.project = null;
  state.sources = [];
  state.approvals = [];
  state.spec = null;
  state.specSha256 = null;
  state.loadedRevision = null;
  state.dirty = false;
  ui.projectTitle.textContent = "—";
  ui.projectMeta.textContent = "";
  ui.specRevision.textContent = "—";
  updateHash(null);
  ui.specEditor.value = "";
  ui.editorState.textContent = "Sin cargar";
  if (ui.sourceFile) {
    ui.sourceFile.value = "";
  }
  if (ui.approvalForm) {
    ui.approvalForm.reset();
  }
  renderSources();
  renderApprovals();
  renderApprovalPanel();
  renderViewer({});
  renderDiagnostics([], "Aún sin validar.");
  renderQuestions(null);
  setStatus("");
  updateVisibility();
  renderProjects();
}

function updateVisibility() {
  const hasProject = Boolean(state.project);
  ui.emptyState.hidden = hasProject;
  ui.workspace.hidden = !hasProject;
  syncSourceControls();
}

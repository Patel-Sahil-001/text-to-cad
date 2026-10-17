/**
 * Text-to-CAD Studio Dashboard Client
 * Manages Three.js WebGL rendering, prompt polishing, cadgen synthesis,
 * live parameter adjustments, and conversational CAD editing.
 */

// Dynamic Backend API Host
// Automatically routes to live Render backend when hosted on Vercel
const API_BASE = (window.location.hostname.includes("vercel.app") || window.location.hostname.includes("text-to-cad-static"))
  ? "https://text-to-cad.onrender.com"
  : (window.location.origin.startsWith("http") && !window.location.hostname.includes("localhost") && !window.location.hostname.includes("127.0.0.1") && !window.location.hostname.includes("onrender.com")
      ? "https://text-to-cad.onrender.com"
      : "");

// State
let currentProjectId = null;
let currentStlMesh = null;
let currentCode = "";
let currentSpec = "";
let currentParameters = {};

// Three.js Globals
let scene, camera, renderer, controls;
let gridHelper, dirLight, ambientLight;
let currentMaterialType = "cadBlue";
let isWireframe = false;

// DOM Elements
const promptInput = document.getElementById("promptInput");
const btnPolishPrompt = document.getElementById("btnPolishPrompt");
const polishedSpecText = document.getElementById("polishedSpecText");
const cadCodeInput = document.getElementById("cadCodeInput");
const btnToggleCodeView = document.getElementById("btnToggleCodeView");
const codeEditorWrapper = document.getElementById("codeEditorWrapper");
const parametersContainer = document.getElementById("parametersContainer");
const paramsGrid = document.getElementById("paramsGrid");
const btnGenerateCad = document.getElementById("btnGenerateCad");
const editInput = document.getElementById("editInput");
const btnApplyEdit = document.getElementById("btnApplyEdit");
const buildOutput = document.getElementById("buildOutput");
const buildTimer = document.getElementById("buildTimer");
const viewportLoader = document.getElementById("viewportLoader");
const activeModelName = document.getElementById("activeModelName");
const dimX = document.getElementById("dimX");
const dimY = document.getElementById("dimY");
const dimZ = document.getElementById("dimZ");
const btnResetView = document.getElementById("btnResetView");
const btnToggleWireframe = document.getElementById("btnToggleWireframe");
const btnToggleGrid = document.getElementById("btnToggleGrid");
const materialSelector = document.getElementById("materialSelector");
const btnDownloadStl = document.getElementById("btnDownloadStl");
const btnDownloadStep = document.getElementById("btnDownloadStep");
const btnDownloadCode = document.getElementById("btnDownloadCode");
const projectHistoryList = document.getElementById("projectHistoryList");
const btnNewProject = document.getElementById("btnNewProject");
const btnLaunchViewer = document.getElementById("btnLaunchViewer");
const aiModelSelect = document.getElementById("aiModelSelect");
const dynamicPresetList = document.getElementById("dynamicPresetList");
const btnRefreshInspirations = document.getElementById("btnRefreshInspirations");

// Compile Error Modal & Diagnostics Elements
const compileErrorModal = document.getElementById("compileErrorModal");
const btnCloseErrorModal = document.getElementById("btnCloseErrorModal");
const btnCloseErrorModalBottom = document.getElementById("btnCloseErrorModalBottom");
const btnOpenErrorModal = document.getElementById("btnOpenErrorModal");
const errorModalTitle = document.getElementById("errorModalTitle");
const errorModalBadge = document.getElementById("errorModalBadge");
const errorModalWhy = document.getElementById("errorModalWhy");
const errorModalSolution = document.getElementById("errorModalSolution");
const errorModalRawLog = document.getElementById("errorModalRawLog");
const btnCopyErrorLog = document.getElementById("btnCopyErrorLog");
const btnCopyErrorLogText = document.getElementById("btnCopyErrorLogText");
const btnAutoFixCode = document.getElementById("btnAutoFixCode");

let lastErrorDiagnosis = null;
let lastErrorRawLog = "";

function showCompileErrorModal(diagnosis, rawLog) {
  if (!compileErrorModal) return;

  lastErrorDiagnosis = diagnosis;
  lastErrorRawLog = rawLog || (diagnosis && diagnosis.raw_log) || "";

  // Title
  if (diagnosis && diagnosis.title) {
    errorModalTitle.textContent = diagnosis.title;
  } else {
    errorModalTitle.textContent = "CAD Compilation Error";
  }

  // Category Badge
  if (diagnosis && diagnosis.category) {
    errorModalBadge.textContent = diagnosis.category;
    errorModalBadge.className = `error-badge ${diagnosis.badge_color || "error"}`;
  } else {
    errorModalBadge.textContent = "Compile Error";
    errorModalBadge.className = "error-badge error";
  }

  // Why this happened
  if (diagnosis && diagnosis.why) {
    errorModalWhy.textContent = diagnosis.why;
  } else {
    errorModalWhy.textContent = "The Python interpreter or OpenCASCADE geometric modeling kernel encountered an evaluation error.";
  }

  // Solution
  if (diagnosis && diagnosis.solution) {
    errorModalSolution.textContent = diagnosis.solution;
  } else {
    errorModalSolution.textContent = "Review the raw compiler output below to inspect the failing line, and ensure build123d API calls are valid.";
  }

  // Raw Traceback
  errorModalRawLog.textContent = lastErrorRawLog || "No traceback logs available.";

  // Show the header button in the compilation console
  if (btnOpenErrorModal) {
    btnOpenErrorModal.style.display = "inline-flex";
  }

  // Display modal popup
  compileErrorModal.style.display = "flex";
}

function hideCompileErrorModal() {
  if (compileErrorModal) compileErrorModal.style.display = "none";
}

// =============================================================================
// THREE.JS VIEWPORT INITIALIZATION
// =============================================================================

function initThreeViewport() {
  const container = document.getElementById("threeContainer");
  const width = container.clientWidth;
  const height = container.clientHeight;

  // Scene
  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0e131f);

  // Camera
  camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 2000);
  camera.position.set(100, 100, 120);

  // Renderer
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setSize(width, height);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  container.appendChild(renderer.domElement);

  // OrbitControls
  controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.05;
  controls.maxDistance = 1000;
  controls.minDistance = 5;

  // Lighting
  ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
  scene.add(ambientLight);

  dirLight = new THREE.DirectionalLight(0xffffff, 0.85);
  dirLight.position.set(120, 200, 150);
  dirLight.castShadow = true;
  dirLight.shadow.mapSize.width = 1024;
  dirLight.shadow.mapSize.height = 1024;
  scene.add(dirLight);

  const fillLight = new THREE.DirectionalLight(0x38bdf8, 0.4);
  fillLight.position.set(-100, -80, -100);
  scene.add(fillLight);

  // Ground Grid
  gridHelper = new THREE.GridHelper(300, 60, 0x00f2fe, 0x1e293b);
  gridHelper.position.y = 0;
  scene.add(gridHelper);

  // Render loop
  function animate() {
    requestAnimationFrame(animate);
    controls.update();
    renderer.render(scene, camera);
  }
  animate();

  // Resize handler
  window.addEventListener("resize", () => {
    const w = container.clientWidth;
    const h = container.clientHeight;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
  });
}

// Materials definition
function getMaterial(type, wireframe = false) {
  switch (type) {
    case "metallic":
      return new THREE.MeshStandardMaterial({
        color: 0xd1d5db,
        metalness: 0.85,
        roughness: 0.25,
        wireframe: wireframe,
      });
    case "orange":
      return new THREE.MeshStandardMaterial({
        color: 0xf97316,
        metalness: 0.1,
        roughness: 0.45,
        wireframe: wireframe,
      });
    case "clay":
      return new THREE.MeshLambertMaterial({
        color: 0xf1f5f9,
        wireframe: wireframe,
      });
    case "cadBlue":
    default:
      return new THREE.MeshStandardMaterial({
        color: 0x38bdf8,
        metalness: 0.3,
        roughness: 0.35,
        wireframe: wireframe,
      });
  }
}

// Load STL into scene
function loadStlModel(url) {
  if (!url) return;
  const fullUrl = (!url.startsWith("http") && API_BASE) ? API_BASE + url : url;
  viewportLoader.style.display = "flex";

  const loader = new THREE.STLLoader();
  loader.load(
    fullUrl,
    function (geometry) {
      if (currentStlMesh) {
        scene.remove(currentStlMesh);
        if (currentStlMesh.geometry) currentStlMesh.geometry.dispose();
      }

      geometry.computeVertexNormals();
      geometry.center();

      const mat = getMaterial(currentMaterialType, isWireframe);
      currentStlMesh = new THREE.Mesh(geometry, mat);
      currentStlMesh.castShadow = true;
      currentStlMesh.receiveShadow = true;

      // Compute bounding box dimensions
      geometry.computeBoundingBox();
      const bbox = geometry.boundingBox;
      const sizeX = (bbox.max.x - bbox.min.x).toFixed(1);
      const sizeY = (bbox.max.y - bbox.min.y).toFixed(1);
      const sizeZ = (bbox.max.z - bbox.min.z).toFixed(1);

      dimX.textContent = sizeX;
      dimY.textContent = sizeY;
      dimZ.textContent = sizeZ;

      // Place base of mesh on ground grid (Y=0)
      const height = bbox.max.y - bbox.min.y;
      currentStlMesh.position.y = height / 2;

      scene.add(currentStlMesh);

      // Adjust camera to fit mesh nicely
      const maxDim = Math.max(sizeX, sizeY, sizeZ);
      const dist = maxDim * 2.2;
      camera.position.set(dist * 0.8, dist * 0.9, dist * 1.1);
      controls.target.set(0, height / 2, 0);
      controls.update();

      viewportLoader.style.display = "none";
    },
    undefined,
    function (err) {
      console.error("Error loading STL:", err);
      viewportLoader.style.display = "none";
    }
  );
}

// =============================================================================
// API CALLS & WORKFLOWS
// =============================================================================

// Step 1: Polish Prompt with AI
async function handlePolishPrompt() {
  const prompt = promptInput.value.trim();
  if (!prompt) {
    alert("Please enter a prompt describing what you want to build.");
    return;
  }

  btnPolishPrompt.disabled = true;
  btnPolishPrompt.innerHTML = "Polishing...";

  try {
    const res = await fetch(`${API_BASE}/api/polish-prompt`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt: prompt,
        model: aiModelSelect ? aiModelSelect.value : null,
      }),
    });
    const data = await res.json();

    polishedSpecText.value = data.polished_spec;
    currentSpec = data.polished_spec;

    // Pre-populate default model name
    activeModelName.textContent = data.title || "Custom CAD Model";

    // Auto trigger code preparation
    cadCodeInput.value = "";
  } catch (err) {
    alert("Failed to polish prompt: " + err.message);
  } finally {
    btnPolishPrompt.disabled = false;
    btnPolishPrompt.innerHTML = `
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"></path></svg>
      Polish with AI`;
  }
}

// Step 2: Generate CAD & Compile
async function handleGenerateCad() {
  const prompt = promptInput.value.trim();
  const spec = polishedSpecText.value.trim();
  const code = cadCodeInput.value.trim();

  if (!prompt && !code) {
    alert("Please provide a prompt or code to build.");
    return;
  }

  btnGenerateCad.disabled = true;
  btnGenerateCad.innerHTML = "Processing with cadgen...";
  viewportLoader.style.display = "flex";
  buildOutput.textContent = "Compiling geometry with cadgen...\n";

  try {
    const res = await fetch(`${API_BASE}/api/generate-cad`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: currentProjectId,
        prompt: prompt || "Custom CAD Model",
        polished_spec: spec || "Generated from source code",
        code: code,
        parameters: currentParameters,
        model: aiModelSelect ? aiModelSelect.value : null,
      }),
    });
    const data = await res.json();

    currentProjectId = data.project_id;
    currentCode = data.code;
    cadCodeInput.value = data.code;
    currentParameters = data.parameters || {};

    buildOutput.textContent = data.build_log || "Build completed successfully.";
    buildTimer.textContent = `${data.elapsed}s`;

    if (data.success && data.stl_url) {
      loadStlModel(data.stl_url + "?t=" + Date.now());
      btnDownloadStl.disabled = false;
      btnDownloadStep.disabled = !data.step_url;
      btnDownloadCode.disabled = false;
      if (window.innerWidth <= 1024) switchMobileTab("viewport");

      // If an error occurred but was self-healed, keep diagnostic button available in console
      if (data.error_diagnosis) {
        lastErrorDiagnosis = data.error_diagnosis;
        lastErrorRawLog = data.build_log || "";
        if (btnOpenErrorModal) btnOpenErrorModal.style.display = "inline-flex";
      } else {
        if (btnOpenErrorModal) btnOpenErrorModal.style.display = "none";
      }
    } else {
      viewportLoader.style.display = "none";
      // Show rich compilation error diagnostic modal popup
      showCompileErrorModal(data.error_diagnosis, data.build_log);
    }

    renderParameterControls(currentParameters);
    loadProjectHistory();
  } catch (err) {
    viewportLoader.style.display = "none";
    buildOutput.textContent = "Network/execution error: " + err.message;
    showCompileErrorModal({
      category: "Network / Server Error",
      badge_color: "error",
      title: "API Connection Failed",
      why: `The browser could not communicate with the CAD server (${API_BASE}). This typically occurs if the backend container is spinning up from cold sleep (on free cloud tiers) or if network connectivity is interrupted.`,
      solution: "1. Please wait 15-30 seconds for the backend to wake up.\n2. Click 'Process & Generate 3D Model' again to re-attempt."
    }, err.stack || err.message);
  } finally {
    btnGenerateCad.disabled = false;
    btnGenerateCad.innerHTML = `
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
      Process & Generate 3D Model`;
  }
}

// Step 3: Conversational Edit on Existing Model
async function handleApplyEdit() {
  const instruction = editInput.value.trim();
  if (!instruction) return;
  if (!currentProjectId) {
    showCompileErrorModal({
      category: "Action Required",
      badge_color: "warning",
      title: "No Active CAD Model",
      why: "You attempted to apply an edit, but no CAD model has been generated or selected yet.",
      solution: "Generate a 3D model first using Step 1 & Step 2 above, or select an existing design from the Saved Parts list."
    }, "No active project loaded.");
    return;
  }

  btnApplyEdit.disabled = true;
  btnApplyEdit.textContent = "Applying...";
  viewportLoader.style.display = "flex";

  try {
    const res = await fetch(`${API_BASE}/api/edit-cad`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: currentProjectId,
        edit_instruction: instruction,
        current_code: cadCodeInput.value || currentCode,
        current_spec: polishedSpecText.value || currentSpec,
        model: aiModelSelect ? aiModelSelect.value : null,
      }),
    });
    const data = await res.json();

    currentCode = data.code;
    cadCodeInput.value = data.code;
    currentParameters = data.parameters || {};
    buildOutput.textContent = data.build_log || "Edit applied and rebuilt.";
    buildTimer.textContent = `${data.elapsed}s`;

    if (data.success && data.stl_url) {
      loadStlModel(data.stl_url + "?t=" + Date.now());
      if (data.error_diagnosis) {
        lastErrorDiagnosis = data.error_diagnosis;
        lastErrorRawLog = data.build_log || "";
        if (btnOpenErrorModal) btnOpenErrorModal.style.display = "inline-flex";
      } else {
        if (btnOpenErrorModal) btnOpenErrorModal.style.display = "none";
      }
    } else {
      viewportLoader.style.display = "none";
      showCompileErrorModal(data.error_diagnosis, data.build_log);
    }

    renderParameterControls(currentParameters);
    editInput.value = "";
    loadProjectHistory();
  } catch (err) {
    viewportLoader.style.display = "none";
    showCompileErrorModal({
      category: "Edit Evaluation Error",
      badge_color: "error",
      title: "Failed to Apply Conversational Edit",
      why: `An exception occurred during edit synthesis or compilation: ${err.message}`,
      solution: "Ensure your edit prompt includes clear dimensions (e.g. 'Increase wall thickness to 5mm') and verify backend availability."
    }, err.stack || err.message);
  } finally {
    btnApplyEdit.disabled = false;
    btnApplyEdit.innerHTML = `
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"></path><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path></svg>
      Apply Edit`;
  }
}

// Render dynamic parameter sliders
function renderParameterControls(params) {
  paramsGrid.innerHTML = "";
  const keys = Object.keys(params);

  if (keys.length === 0) {
    parametersContainer.style.display = "none";
    return;
  }

  parametersContainer.style.display = "block";

  keys.forEach((key) => {
    const val = params[key];
    const item = document.createElement("div");
    item.className = "param-control";
    item.innerHTML = `
      <label>${key}</label>
      <input type="number" step="any" value="${val}" data-param="${key}">
    `;

    const input = item.querySelector("input");
    input.addEventListener("change", (e) => {
      currentParameters[key] = parseFloat(e.target.value);
      handleGenerateCad();
    });

    paramsGrid.appendChild(item);
  });
}

// Load Project History
async function loadProjectHistory() {
  try {
    const res = await fetch(`${API_BASE}/api/projects`);
    const projects = await res.json();

    if (!projects || projects.length === 0) {
      projectHistoryList.innerHTML = `<div class="empty-state">No saved designs yet</div>`;
      return;
    }

    projectHistoryList.innerHTML = "";
    projects.forEach((proj) => {
      const el = document.createElement("div");
      el.className = `history-item ${proj.id === currentProjectId ? "active" : ""}`;
      const timeStr = new Date(proj.created_at * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      el.innerHTML = `
        <div class="history-item-top">
          <div class="history-item-title" title="${proj.title}">${proj.title}</div>
          <button class="btn-delete-part" title="Delete part & all 3D files" aria-label="Delete part">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
          </button>
        </div>
        <div class="history-item-meta">
          <span>${proj.id}</span>
          <span>${timeStr}</span>
        </div>
      `;

      // Click to load project
      el.addEventListener("click", () => selectProject(proj.id));

      // Click to delete project immediately with smooth feedback
      const deleteBtn = el.querySelector(".btn-delete-part");
      if (deleteBtn) {
        deleteBtn.addEventListener("click", async (e) => {
          e.preventDefault();
          e.stopPropagation();
          el.style.transition = "all 0.2s ease";
          el.style.opacity = "0.2";
          el.style.transform = "translateX(-8px)";
          await deleteProject(proj.id);
        });
      }

      projectHistoryList.appendChild(el);
    });
  } catch (err) {
    console.error("Failed to load history:", err);
  }
}

// Delete a project completely
async function deleteProject(id) {
  try {
    const res = await fetch(`${API_BASE}/api/project/${id}`, { method: "DELETE" });
    const data = await res.json();
    if (res.ok && data.success) {
      if (currentProjectId === id) {
        startNewProject();
      } else {
        await loadProjectHistory();
      }
    } else {
      console.warn("Failed to delete project:", data);
      await loadProjectHistory();
    }
  } catch (err) {
    console.error("Error deleting project:", err);
    await loadProjectHistory();
  }
}

// Clear all past projects
const btnClearAllHistory = document.getElementById("btnClearAllHistory");
if (btnClearAllHistory) {
  btnClearAllHistory.addEventListener("click", async () => {
    try {
      btnClearAllHistory.disabled = true;
      btnClearAllHistory.textContent = "Clearing...";
      await fetch(`${API_BASE}/api/projects`, { method: "DELETE" });
      startNewProject();
    } catch (err) {
      console.error("Failed to clear history:", err);
    } finally {
      btnClearAllHistory.disabled = false;
      btnClearAllHistory.textContent = "Clear All";
    }
  });
}

// Select and load a project from history
async function selectProject(id) {
  try {
    const res = await fetch(`${API_BASE}/api/project/${id}`);
    const data = await res.json();

    currentProjectId = data.id;
    promptInput.value = data.prompt || "";
    polishedSpecText.value = data.polished_spec || "";
    currentSpec = data.polished_spec || "";
    currentCode = data.code || "";
    cadCodeInput.value = data.code || "";
    currentParameters = data.parameters || {};
    activeModelName.textContent = data.title || id;

    renderParameterControls(currentParameters);

    if (data.stl_url) {
      loadStlModel(data.stl_url + "?t=" + Date.now());
      btnDownloadStl.disabled = false;
      btnDownloadStep.disabled = !data.step_url;
      btnDownloadCode.disabled = false;
      if (window.innerWidth <= 1024) switchMobileTab("viewport");
    }

    loadProjectHistory();
  } catch (err) {
    alert("Failed to load project: " + err.message);
  }
}

// Reset / New Project
function startNewProject() {
  currentProjectId = null;
  currentCode = "";
  currentSpec = "";
  currentParameters = {};

  promptInput.value = "";
  polishedSpecText.value = "";
  cadCodeInput.value = "";
  paramsGrid.innerHTML = "";
  parametersContainer.style.display = "none";
  activeModelName.textContent = "New Model";

  if (currentStlMesh) {
    scene.remove(currentStlMesh);
    currentStlMesh = null;
  }

  dimX.textContent = "-";
  dimY.textContent = "-";
  dimZ.textContent = "-";

  btnDownloadStl.disabled = true;
  btnDownloadStep.disabled = true;
  btnDownloadCode.disabled = true;

  loadProjectHistory();
}

// =============================================================================
// EVENT LISTENERS & SETUP
// =============================================================================

btnPolishPrompt.addEventListener("click", handlePolishPrompt);
btnGenerateCad.addEventListener("click", handleGenerateCad);
btnApplyEdit.addEventListener("click", handleApplyEdit);
btnNewProject.addEventListener("click", startNewProject);

editInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") handleApplyEdit();
});

btnToggleCodeView.addEventListener("click", () => {
  const isHidden = codeEditorWrapper.style.display === "none";
  codeEditorWrapper.style.display = isHidden ? "block" : "none";
  btnToggleCodeView.textContent = isHidden ? "Hide Python Code" : "Show Python Code";
});

// Dynamic AI Models & Inspiration Loader
async function loadDynamicModels() {
  if (!aiModelSelect) return;
  try {
    const res = await fetch(`${API_BASE}/api/models`);
    const data = await res.json();
    if (data.models && data.models.length > 0) {
      aiModelSelect.innerHTML = "";
      data.models.forEach((m) => {
        const opt = document.createElement("option");
        opt.value = m.id;
        opt.textContent = `${m.name} (${m.provider})`;
        if (m.id === data.active_model) opt.selected = true;
        aiModelSelect.appendChild(opt);
      });
    }
  } catch (err) {
    console.warn("Could not fetch dynamic models:", err);
  }
}

const INITIAL_INSPIRATIONS = [
  {
    title: "Action Cam Mount",
    prompt: "Action camera three-prong mounting bracket with ergonomic handle grip and 1/4-20 tripod adapter"
  },
  {
    title: "Linear Bearing Block",
    prompt: "SC8UU 8mm linear ball bearing pillow block with 4 M4 mounting threads and lightweight skeleton cutout"
  },
  {
    title: "Drone Motor Arm",
    prompt: "Carbon-compatible quadcopter motor arm for 2207 brushless motor with wire routing and 16x19mm M3 pattern"
  }
];

function renderInspirations(ideasList) {
  if (!dynamicPresetList) return;
  dynamicPresetList.innerHTML = "";
  // Display only 3 items
  const threeIdeas = (ideasList || []).slice(0, 3);
  threeIdeas.forEach((idea) => {
    const pill = document.createElement("button");
    pill.type = "button";
    pill.className = "preset-pill";
    pill.textContent = idea.title || idea.label || "Design Idea";
    pill.title = idea.prompt;
    pill.addEventListener("click", () => {
      promptInput.value = idea.prompt;
      handlePolishPrompt();
    });
    dynamicPresetList.appendChild(pill);
  });
}

// Loads existing inspirations from localStorage or defaults on visit (does NOT make API requests on page load)
function initInspirations() {
  const cached = localStorage.getItem("text_to_cad_inspirations");
  if (cached) {
    try {
      const parsed = JSON.parse(cached);
      if (Array.isArray(parsed) && parsed.length > 0) {
        renderInspirations(parsed);
        return;
      }
    } catch (e) {
      console.warn("Could not parse cached inspirations:", e);
    }
  }
  renderInspirations(INITIAL_INSPIRATIONS);
  localStorage.setItem("text_to_cad_inspirations", JSON.stringify(INITIAL_INSPIRATIONS));
}

// ONLY called when the user explicitly clicks the "✨ New Ideas" button
async function fetchNewInspirations() {
  if (!dynamicPresetList || !btnRefreshInspirations) return;

  btnRefreshInspirations.disabled = true;
  const originalHtml = btnRefreshInspirations.innerHTML;
  btnRefreshInspirations.innerHTML = "⏳ Thinking...";
  dynamicPresetList.innerHTML = `<span style="font-size:0.75rem; color:var(--text-muted); padding:4px 0;">Generating 3 unique ideas...</span>`;

  try {
    const res = await fetch(`${API_BASE}/api/inspire`);
    const data = await res.json();
    const ideas = (data.ideas || data.presets || []).slice(0, 3);
    if (ideas.length > 0) {
      localStorage.setItem("text_to_cad_inspirations", JSON.stringify(ideas));
      renderInspirations(ideas);
    } else {
      initInspirations();
    }
  } catch (err) {
    console.warn("Could not fetch unique inspirations:", err);
    initInspirations();
  } finally {
    btnRefreshInspirations.disabled = false;
    btnRefreshInspirations.innerHTML = originalHtml;
  }
}

if (btnRefreshInspirations) {
  btnRefreshInspirations.addEventListener("click", fetchNewInspirations);
}

// Viewport Controls
btnResetView.addEventListener("click", () => {
  if (currentStlMesh) {
    camera.position.set(100, 100, 120);
    controls.target.set(0, currentStlMesh.position.y, 0);
    controls.update();
  }
});

btnToggleWireframe.addEventListener("click", () => {
  isWireframe = !isWireframe;
  btnToggleWireframe.classList.toggle("active", isWireframe);
  if (currentStlMesh) {
    currentStlMesh.material = getMaterial(currentMaterialType, isWireframe);
  }
});

btnToggleGrid.addEventListener("click", () => {
  gridHelper.visible = !gridHelper.visible;
  btnToggleGrid.classList.toggle("active", !gridHelper.visible);
});

materialSelector.addEventListener("change", (e) => {
  currentMaterialType = e.target.value;
  if (currentStlMesh) {
    currentStlMesh.material = getMaterial(currentMaterialType, isWireframe);
  }
});

// Downloads
btnDownloadStl.addEventListener("click", () => {
  if (currentProjectId) window.open(`${API_BASE}/api/download/${currentProjectId}/stl`, "_blank");
});
btnDownloadStep.addEventListener("click", () => {
  if (currentProjectId) window.open(`${API_BASE}/api/download/${currentProjectId}/step`, "_blank");
});
btnDownloadCode.addEventListener("click", () => {
  if (currentProjectId) window.open(`${API_BASE}/api/download/${currentProjectId}/py`, "_blank");
});

// Deployment Modal
const deployModal = document.getElementById("deployModal");
const btnDeployModal = document.getElementById("btnDeployModal");
const btnCloseDeployModal = document.getElementById("btnCloseDeployModal");

if (btnDeployModal && deployModal) {
  btnDeployModal.addEventListener("click", () => {
    deployModal.style.display = "flex";
  });
}

if (btnCloseDeployModal && deployModal) {
  btnCloseDeployModal.addEventListener("click", () => {
    deployModal.style.display = "none";
  });
  deployModal.addEventListener("click", (e) => {
    if (e.target === deployModal) deployModal.style.display = "none";
  });
}

// Compile Error Diagnostics Modal Listeners
if (btnCloseErrorModal) {
  btnCloseErrorModal.addEventListener("click", hideCompileErrorModal);
}
if (btnCloseErrorModalBottom) {
  btnCloseErrorModalBottom.addEventListener("click", hideCompileErrorModal);
}
if (compileErrorModal) {
  compileErrorModal.addEventListener("click", (e) => {
    if (e.target === compileErrorModal) hideCompileErrorModal();
  });
}
if (btnOpenErrorModal) {
  btnOpenErrorModal.addEventListener("click", () => {
    showCompileErrorModal(lastErrorDiagnosis, lastErrorRawLog);
  });
}
if (btnCopyErrorLog && btnCopyErrorLogText) {
  btnCopyErrorLog.addEventListener("click", () => {
    const textToCopy = lastErrorRawLog || (errorModalRawLog ? errorModalRawLog.textContent : "") || "";
    navigator.clipboard.writeText(textToCopy).then(() => {
      btnCopyErrorLogText.textContent = "Copied!";
      setTimeout(() => {
        btnCopyErrorLogText.textContent = "Copy Traceback";
      }, 2000);
    }).catch((err) => {
      console.warn("Could not copy traceback:", err);
    });
  });
}
if (btnAutoFixCode) {
  btnAutoFixCode.addEventListener("click", () => {
    hideCompileErrorModal();
    const diagTitle = (lastErrorDiagnosis && lastErrorDiagnosis.title) || "compiler error";
    editInput.value = `Fix CAD compiler error: ${diagTitle}. Ensure valid build123d geometry and clean ASCII Python syntax with standard straight quotes.`;
    handleApplyEdit();
  });
}

// Mobile Navigation Tab Switcher
const mobileTabs = document.querySelectorAll(".mobile-tab-btn");
const sidebarPanel = document.getElementById("sidebarPanel");
const editorPanel = document.getElementById("editorPanel");
const viewportPanel = document.getElementById("viewportPanel");

function switchMobileTab(tabName) {
  mobileTabs.forEach((btn) => {
    btn.classList.toggle("active", btn.getAttribute("data-tab") === tabName);
  });

  if (sidebarPanel) sidebarPanel.classList.toggle("mobile-active", tabName === "sidebar");
  if (editorPanel) editorPanel.classList.toggle("mobile-active", tabName === "editor");
  if (viewportPanel) {
    viewportPanel.classList.toggle("mobile-active", tabName === "viewport");
    if (tabName === "viewport") {
      // Trigger canvas resize
      setTimeout(() => {
        const container = document.getElementById("threeContainer");
        if (container && renderer && camera) {
          const w = container.clientWidth;
          const h = container.clientHeight;
          camera.aspect = w / h;
          camera.updateProjectionMatrix();
          renderer.setSize(w, h);
        }
      }, 50);
    }
  }
}

mobileTabs.forEach((btn) => {
  btn.addEventListener("click", () => {
    switchMobileTab(btn.getAttribute("data-tab"));
  });
});

// Check backend Groq config
async function checkEngineConfig() {
  try {
    const res = await fetch(`${API_BASE}/api/config`);
    const data = await res.json();
    const badge = document.getElementById("groqStatusBadge");
    if (badge && data.groq_configured) {
      badge.innerHTML = `<span class="status-dot groq-dot"></span> Groq AI Connected (${data.groq_model})`;
    }
  } catch (e) {
    console.error("Config check failed:", e);
  }
}

// Initialize on page load
window.addEventListener("DOMContentLoaded", () => {
  initThreeViewport();
  loadProjectHistory();
  checkEngineConfig();
  loadDynamicModels();
  initInspirations();
  switchMobileTab("editor"); // Default to editor view on mobile
});

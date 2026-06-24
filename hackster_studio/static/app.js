document.addEventListener("click", async (event) => {
  const closeGenerationButton = event.target.closest("[data-book-generation-close]");
  if (closeGenerationButton) {
    closeBookGenerationDialog();
    return;
  }

  const reopenGenerationButton = event.target.closest("[data-book-generation-reopen]");
  if (reopenGenerationButton) {
    reopenBookGenerationDialog();
    return;
  }

  const toggleLogButton = event.target.closest("[data-book-generation-log-toggle]");
  if (toggleLogButton) {
    toggleBookGenerationLog(toggleLogButton);
    return;
  }

  const selectAllCharacterImages = event.target.closest("[data-character-select-all]");
  if (selectAllCharacterImages) {
    updateCharacterImageSelection(selectAllCharacterImages.closest("[data-character-auto-selection]"), true);
    return;
  }

  const clearCharacterImages = event.target.closest("[data-character-clear-selection]");
  if (clearCharacterImages) {
    updateCharacterImageSelection(clearCharacterImages.closest("[data-character-auto-selection]"), false);
    return;
  }

  const button = event.target.closest("[data-copy]");
  if (!button) return;

  const target = document.querySelector(button.dataset.copy);
  if (!target) return;

  await navigator.clipboard.writeText(target.innerText);
  const original = button.innerText;
  button.innerText = "Copied";
  setTimeout(() => { button.innerText = original; }, 1200);
});

document.addEventListener("DOMContentLoaded", () => {
  refreshGenerationJobForms();
});

document.addEventListener("change", (event) => {
  const checkbox = event.target.closest("[data-character-auto-selection] input[type='checkbox'][name='selected_images']");
  if (!checkbox) return;

  const form = checkbox.closest("[data-character-auto-selection]");
  const card = checkbox.closest(".character-example-card");
  if (card) card.classList.toggle("is-selected", checkbox.checked);
  queueCharacterSelectionAutomation(form);
});

document.addEventListener("submit", (event) => {
  // "Process Selected Set Now" — submit via fetch and show server feedback,
  // instead of a silent full-page POST→redirect. Delete buttons (which carry a
  // formaction) are not data-character-process, so they fall through to a
  // normal submit.
  const characterForm = event.target.closest("[data-character-auto-selection]");
  const isProcess = event.submitter && event.submitter.matches && event.submitter.matches("[data-character-process]");
  if (characterForm && isProcess) {
    event.preventDefault();
    const submitter = event.submitter;
    const original = submitter ? submitter.textContent : "";
    if (submitter) { submitter.disabled = true; submitter.textContent = "Processing..."; }
    submitCharacterSelectionAutomation(characterForm).finally(() => {
      if (submitter) { submitter.disabled = false; submitter.textContent = original; }
    });
    return;
  }

  const generationJobForm = event.target.closest("[data-generation-job-form]");
  if (generationJobForm) {
    event.preventDefault();
    const submitter = event.submitter;
    const status = generationJobForm.querySelector("[data-generation-job-status]");
    const activeJobId = generationJobForm.dataset.activeJobId || "";
    if (activeJobId) {
      if (status) {
        status.hidden = false;
        status.textContent = "Opening the current book generation run.";
      }
      if (submitter) submitter.textContent = "Viewing...";
      showBookGenerationProgress({ message: "Browser: opening the current book generation run." });
      appendBookGenerationLog(`Browser: reopening active book generation job ${activeJobId}.`);
      startBookGenerationJobPolling(activeJobId, generationJobForm.dataset.activeRedirectUrl || "");
      setTimeout(() => {
        if (submitter) submitter.textContent = "View Current Book Generation";
      }, 800);
      return;
    }

    const jobKind = generationJobForm.dataset.generationJobKind || "resume";
    const startingMessage = jobKind === "characters" || jobKind === "character_reference"
      ? "Started. Generating character reference pack."
      : "Started. Resuming from the current book state.";
    const workingLabel = jobKind === "characters" || jobKind === "character_reference" ? "Generating pack..." : "Resuming...";
    if (status) {
      status.hidden = false;
      status.textContent = startingMessage;
    }
    generationJobForm.querySelectorAll("button").forEach((button) => {
      button.disabled = true;
    });
    if (submitter) submitter.textContent = workingLabel;
    showBookGenerationProgress({ message: `Browser: ${startingMessage}` });
    submitDgxPlannerForm(generationJobForm);
    return;
  }

  const form = event.target.closest("[data-planner-form]");
  if (!form) return;

  const submitter = event.submitter;
  const engine = submitter && submitter.name === "planner_engine" ? submitter.value : "";
  preserveSubmitterValue(form, submitter);

  const status = form.querySelector("[data-planner-status]");
  const message = engine === "dgx"
    ? "Started. DGX is generating the book plan now."
    : "Saving book details.";

  if (status) {
    status.hidden = false;
    status.textContent = message;
  }

  form.querySelectorAll("button").forEach((button) => {
    button.disabled = true;
  });
  if (submitter) {
    submitter.textContent = engine === "dgx" ? "Generating with DGX..." : "Working...";
  }

  if (engine === "dgx") {
    event.preventDefault();
    showBookGenerationProgress();
    submitDgxPlannerForm(form);
  }
});

function queueCharacterSelectionAutomation(form) {
  if (!form) return;
  const status = form.querySelector("[data-character-auto-selection-status]");
  const selectedCount = form.querySelectorAll("input[name='selected_images']:checked").length;
  if (status) {
    status.hidden = false;
    status.textContent = `Saving ${selectedCount} selected examples and refreshing LoRA prep...`;
  }
  window.clearTimeout(form._characterSelectionTimer);
  form._characterSelectionTimer = window.setTimeout(() => {
    submitCharacterSelectionAutomation(form);
  }, 700);
}

function updateCharacterImageSelection(form, checked) {
  if (!form) return;
  const checkboxes = Array.from(form.querySelectorAll("input[type='checkbox'][name='selected_images']"));
  checkboxes.forEach((checkbox) => {
    checkbox.checked = checked;
    const card = checkbox.closest(".character-example-card");
    if (card) card.classList.toggle("is-selected", checked);
  });
  const status = form.querySelector("[data-character-auto-selection-status]");
  if (status) {
    status.hidden = false;
    status.textContent = checked
      ? `Selected ${checkboxes.length} character images.`
      : "Selection cleared.";
  }
}

async function submitCharacterSelectionAutomation(form) {
  const status = form.querySelector("[data-character-auto-selection-status]");
  try {
    const response = await fetch(form.action, {
      method: form.method || "POST",
      body: new FormData(form),
      headers: { "X-Requested-With": "fetch" },
      redirect: "follow",
    });
    if (!response.ok) {
      if (status) { status.hidden = false; status.textContent = `Could not save selection: HTTP ${response.status}`; }
      return;
    }
    let payload = null;
    try { payload = await response.json(); } catch (_error) { payload = null; }
    updateCharacterTrainingBanner(payload);
    if (status) {
      status.hidden = false;
      status.textContent = (payload && payload.message)
        || "Selection saved. Dataset and training request refreshed.";
    }
  } catch (error) {
    if (status) { status.hidden = false; status.textContent = `Could not save selection: ${error}`; }
  }
}

function updateCharacterTrainingBanner(payload) {
  if (!payload) return;
  const titleCase = (text) => String(text).replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  const state = document.querySelector("[data-character-training-banner] [data-training-state]");
  const count = document.querySelector("[data-character-training-banner] [data-training-count]");
  const message = document.querySelector("[data-character-training-banner] [data-training-message]");
  if (state && payload.status) state.textContent = titleCase(payload.status);
  if (count && typeof payload.selected_count === "number") count.textContent = payload.selected_count;
  if (message) {
    if (payload.message) { message.textContent = payload.message; message.hidden = false; }
    else { message.hidden = true; }
  }
}

function preserveSubmitterValue(form, submitter) {
  if (!submitter || !submitter.name || !submitter.value) return;

  const existing = form.querySelector("input[data-submit-proxy]");
  if (existing) existing.remove();

  const proxy = document.createElement("input");
  proxy.type = "hidden";
  proxy.name = submitter.name;
  proxy.value = submitter.value;
  proxy.dataset.submitProxy = "true";
  form.appendChild(proxy);
}

async function refreshGenerationJobForms() {
  const forms = Array.from(document.querySelectorAll("[data-generation-job-form]"));
  if (!forms.length) return;

  const activeByBook = new Map();
  const sessionBookSlug = forms[0]?.dataset.bookGenerationBookSlug || "";
  if (window.bookGenerationJobId && sessionBookSlug && !window.bookGenerationProgress?.complete) {
    activeByBook.set(sessionBookSlug, {
      job_id: window.bookGenerationJobId,
      book_slug: sessionBookSlug,
      redirect_url: window.bookGenerationRedirectUrl || "",
      status: "running",
      stage: "browser_session",
    });
  }

  try {
    const response = await fetch(`/api/book-generation/jobs?ts=${Date.now()}`, {
      cache: "no-store",
      headers: { "Accept": "application/json" },
    });
    if (response.ok) {
      const payload = await response.json();
      (payload.jobs || []).forEach((job) => {
        if (!["queued", "running"].includes(job.status)) return;
        if (!activeByBook.has(job.book_slug)) activeByBook.set(job.book_slug, job);
      });
    }
  } catch {
    // The form can still use any job already known in this browser session.
  }

  forms.forEach((form) => {
    const activeJob = activeByBook.get(form.dataset.bookGenerationBookSlug || "");
    if (activeJob && ["queued", "running"].includes(activeJob.status)) {
      setGenerationJobFormActive(form, activeJob);
    } else {
      setGenerationJobFormResume(form);
    }
  });
}

function findGenerationJobForm(bookSlug) {
  const forms = Array.from(document.querySelectorAll("[data-generation-job-form]"));
  if (!bookSlug) return forms[0] || null;
  return forms.find((form) => form.dataset.bookGenerationBookSlug === bookSlug) || null;
}

function setGenerationJobFormActive(form, job) {
  form.dataset.activeJobId = job.job_id || "";
  form.dataset.activeRedirectUrl = job.redirect_url || `/workflow?book_slug=${job.book_slug || form.dataset.bookGenerationBookSlug || ""}`;
  const title = form.querySelector("[data-generation-job-title]");
  const detail = form.querySelector("[data-generation-job-detail]");
  const submit = form.querySelector("[data-generation-job-submit]");
  const status = form.querySelector("[data-generation-job-status]");
  if (title) title.textContent = "Current Book Generation";
  if (detail) {
    detail.textContent = `A ${job.status || "running"} generation run is already active for this book. Open it to watch progress instead of starting another resume.`;
  }
  if (submit) {
    submit.textContent = "View Current Book Generation";
    submit.disabled = false;
  }
  if (status) {
    status.hidden = false;
    status.textContent = `Current job: ${(job.job_id || "").slice(0, 8)} · ${job.stage || job.status || "running"}`;
  }
}

function setGenerationJobFormResume(form) {
  delete form.dataset.activeJobId;
  delete form.dataset.activeRedirectUrl;
  const title = form.querySelector("[data-generation-job-title]");
  const detail = form.querySelector("[data-generation-job-detail]");
  const submit = form.querySelector("[data-generation-job-submit]");
  const status = form.querySelector("[data-generation-job-status]");
  const jobKind = form.dataset.generationJobKind || "resume";
  const isCharacterReference = jobKind === "character_reference";
  if (title) title.textContent = isCharacterReference ? "Generate Reference Pack" : "Resume Existing Run";
  if (detail) {
    detail.textContent = isCharacterReference
      ? "Generate turnarounds, expressions, poses, manifest, and QA files for this character."
      : "Continue from the current planned pages, prompts, and finished illustrations. This skips DGX story planning and starts at the first missing image.";
  }
  if (submit) {
    submit.textContent = isCharacterReference ? "Generate Reference Pack" : (jobKind === "characters" ? "Generate Character Packs" : "Resume From Current State");
    submit.disabled = false;
  }
  if (status) {
    status.hidden = true;
    status.textContent = "";
  }
}

function showBookGenerationProgress(options = {}) {
  const overlay = ensureBookGenerationOverlay();
  const stepList = overlay.querySelector("[data-book-generation-steps]");
  const steps = bookGenerationSteps();

  stopBookGenerationJobPolling();
  overlay.hidden = false;
  setBookGenerationReopenVisible(false);
  setBookGenerationOpenLink("");
  document.body.classList.add("is-generating-book");
  stepList.innerHTML = steps.map(([label], index) => (
    `<li class="${index === 0 ? "is-active" : ""}">${label}</li>`
  )).join("");

  window.bookGenerationProgress = { stageIndex: 0, progress: 3, complete: false };
  setBookGenerationStage(0, { progress: 3 });
  resetBookGenerationLog();
  appendBookGenerationLog(options.message || "Browser: DGX generation request started.");
  startDgxLogPolling();

  window.clearInterval(window.bookGenerationProgressTimer);
  window.bookGenerationProgressTimer = window.setInterval(nudgeBookGenerationProgress, 650);
}

async function submitDgxPlannerForm(form) {
  appendBookGenerationLog(`Browser: submitting ${form.action}`);
  setBookGenerationStage(0, { progress: 6 });
  try {
    const response = await fetch(form.action, {
      method: form.method || "POST",
      body: new FormData(form),
      headers: { "X-Requested-With": "fetch" },
      redirect: "follow",
    });
    if (!response.ok) {
      const body = await response.text();
      appendBookGenerationLog(`Browser: request failed with HTTP ${response.status}.`);
      appendBookGenerationLog(body.slice(0, 1200) || "No response body returned.");
      setBookGenerationFailed(`Request failed with HTTP ${response.status}.`);
      stopDgxLogPolling();
      return;
    }

    const payload = await readJsonResponse(response);
    if (payload && payload.job_id) {
      appendBookGenerationLog(`Browser: backend job accepted: ${payload.job_id}`);
      const jobForm = findGenerationJobForm(payload.book_slug) || form.closest("[data-generation-job-form]");
      if (jobForm) setGenerationJobFormActive(jobForm, payload);
      updateBookGenerationStageFromJob(payload);
      startBookGenerationJobPolling(payload.job_id, payload.redirect_url || response.url || form.action);
      return;
    }

    setBookGenerationStage(5, { progress: 96 });
    setBookGenerationComplete();
    appendBookGenerationLog("Browser: DGX planner finished. Opening the generated book page.");
    window.location.href = response.url || form.action;
  } catch (error) {
    appendBookGenerationLog(`Browser: request failed before completion: ${error}`);
    setBookGenerationFailed(String(error));
    stopDgxLogPolling();
  }
}

async function readJsonResponse(response) {
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) return null;
  try {
    return await response.json();
  } catch (error) {
    appendBookGenerationLog(`Browser: could not parse JSON response: ${error}`);
    return null;
  }
}

function setBookGenerationComplete(options = {}) {
  window.bookGenerationProgress = window.bookGenerationProgress || {};
  window.bookGenerationProgress.complete = true;
  setBookGenerationStage(9, { progress: 100, allowBackwards: true, detail: options.detail });
  stopBookGenerationJobPolling();
  stopDgxLogPolling();
  setBookGenerationReopenVisible(false);
}

function setBookGenerationFailed(message) {
  const overlay = ensureBookGenerationOverlay();
  window.bookGenerationProgress = window.bookGenerationProgress || {};
  window.bookGenerationProgress.complete = true;
  overlay.querySelector("[data-book-generation-title]").textContent = "Generation failed";
  overlay.querySelector("[data-book-generation-detail]").textContent = message || "The submitted book generation request failed.";
  stopBookGenerationJobPolling();
  if (overlay.hidden) setBookGenerationReopenVisible(true, "Generation Failed");
}

function bookGenerationSteps() {
  return [
    ["Request accepted", "Hackster Studio accepted this exact generation request.", 6],
    ["DGX planner", "Preparing the local planner for this request.", 14],
    ["Story layout", "DGX is writing the structured story and page plan.", 26],
    ["Pages and prompts", "Pages, prompts, and page specs are being created.", 36],
    ["Character gate", "Character turnarounds, expressions, poses, manifests, and QA reports are being prepared.", 45],
    ["Images", "ComfyUI is generating production page images.", 86],
    ["Review package", "Review files and validation reports are being written.", 91],
    ["Print exports", "Draft PDF, Lulu PDF, and Affinity files are being built.", 97],
    ["Production reports", "Build reports and checklists are being finalized.", 99],
    ["Complete", "Final artifact check passed.", 100],
  ];
}

function setBookGenerationStage(stageIndex, options = {}) {
  const overlay = ensureBookGenerationOverlay();
  const fill = overlay.querySelector("[data-book-generation-fill]");
  const percent = overlay.querySelector("[data-book-generation-percent]");
  const title = overlay.querySelector("[data-book-generation-title]");
  const detail = overlay.querySelector("[data-book-generation-detail]");
  const stepList = overlay.querySelector("[data-book-generation-steps]");
  const steps = bookGenerationSteps();
  const state = window.bookGenerationProgress || { stageIndex: 0, progress: 0, complete: false };

  if (!options.allowBackwards && stageIndex < state.stageIndex) return;
  state.stageIndex = Math.max(0, Math.min(stageIndex, steps.length - 1));
  if (typeof options.progress === "number") {
    state.progress = Math.max(state.progress || 0, options.progress);
  }
  const [, , cap] = steps[state.stageIndex];
  state.progress = Math.min(state.progress || 0, cap);
  window.bookGenerationProgress = state;

  const [label, stepDetail] = steps[state.stageIndex];
  title.textContent = label;
  detail.textContent = options.detail || stepDetail;
  fill.style.width = `${Math.round(state.progress)}%`;
  percent.textContent = `${Math.round(state.progress)}%`;
  stepList.querySelectorAll("li").forEach((item, index) => {
    item.classList.toggle("is-complete", index < state.stageIndex);
    item.classList.toggle("is-active", index === state.stageIndex);
  });
}

function nudgeBookGenerationProgress() {
  const state = window.bookGenerationProgress;
  if (!state || state.complete) return;
  const steps = bookGenerationSteps();
  const cap = steps[state.stageIndex][2];
  state.progress += Math.max(0.05, (cap - state.progress) * 0.018);
  state.progress = Math.min(state.progress, cap);
  setBookGenerationStage(state.stageIndex, { progress: state.progress, allowBackwards: true });
}

function startDgxLogPolling() {
  stopDgxLogPolling();
  pollDgxLog();
  window.bookGenerationLogTimer = window.setInterval(pollDgxLog, 1800);
}

function stopDgxLogPolling() {
  window.clearInterval(window.bookGenerationLogTimer);
  window.bookGenerationLogTimer = null;
}

function startBookGenerationJobPolling(jobId, redirectUrl) {
  stopBookGenerationJobPolling();
  window.bookGenerationJobActive = true;
  window.bookGenerationJobId = jobId;
  window.bookGenerationRedirectUrl = redirectUrl || "";
  pollBookGenerationJob(jobId, redirectUrl);
  window.bookGenerationJobTimer = window.setInterval(() => {
    pollBookGenerationJob(jobId, redirectUrl);
  }, 1500);
}

function stopBookGenerationJobPolling() {
  window.clearInterval(window.bookGenerationJobTimer);
  window.bookGenerationJobTimer = null;
  window.bookGenerationJobActive = false;
}

async function pollBookGenerationJob(jobId, redirectUrl) {
  const overlay = document.querySelector("[data-book-generation-overlay]");
  if (!overlay) return;
  try {
    const response = await fetch(`/api/book-generation/jobs/${encodeURIComponent(jobId)}?ts=${Date.now()}`, {
      cache: "no-store",
      headers: { "Accept": "application/json" },
    });
    if (!response.ok) {
      appendBookGenerationLog(`Browser: job status poll returned HTTP ${response.status}.`);
      return;
    }
    const payload = await response.json();
    updateBookGenerationStageFromJob(payload);
    window.bookGenerationJobLog = payload.events || [];
    window.bookGenerationJobResult = payload.result || {};
    renderBookGenerationLog();

    if (payload.status === "done") {
      const events = payload.events || [];
      const latestEvent = events.length ? events[events.length - 1] : "";
      setBookGenerationComplete({ detail: latestEvent || "Final artifact check passed." });
      const result = payload.result || {};
      const targetUrl = result.review_url || redirectUrl || payload.redirect_url || result.workflow_url || `/workflow?book_slug=${payload.book_slug}`;
      setBookGenerationOpenLink(targetUrl);
      appendBookGenerationLog("Browser: submitted job completed. Book page is ready to open.");
      refreshGenerationJobForms();
      if (targetUrl && window.location.pathname === "/story-maker" && targetUrl.includes("/story-maker")) {
        window.location.href = targetUrl;
        return;
      }
      if (overlay.hidden) setBookGenerationReopenVisible(true, "Book Ready");
    } else if (payload.status === "failed") {
      setBookGenerationFailed(payload.error || "The submitted book generation job failed.");
      appendBookGenerationLog(`Browser: submitted job failed: ${payload.error || "unknown error"}`);
      stopDgxLogPolling();
      refreshGenerationJobForms();
    }
  } catch (error) {
    appendBookGenerationLog(`Browser: could not read job status yet: ${error}`);
  }
}

function updateBookGenerationStageFromJob(payload) {
  const stageToIndex = {
    queued: 0,
    dgx_starting: 1,
    planner_generating: 2,
    planner_releasing: 2,
    planner_page_saved: 2,
    story_received: 2,
    pages_created: 3,
    prompts_created: 3,
    specs_exported: 3,
    managed_build_started: 3,
    characters_generating: 4,
    characters_complete: 4,
    images_generating: 5,
    images_complete: 5,
    review_exported: 6,
    production_exports: 7,
    complete: 9,
  };
  if (payload.status === "failed") {
    setBookGenerationFailed(payload.error || "The submitted book generation request failed.");
    return;
  }

  const stageIndex = stageToIndex[payload.stage] ?? 0;
  const events = payload.events || [];
  const latestEvent = events.length ? events[events.length - 1] : "";
  setBookGenerationStage(stageIndex, {
    progress: typeof payload.progress === "number" ? payload.progress : undefined,
    detail: latestEvent || undefined,
  });
}

async function pollDgxLog() {
  const overlay = document.querySelector("[data-book-generation-overlay]");
  if (!overlay || overlay.hidden) return;
  const state = overlay.querySelector("[data-book-generation-log-state]");
  try {
    const response = await fetch(`/api/dgx/planner-log?lines=90&ts=${Date.now()}`, {
      cache: "no-store",
      headers: { "Accept": "application/json" },
    });
    const payload = await response.json();
    window.bookGenerationRemoteLog = payload.log || "";
    if (state) state.textContent = payload.available ? "live" : "waiting";
    if (!window.bookGenerationJobActive) {
      updateBookGenerationStageFromLog(window.bookGenerationRemoteLog);
    }
    renderBookGenerationLog();
  } catch (error) {
    if (state) state.textContent = "offline";
    window.bookGenerationRemoteLog = `Could not read DGX log yet: ${error}`;
    renderBookGenerationLog();
  }
}

function updateBookGenerationStageFromLog(logText) {
  const text = (logText || "").toLowerCase();
  if (!text) return;
  const lines = text.split(/\n+/).map((line) => line.trim()).filter(Boolean);
  const latestRelevantLine = [...lines]
    .reverse()
    .find((line) => (
      /running:\s*\d+/.test(line) ||
      line.includes("post /v1/chat/completions") ||
      line.includes("started server process") ||
      line.includes("application startup complete") ||
      line.includes("loading") ||
      line.includes("model") ||
      line.includes("cuda") ||
      line.includes("waiting for")
    ));

  if (latestRelevantLine && (/running:\s*[1-9]/.test(latestRelevantLine) || latestRelevantLine.includes("post /v1/chat/completions"))) {
    setBookGenerationStage(2, { progress: 35 });
    return;
  }
  if (
    text.includes("started server process") ||
    text.includes("application startup complete") ||
    text.includes("loading") ||
    text.includes("model") ||
    text.includes("cuda") ||
    text.includes("waiting for")
  ) {
    setBookGenerationStage(1, { progress: 12 });
  }
}

function resetBookGenerationLog() {
  window.bookGenerationClientLog = [];
  window.bookGenerationJobLog = [];
  window.bookGenerationJobResult = {};
  window.bookGenerationRemoteLog = "";
  window.bookGenerationJobActive = false;
  renderBookGenerationLog();
}

function appendBookGenerationLog(line) {
  const timestamp = new Date().toLocaleTimeString();
  window.bookGenerationClientLog = window.bookGenerationClientLog || [];
  window.bookGenerationClientLog.push(`[${timestamp}] ${line}`);
  renderBookGenerationLog();
}

function renderBookGenerationLog() {
  const log = document.querySelector("[data-book-generation-log]");
  if (!log) return;
  const clientLines = window.bookGenerationClientLog || [];
  const jobLines = window.bookGenerationJobLog || [];
  const result = window.bookGenerationJobResult || {};
  const requestSummary = result.request_summary;
  const responseSummary = result.response_summary;
  const remoteLog = (window.bookGenerationRemoteLog || "").trim();
  log.textContent = [
    ...clientLines,
    jobLines.length ? "\n--- submitted job milestones ---" : "",
    ...jobLines.map((line) => `Job: ${line}`),
    requestSummary ? "\n--- planner request summary ---" : "",
    ...formatBookGenerationSummary(requestSummary),
    responseSummary ? "\n--- planner response summary ---" : "",
    ...formatBookGenerationSummary(responseSummary),
    remoteLog ? "\n--- DGX vLLM planner log (planner phases only) ---" : "\n--- DGX vLLM planner log (planner phases only) ---\nNo vLLM planner output for this phase. Watch the job milestones above for prompt/image progress.",
    remoteLog,
  ].filter(Boolean).join("\n");
  log.scrollTop = log.scrollHeight;
}

function formatBookGenerationSummary(summary) {
  if (!summary || typeof summary !== "object") return [];
  const lines = [];
  const labels = {
    title: "Title",
    page_count: "Pages",
    target_age: "Target age",
    lesson: "Lesson",
    idea: "Idea",
    focus_characters: "Characters",
    focus_items: "Objects/items",
    reference_notes: "Reference notes",
    requested_output: "Requested output",
    summary: "Returned summary",
  };
  Object.entries(labels).forEach(([key, label]) => {
    if (summary[key] === undefined || summary[key] === null || summary[key] === "") return;
    const value = formatSummaryValue(summary[key]);
    if (value) lines.push(`${label}: ${value}`);
  });
  if (Array.isArray(summary.page_samples) && summary.page_samples.length) {
    lines.push("Page samples:");
    summary.page_samples.forEach((page) => {
      if (!page || typeof page !== "object") return;
      const pageNumber = page.page ? `p${page.page}` : "page";
      const scene = page.scene || "Untitled scene";
      const story = page.story ? ` - ${page.story}` : "";
      lines.push(`  ${pageNumber}: ${scene}${story}`);
    });
  }
  return lines;
}

function formatSummaryValue(value) {
  if (Array.isArray(value)) return value.filter(Boolean).join(", ");
  if (typeof value === "object") return "";
  return String(value).replace(/\s+/g, " ").trim();
}

function toggleBookGenerationLog(button) {
  const panel = button.closest("[data-book-generation-log-panel]");
  if (!panel) return;

  const isCollapsed = panel.classList.toggle("is-collapsed");
  button.setAttribute("aria-expanded", String(!isCollapsed));
  button.textContent = isCollapsed ? "Show" : "Hide";
}

function closeBookGenerationDialog() {
  const overlay = document.querySelector("[data-book-generation-overlay]");
  if (!overlay) return;
  overlay.hidden = true;
  document.body.classList.remove("is-generating-book");
  setBookGenerationReopenVisible(true);
}

function reopenBookGenerationDialog() {
  const overlay = ensureBookGenerationOverlay();
  overlay.hidden = false;
  document.body.classList.add("is-generating-book");
  setBookGenerationReopenVisible(false);
  const isComplete = Boolean(window.bookGenerationProgress && window.bookGenerationProgress.complete);
  if (window.bookGenerationJobId && !window.bookGenerationJobTimer && !isComplete) {
    startBookGenerationJobPolling(window.bookGenerationJobId, window.bookGenerationRedirectUrl || "");
  }
  if (!window.bookGenerationLogTimer && !isComplete) {
    startDgxLogPolling();
  }
  renderBookGenerationLog();
}

function setBookGenerationReopenVisible(visible, label = "Book Generation") {
  const button = ensureBookGenerationReopenButton();
  button.hidden = !visible;
  button.textContent = label;
}

function setBookGenerationOpenLink(href) {
  const overlay = ensureBookGenerationOverlay();
  const link = overlay.querySelector("[data-book-generation-open]");
  if (!link) return;
  link.href = href || "#";
  link.hidden = !href;
}

function ensureBookGenerationOverlay() {
  let overlay = document.querySelector("[data-book-generation-overlay]");
  if (overlay) return overlay;

  overlay = document.createElement("div");
  overlay.className = "book-generation-overlay";
  overlay.dataset.bookGenerationOverlay = "true";
  overlay.hidden = true;
  overlay.innerHTML = `
    <section class="book-generation-dialog" role="status" aria-live="polite" aria-label="Book generation status">
      <div class="book-generation-topline">
        <span>Book generation started</span>
        <div class="book-generation-actions">
          <a href="#" data-book-generation-open hidden>Open Book</a>
          <strong data-book-generation-percent>0%</strong>
          <button type="button" data-book-generation-close aria-label="Close book generation dialog">Close</button>
        </div>
      </div>
      <h2 data-book-generation-title>Generating book</h2>
      <p data-book-generation-detail>Starting the planner.</p>
      <div class="book-generation-progress" aria-hidden="true">
        <div data-book-generation-fill></div>
      </div>
      <ol class="book-generation-steps" data-book-generation-steps></ol>
      <div class="book-generation-log-panel" data-book-generation-log-panel>
        <div class="book-generation-log-head">
          <span>Hackster Studio / DGX Output</span>
          <div>
            <strong data-book-generation-log-state>connecting</strong>
            <button type="button" data-book-generation-log-toggle aria-expanded="true">Hide</button>
          </div>
        </div>
        <pre data-book-generation-log>Waiting for DGX log output...</pre>
      </div>
    </section>
  `;
  document.body.appendChild(overlay);
  return overlay;
}

function ensureBookGenerationReopenButton() {
  let button = document.querySelector("[data-book-generation-reopen]");
  if (button) return button;

  button = document.createElement("button");
  button.type = "button";
  button.className = "book-generation-reopen";
  button.dataset.bookGenerationReopen = "true";
  button.hidden = true;
  button.textContent = "Book Generation";
  document.body.appendChild(button);
  return button;
}

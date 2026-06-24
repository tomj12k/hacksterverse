// ── Constants ──────────────────────────────────────────────────────────────

const LAYER_ICONS = {
  camera:     "CAM",
  lighting:   "LGT",
  text:       "TXT",
  foreground: "FG",
  character:  "CHR",
  props:      "PRP",
  midground:  "MID",
  background: "BG",
};

const LIGHTING_SHADOW_ANGLES = {
  ambient_soft:        270,
  warm_sunset_left:    225,
  cool_forest_ambient: 270,
  dramatic_backlight:   45,
};

const GENERATED_LAYER_DIRS = {
  background: "backgrounds",
  midground:  "midground",
  foreground: "foreground",
  character:  "characters",
  props:      "props",
};

// ── State ──────────────────────────────────────────────────────────────────

function initStoryMaker() {
  const root = document.querySelector("[data-story-maker]");
  const data = document.querySelector("#story-scene-data");
  if (!root || !data) return;

  const scene = JSON.parse(data.textContent);
  const stage = root.querySelector("[data-story-stage]");
  const layerList = root.querySelector("[data-layer-list]");
  const boneList = root.querySelector("[data-bone-list]");
  const poseExtras = root.querySelector("[data-pose-extras]");
  const deleteLayerButton = root.querySelector("[data-action='delete-layer']");
  const undoButton = document.querySelector("[data-action='undo']");
  const redoButton = document.querySelector("[data-action='redo']");
  const saveState = document.querySelector("[data-save-state]");
  const qaPanel = root.querySelector("[data-qa-panel]");
  const pageStatusControl = document.querySelector("[data-page-status-control]");
  const pageStatusBadge = document.querySelector("[data-page-status]");
  const qaSummary = document.querySelector("[data-qa-summary]");
  const preserveAspectOption = root.querySelector("[data-transform-option='preserve-aspect']");
  const gridToggle = document.querySelector("[data-grid-toggle]");
  const snapToggle = document.querySelector("[data-snap-toggle]");
  const gridSizeControl = document.querySelector("[data-grid-size]");
  const snapReadout = document.querySelector("[data-snap-readout]");
  const stageActionStatus = document.querySelector("[data-stage-action-status]");
  const viewportButtons = Array.from(document.querySelectorAll("[data-viewport-mode]"));
  const castList = root.querySelector("[data-story-cast]");
  const controls = Array.from(root.querySelectorAll("[data-control]"));
  let selectedId = null;
  let isDirty = false;
  let restoringHistory = false;
  const history = { undo: [], redo: [], limit: 80 };
  const activeGenIntervals = new Map();

  // Sort layers high z_index first for panel; low z_index first for stage.
  const sortedForPanel = () =>
    [...scene.layers].sort((a, b) => (b.z_index || 0) - (a.z_index || 0));
  const sortedForStage = () =>
    [...scene.layers].sort((a, b) => (a.z_index || 0) - (b.z_index || 0));

  const findLayer = (id) => scene.layers.find((l) => l.id === id);
  const plannedCharacters = () => Array.isArray(scene.planned_characters) ? scene.planned_characters : [];

  function nowIso() {
    return new Date().toISOString();
  }

  function canDeleteLayer(layer) {
    return !!layer && !layer.locked && !["camera"].includes(layer.type);
  }

  function canResizeLayer(layer) {
    return !!layer && !layer.locked && !["camera", "lighting"].includes(layer.type);
  }

  function syncTransformControls(layer) {
    controls.forEach((input) => {
      const key = input.dataset.control;
      const val = layer?.transform?.[key];
      const defaultValue = ["opacity", "scale", "zoom"].includes(key) ? 1 : 0;
      input.value = val ?? defaultValue;
      input.disabled = !layer || (["width", "height"].includes(key) && !canResizeLayer(layer));
    });
    if (preserveAspectOption) {
      preserveAspectOption.checked = !!layer?.preserve_aspect;
      preserveAspectOption.disabled = !layer || !canResizeLayer(layer);
    }
  }

  function safeMarginPct() {
    const canvas = scene.canvas ?? {};
    const trim = canvas.trim_inches ?? [8.5, 8.5];
    return (canvas.safe_margin_inches ?? 0.5) / (trim[0] || 8.5);
  }

  function gridSize() {
    return Number(gridSizeControl?.value ?? 0.05) || 0.05;
  }

  function snapValue(value) {
    if (!snapToggle?.checked) return value;
    const size = gridSize();
    return Math.round(value / size) * size;
  }

  function clamp01(value) {
    return Math.min(1, Math.max(0, value));
  }

  function clampSize(value) {
    return Math.max(0.02, Math.min(2, value));
  }

  function percent(value) {
    return `${Math.round(value * 1000) / 10}%`;
  }

  function updateSnapReadout(layer) {
    if (!snapReadout) return;
    if (!layer?.transform) {
      snapReadout.textContent = `Snap: ${percent(gridSize())} grid`;
      return;
    }
    const t = layer.transform;
    snapReadout.textContent = `Snap: ${percent(gridSize())} grid · X ${percent(t.x ?? 0)} · Y ${percent(t.y ?? 0)} · W ${percent(t.width ?? 0)} · H ${percent(t.height ?? 0)}`;
  }

  function layerBounds(layer) {
    const t = layer?.transform ?? {};
    const x = t.x ?? 0.5;
    const y = t.y ?? 0.5;
    const width = t.width ?? 1;
    const height = t.height ?? 1;
    return {
      left: x - width / 2,
      right: x + width / 2,
      top: y - height / 2,
      bottom: y + height / 2,
      width,
      height,
    };
  }

  function recordPrompt(layer, prompt, kind = "image") {
    if (!prompt) return;
    const entry = {
      kind,
      prompt,
      at: nowIso(),
      lighting_variant: scene.lighting_brief ?? "ambient_soft",
    };
    layer.prompt_history = layer.prompt_history ?? [];
    layer.prompt_history.unshift(entry);
    scene.prompt_history = scene.prompt_history ?? [];
    scene.prompt_history.unshift({ layer_id: layer.id, layer_name: layer.name, ...entry });
    layer.prompt_history = layer.prompt_history.slice(0, 12);
    scene.prompt_history = scene.prompt_history.slice(0, 50);
  }

  function recordAssetVersion(layer, assetPath, source = "generate") {
    if (!assetPath) return;
    layer.versions = layer.versions ?? [];
    if (layer.versions[0]?.asset_path === assetPath) return;
    layer.versions.unshift({
      asset_path: assetPath,
      source,
      at: nowIso(),
    });
    layer.versions = layer.versions.slice(0, 12);
  }

  function computeSceneQa() {
    const issues = [];
    const layers = scene.layers ?? [];
    const visibleLayers = layers.filter((layer) => layer.visible !== false);
    const status = scene.status ?? "not_started";
    const safe = safeMarginPct();
    const hasBackground = visibleLayers.some((layer) => layer.type === "background" && layer.asset_path);
    const hasText = visibleLayers.some((layer) => layer.type === "text");
    const hasNiko = visibleLayers.some((layer) => layer.id === "char_niko");

    if (!hasBackground) issues.push({ severity: "error", code: "missing_background", message: "No visible background image layer." });
    if (!hasText) issues.push({ severity: "warning", code: "missing_text", message: "No visible dialogue/text layer." });
    if (scene.uses_hackster_niko && !hasNiko && (scene.page_number ?? 0) >= 4) issues.push({ severity: "warning", code: "missing_niko", message: "Hackster Niko is not present as a separate layer." });

    visibleLayers.forEach((layer) => {
      if (["camera", "lighting"].includes(layer.type)) return;
      const b = layerBounds(layer);
      if (layer.type === "text" && (b.left < safe || b.top < safe || b.right > 1 - safe || b.bottom > 1 - safe)) {
        issues.push({ severity: "error", code: "text_outside_safe_area", message: `${layer.name || "Text"} crosses the safe text margin.` });
      }
      if (b.width <= 0 || b.height <= 0) {
        issues.push({ severity: "error", code: "invalid_layer_size", message: `${layer.name || "Layer"} has an invalid size.` });
      }
      if (!["text"].includes(layer.type) && !layer.asset_path) {
        issues.push({ severity: "warning", code: "missing_asset", message: `${layer.name || "Layer"} has no image asset.` });
      }
    });

    if (status !== "approved") issues.push({ severity: "info", code: "not_approved", message: "Page is not approved yet." });
    const errors = issues.filter((issue) => issue.severity === "error").length;
    const warnings = issues.filter((issue) => issue.severity === "warning").length;
    return { ready: errors === 0 && status === "approved", errors, warnings, issues };
  }

  function renderQa() {
    scene.qa = computeSceneQa();
    if (qaSummary) {
      qaSummary.textContent = `${scene.qa.errors} errors · ${scene.qa.warnings} warnings`;
    }
    if (!qaPanel) return;
    qaPanel.innerHTML = "";
    if (!scene.qa.issues.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No QA issues.";
      qaPanel.appendChild(empty);
      return;
    }
    scene.qa.issues.forEach((issue) => {
      const row = document.createElement("div");
      row.className = `qa-issue qa-issue--${issue.severity}`;
      const severity = document.createElement("strong");
      severity.textContent = issue.severity.toUpperCase();
      const message = document.createElement("span");
      message.textContent = issue.message;
      row.append(severity, message);
      qaPanel.appendChild(row);
    });
  }

  function syncPageStatus() {
    scene.status = scene.status ?? "not_started";
    scene.approval = scene.approval ?? { approved: false, approved_at: null, approved_by: null, notes: "" };
    if (pageStatusControl) pageStatusControl.value = scene.status;
    if (pageStatusBadge) pageStatusBadge.textContent = scene.status.replace(/_/g, " ").replace(/\b\w/g, (ch) => ch.toUpperCase());
    renderQa();
  }

  function snapshotScene() {
    return JSON.stringify({ scene, selectedId });
  }

  function updateHistoryButtons() {
    if (undoButton) undoButton.disabled = history.undo.length === 0;
    if (redoButton) redoButton.disabled = history.redo.length === 0;
  }

  function setDirty(value = true) {
    isDirty = value;
    if (!saveState) return;
    saveState.textContent = value ? "Unsaved" : "Saved";
    saveState.classList.toggle("is-dirty", value);
  }

  function pushHistory() {
    if (restoringHistory) return;
    const snap = snapshotScene();
    if (history.undo[history.undo.length - 1] === snap) return;
    history.undo.push(snap);
    if (history.undo.length > history.limit) history.undo.shift();
    history.redo = [];
    updateHistoryButtons();
  }

  function noteSceneChange() {
    if (!restoringHistory) setDirty(true);
    renderQa();
  }

  function restoreSnapshot(snapshot) {
    restoringHistory = true;
    try {
      const restored = JSON.parse(snapshot);
      Object.keys(scene).forEach((key) => delete scene[key]);
      Object.assign(scene, restored.scene);
      selectedId = restored.selectedId;
      stage.querySelectorAll(".story-layer").forEach((el) => el.remove());
      sortedForStage().forEach(renderLayer);
      rebuildLayerPanel();
      if (selectedId && findLayer(selectedId)) {
        selectLayer(selectedId);
      } else {
        const firstNonCamera = sortedForPanel().find((l) => l.type !== "camera");
        if (firstNonCamera) selectLayer(firstNonCamera.id);
        else selectLayer(null);
      }
      syncPageStatus();
      setDirty(true);
    } finally {
      restoringHistory = false;
      updateHistoryButtons();
    }
  }

  function undoSceneChange() {
    if (!history.undo.length) return;
    history.redo.push(snapshotScene());
    restoreSnapshot(history.undo.pop());
  }

  function redoSceneChange() {
    if (!history.redo.length) return;
    history.undo.push(snapshotScene());
    restoreSnapshot(history.redo.pop());
  }

  function setViewportMode(mode) {
    const next = ["default", "theater", "focus"].includes(mode) ? mode : "default";
    root.dataset.viewportMode = next;
    viewportButtons.forEach((button) => {
      const active = button.dataset.viewportMode === next;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
    localStorage.setItem("storyMakerViewportMode", next);
    scene.layers.forEach(updateLayerElement);
    updateSnapReadout(findLayer(selectedId));
  }

  function hexToRgba(hex, alpha = 1) {
    const raw = String(hex || "#FFFFFF").replace("#", "");
    const full = raw.length === 3 ? raw.split("").map((ch) => ch + ch).join("") : raw;
    const value = /^[0-9a-fA-F]{6}$/.test(full) ? full : "FFFFFF";
    const r = parseInt(value.slice(0, 2), 16);
    const g = parseInt(value.slice(2, 4), 16);
    const b = parseInt(value.slice(4, 6), 16);
    return `rgba(${r}, ${g}, ${b}, ${Math.max(0, Math.min(1, alpha))})`;
  }

  function slugPart(value, fallback = "layer") {
    return String(value || fallback)
      .toLowerCase()
      .replace(/[^a-z0-9_-]+/g, "_")
      .replace(/^_+|_+$/g, "") || fallback;
  }

  function defaultGenerationPath(layer) {
    const lighting = slugPart(scene.lighting_brief ?? "ambient_soft", "ambient_soft");
    const fileName = `${slugPart(layer.id)}_${lighting}.png`;
    if (layer.type === "character") {
      const characterSlug = slugPart(layer.character_slug ?? "niko", "niko");
      return `assets/layers/characters/${characterSlug}/${fileName}`;
    }
    const dir = GENERATED_LAYER_DIRS[layer.type] ?? "props";
    return `assets/layers/${dir}/${fileName}`;
  }

  function characterLayerFor(slug) {
    return scene.layers.find((layer) => (
      layer.type === "character" && slugPart(layer.character_slug, "character") === slug
    ));
  }

  function addPlannedCharacterLayer(character, assetPath = null) {
    const name = character?.name || "Character";
    const slug = slugPart(character?.slug || name, "character");
    const existing = characterLayerFor(slug);
    if (existing) {
      selectLayer(existing.id);
      return existing;
    }

    pushHistory();
    const sameTypeCount = scene.layers.filter((layer) => layer.type === "character").length;
    const layer = {
      id: `character_${slug}_${Date.now()}`,
      name,
      type: "character",
      z_index: Number((3 + sameTypeCount * 0.01).toFixed(2)),
      parallax_factor: 1.0,
      character_slug: slug,
      asset_path: assetPath || character?.asset_paths?.[0] || null,
      lighting_variant: scene.lighting_brief ?? "ambient_soft",
      pose: "standing_neutral",
      rig: null,
      prompt_history: [{
        kind: "character",
        prompt: `${name}, full body character layer, consistent design, transparent background PNG with real alpha, clean cutout silhouette, no backdrop, no white sheet, ${scene.lighting_brief ?? "ambient"} lighting`,
        at: nowIso(),
        lighting_variant: scene.lighting_brief ?? "ambient_soft",
      }],
      shadow: {
        enabled: false,
        angle: LIGHTING_SHADOW_ANGLES[scene.lighting_brief] ?? 270,
        distance: 12,
        blur: 8,
        opacity: 0.3,
      },
      transform: {
        x: 0.5,
        y: 0.58,
        width: 0.26,
        height: 0.42,
        scale: 1.0,
        rotation: 0,
        opacity: 1,
      },
    };
    scene.layers.push(layer);
    renderLayer(layer);
    rebuildLayerPanel();
    renderStoryCast();
    selectLayer(layer.id);
    noteSceneChange();
    if (!layer.asset_path) {
      autoGenerateCharacterLayer(layer);
    }
    return layer;
  }

  function characterPrompt(layer) {
    return `${layer.name || layer.character_slug || "Character"}, full body character layer, consistent design, transparent background PNG with real alpha, clean cutout silhouette, no backdrop, no white sheet, expressive readable silhouette, children's premium storybook style, ${scene.lighting_brief ?? "ambient"} lighting`;
  }

  function setGenerationStatus(layer, statusEl, message) {
    layer.generation_status = message;
    if (statusEl) statusEl.textContent = message;
    const statusNode = stage.querySelector(`[data-layer-id="${layer.id}"] .story-placeholder-status`);
    if (statusNode) statusNode.textContent = message;
    renderStoryCast();
  }

  function clearGenerationStatus(layer, statusEl, message = "") {
    delete layer.generation_status;
    if (statusEl) statusEl.textContent = message;
    renderStoryCast();
  }

  function autoGenerateCharacterLayer(layer) {
    const prompt = layer.prompt_history?.[0]?.prompt || characterPrompt(layer);
    const outputPath = defaultGenerationPath(layer);
    recordPrompt(layer, prompt, "character");
    setGenerationStatus(layer, null, "Submitting character art...");
    fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        layer_id: layer.id,
        layer_type: layer.type,
        prompt,
        output_path: outputPath,
        lighting_variant: scene.lighting_brief ?? "ambient_soft",
      }),
    })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(({ job_id }) => {
        setGenerationStatus(layer, null, "Generating character art...");
        pollJob(job_id, layer, outputPath, null);
      })
      .catch((err) => {
        setGenerationStatus(layer, null, "Generation failed. Use Inspector > Generate Image to retry.");
        console.error("Automatic character generation failed:", err);
      });
  }

  function renderStoryCast() {
    if (!castList) return;
    castList.innerHTML = "";
    const characters = plannedCharacters();
    if (!characters.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No planned characters found for this book.";
      castList.appendChild(empty);
      return;
    }

    characters.forEach((character) => {
      const slug = slugPart(character.slug || character.name, "character");
      const layer = characterLayerFor(slug);
      const assetPath = character.asset_paths?.[0] || layer?.asset_path || null;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "story-cast-button";
      button.classList.toggle("is-on-page", !!layer);
      button.dataset.characterSlug = slug;

      const avatar = document.createElement("span");
      avatar.className = "story-cast-avatar";
      if (assetPath) {
        const img = document.createElement("img");
        img.src = `/project-assets/${assetPath}`;
        img.alt = character.name;
        img.onerror = () => {
          img.remove();
          avatar.textContent = (character.name || "?").slice(0, 2).toUpperCase();
        };
        avatar.appendChild(img);
      } else {
        avatar.textContent = (character.name || "?").slice(0, 2).toUpperCase();
      }

      const copy = document.createElement("span");
      copy.className = "story-cast-copy";
      const name = document.createElement("strong");
      name.textContent = character.name || slug;
      const status = document.createElement("small");
      status.textContent = layer ? "On page" : "Add to page";
      copy.append(name, status);
      button.append(avatar, copy);
      button.addEventListener("click", () => addPlannedCharacterLayer(character, assetPath));
      castList.appendChild(button);
    });
  }

  // ── Camera helpers ────────────────────────────────────────────────────────

  function getCameraLayer() {
    return scene.layers.find((l) => l.type === "camera");
  }

  function computeParallaxOffset(layer) {
    const cam = getCameraLayer();
    if (!cam) return { dx: 0, dy: 0 };
    const factor = layer.parallax_factor ?? 1.0;
    return {
      dx: (cam.transform?.x ?? 0) * factor,
      dy: (cam.transform?.y ?? 0) * factor,
    };
  }

  // ── Shadow CSS ────────────────────────────────────────────────────────────

  function shadowFilter(shadow) {
    if (!shadow?.enabled) return "";
    const angle = (shadow.angle ?? 270) * (Math.PI / 180);
    const dist = shadow.distance ?? 12;
    const blur = shadow.blur ?? 8;
    const opacity = shadow.opacity ?? 0.3;
    const dx = Math.round(Math.cos(angle) * dist);
    const dy = Math.round(Math.sin(angle) * dist);
    return `drop-shadow(${dx}px ${dy}px ${blur}px rgba(0,0,0,${opacity}))`;
  }

  // ── Render layer element ──────────────────────────────────────────────────

  function appendResizeHandle(el, layer) {
    if (!canResizeLayer(layer)) return;
    const handle = document.createElement("button");
    handle.type = "button";
    handle.className = "story-resize-handle";
    handle.setAttribute("aria-label", `Resize ${layer.name}`);
    el.appendChild(handle);
  }

  function renderLayer(layer) {
    // Remove stale element if re-rendering
    stage.querySelector(`[data-layer-id="${layer.id}"]`)?.remove();

    const el = document.createElement("div");
    el.className = "story-layer";
    el.dataset.layerId = layer.id;
    el.dataset.layerType = layer.type;
    if (layer.locked) el.classList.add("is-locked");
    if (layer.visible === false) el.classList.add("is-hidden-layer");

    if (layer.type === "lighting") {
      el.classList.add("story-layer--lighting");
      el.style.position = "absolute";
      el.style.inset = "0";
      el.style.pointerEvents = "none";
      el.style.zIndex = layer.z_index ?? 1;
      el.style.backgroundColor = layer.tint_color ?? "#FFFFFF";
      el.style.mixBlendMode = layer.blend_mode ?? "multiply";
      el.style.opacity = layer.opacity ?? 0;
      stage.appendChild(el);
      return;
    }

    if (layer.type === "camera") {
      el.classList.add("story-layer--camera");
      el.style.position = "absolute";
      el.style.inset = "0";
      el.style.border = "2px dashed rgba(0,180,255,0.6)";
      el.style.pointerEvents = "none";
      el.style.zIndex = layer.z_index ?? 99;
      stage.appendChild(el);
      return;
    }

    if (layer.type === "text") {
      el.classList.add("story-layer--text");
      el.style.zIndex = layer.z_index ?? 1;
      if (layer.asset_path) {
        el.classList.add("story-layer--text-art");
        const img = document.createElement("img");
        img.alt = layer.name;
        img.src = `/project-assets/${layer.asset_path}?v=${Date.now()}`;
        img.style.width = "100%";
        img.style.height = "100%";
        img.style.objectFit = "contain";
        el.appendChild(img);
      } else {
        const textEl = document.createElement("div");
        textEl.className = "story-placeholder story-placeholder--text";
        textEl.textContent = layer.text || layer.name;
        el.appendChild(textEl);
      }
      appendResizeHandle(el, layer);
      stage.appendChild(el);
      updateLayerElement(layer);
      return;
    }

    // Image-bearing layers (background, midground, foreground, character, props)
    el.style.zIndex = layer.z_index ?? 1;
    if (layer.asset_path) {
      const img = document.createElement("img");
      img.alt = layer.name;
      img.src = `/project-assets/${layer.asset_path}${layer.asset_version ? `?v=${layer.asset_version}` : ""}`;
      img.style.width = "100%";
      img.style.height = "100%";
      img.style.objectFit = "fill";
      el.appendChild(img);
    } else {
      const ph = document.createElement("div");
      ph.className = "story-placeholder";
      if (layer.type === "background") {
        ph.classList.add("story-placeholder--background");
        ph.setAttribute("aria-label", layer.name);
      } else if (layer.type === "character") {
        ph.classList.add("story-placeholder--character");
        const initials = document.createElement("span");
        initials.className = "story-placeholder-initials";
        initials.textContent = (layer.name || "CH").slice(0, 2).toUpperCase();
        const name = document.createElement("strong");
        name.textContent = layer.name || "Character";
        const status = document.createElement("span");
        status.className = "story-placeholder-status";
        status.textContent = layer.generation_status || "Character art not generated yet.";
        ph.append(initials, name, status);
      } else {
        ph.textContent = `${LAYER_ICONS[layer.type] ?? ""} ${layer.name}`;
      }
      el.appendChild(ph);
    }

    // Shadow filter for character and props
    if (layer.type === "character" || layer.type === "props") {
      const filter = shadowFilter(layer.shadow);
      if (filter) el.style.filter = filter;
    }

    appendResizeHandle(el, layer);

    stage.appendChild(el);
    updateLayerElement(layer);
  }

  function updateLayerElement(layer) {
    const el = stage.querySelector(`[data-layer-id="${layer.id}"]`);
    if (!el) return;

    if (layer.type === "lighting") {
      el.style.backgroundColor = layer.tint_color ?? "#FFFFFF";
      el.style.mixBlendMode = layer.blend_mode ?? "multiply";
      el.style.opacity = layer.opacity ?? 0;
      return;
    }

    if (layer.type === "camera") return;

    const transform = layer.transform ?? {};
    const { dx, dy } = computeParallaxOffset(layer);

    const x = (transform.x ?? 0) - dx;
    const y = (transform.y ?? 0) - dy;
    const w = transform.width ?? 1;
    const h = transform.height ?? 1;
    const scale = transform.scale ?? 1;
    const rotation = transform.rotation ?? 0;
    const opacity = transform.opacity ?? 1;

    el.style.left = `${x * 100}%`;
    el.style.top = `${y * 100}%`;
    el.style.width = `${w * 100}%`;
    el.style.height = `${h * 100}%`;
    el.style.opacity = opacity;
    el.style.display = layer.visible === false ? "none" : "";
    el.style.transform = `translate(-50%, -50%) rotate(${rotation}deg) scale(${scale})`;
    el.classList.toggle("is-selected", layer.id === selectedId);
    el.classList.toggle("is-locked", !!layer.locked);
    el.classList.toggle("is-hidden-layer", layer.visible === false);

    if (layer.type === "character" || layer.type === "props") {
      el.style.filter = shadowFilter(layer.shadow);
    }

    if (layer.type === "text" && !layer.asset_path) {
      const textEl = el.querySelector(".story-placeholder--text");
      if (textEl) {
        textEl.textContent = layer.text || layer.name || "";
        textEl.style.color = layer.text_color ?? "#154c84";
        textEl.style.backgroundColor = hexToRgba(layer.box_color ?? "#FFFFFF", layer.box_opacity ?? 0.88);
        textEl.style.textAlign = layer.align ?? "center";
        textEl.style.fontSize = `${Math.max(12, Math.round((layer.font_size ?? 0.04) * stage.getBoundingClientRect().height))}px`;
        textEl.style.textShadow = `0 2px 0 ${hexToRgba(layer.stroke_color ?? "#F2C94C", 0.48)}`;
      }
    }
  }

  // ── Layer panel ───────────────────────────────────────────────────────────

  function rebuildLayerPanel() {
    layerList.innerHTML = "";
    sortedForPanel().forEach((layer) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "layer-button";
      button.dataset.layerId = layer.id;
      const icon = LAYER_ICONS[layer.type] ?? "";
      const type = document.createElement("span");
      type.className = "layer-type";
      type.textContent = icon;
      const name = document.createElement("span");
      name.className = "layer-name";
      name.textContent = layer.name;
      const state = document.createElement("span");
      state.className = "layer-state";
      state.textContent = [
        layer.visible === false ? "Hidden" : "",
        layer.locked ? "Locked" : "",
      ].filter(Boolean).join(" · ");
      button.classList.toggle("is-hidden", layer.visible === false);
      button.classList.toggle("is-locked", !!layer.locked);
      button.append(type, name, state);
      button.addEventListener("click", () => selectLayer(layer.id));
      layerList.appendChild(button);
    });
    renderStoryCast();
  }

  // ── Inspector ─────────────────────────────────────────────────────────────

  function renderBones(layer) {
    boneList.innerHTML = "";
    const bones = layer?.rig?.bones ?? [];
    if (!bones.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No skeleton assigned.";
      boneList.appendChild(empty);
      return;
    }
    bones.forEach((bone) => {
      const row = document.createElement("div");
      row.className = "bone-row";
      const label = document.createElement("span");
      label.textContent = bone.name;
      const range = document.createElement("input");
      range.type = "range";
      range.step = "1";
      range.min = String(bone.min ?? -90);
      range.max = String(bone.max ?? 90);
      range.value = bone.rotation ?? 0;
      const input = document.createElement("input");
      input.type = "number";
      input.step = "1";
      input.min = String(bone.min ?? -90);
      input.max = String(bone.max ?? 90);
      input.value = bone.rotation ?? 0;
      input.setAttribute("aria-label", `${bone.name} rotation`);
      const sync = (value) => {
        pushHistory();
        bone.rotation = Number(value);
        range.value = String(bone.rotation);
        input.value = String(bone.rotation);
        noteSceneChange();
      };
      range.addEventListener("input", () => sync(range.value));
      input.addEventListener("input", () => sync(input.value));
      row.appendChild(label);
      row.appendChild(range);
      row.appendChild(input);
      boneList.appendChild(row);
    });

    if (layer?.type === "character" && layer.character_slug === "niko") {
      const status = document.createElement("p");
      status.className = "gen-status";
      const btn = document.createElement("button");
      btn.type = "button";
      btn.dataset.action = "generate-niko-pose";
      btn.textContent = "Regenerate Pose";
      btn.addEventListener("click", () => generateNikoPose(layer, status));
      boneList.appendChild(btn);
      boneList.appendChild(status);
    }
  }

  async function generateNikoPose(layer, statusEl) {
    const customId = `${slugPart(scene.book_slug, "book")}_page_${String(scene.page_number).padStart(3, "0")}_${slugPart(layer.id, "niko")}`;
    const outputPath = `assets/layers/characters/niko/custom/${customId}.png`;
    statusEl.textContent = "Rendering pose…";
    try {
      const resp = await fetch("/api/generate/niko-pose", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pose: layer.pose ?? "custom",
          output_path: outputPath,
          rig: layer.rig ?? { bones: [] },
        }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const { asset_path } = await resp.json();
      pushHistory();
      recordAssetVersion(layer, layer.asset_path, "previous");
      layer.asset_path = asset_path;
      recordAssetVersion(layer, asset_path, "niko_pose");
      layer.pose = "custom";
      layer.asset_version = Date.now();
      renderLayer(layer);
      selectLayer(layer.id);
      noteSceneChange();
      statusEl.textContent = "Done ✓ — custom pose applied.";
    } catch (err) {
      statusEl.textContent = "Pose generation failed.";
      console.error("Niko pose generation failed:", err);
    }
  }

  function pollJob(jobId, layer, outputPath, statusEl) {
    const cleanup = () => {
      const interval = activeGenIntervals.get(jobId);
      if (interval) clearInterval(interval);
      activeGenIntervals.delete(jobId);
    };

    cleanup();
    const interval = setInterval(async () => {
      try {
        const resp = await fetch(`/api/generate/${jobId}`);
        const { status, asset_path } = await resp.json();
        setGenerationStatus(layer, statusEl, status);
        if (status === "done") {
          cleanup();
          pushHistory();
          recordAssetVersion(layer, layer.asset_path, "previous");
          layer.asset_path = asset_path ?? outputPath;
          recordAssetVersion(layer, layer.asset_path, "generate");
          layer.asset_version = Date.now();
          renderLayer(layer);
          selectLayer(layer.id);
          noteSceneChange();
          clearGenerationStatus(layer, statusEl, "Done ✓ — layer updated.");
        } else if (status === "failed") {
          cleanup();
          setGenerationStatus(layer, statusEl, "Generation failed. Use Inspector > Generate Image to retry.");
        }
      } catch {
        cleanup();
        setGenerationStatus(layer, statusEl, "Polling error. Use Inspector > Generate Image to retry.");
      }
    }, 2000);
    activeGenIntervals.set(jobId, interval);
  }

  function renderInspectorExtras(layer) {
    const extras = document.querySelector("[data-inspector-extras]");
    if (!extras) return;
    extras.innerHTML = "";
    if (poseExtras) poseExtras.innerHTML = "";

    if (!layer) return;

    const layerSection = document.createElement("div");
    layerSection.className = "inspector-section";
    const layerHeading = document.createElement("h3");
    layerHeading.textContent = "Layer";
    layerSection.appendChild(layerHeading);

    const nameLabel = document.createElement("label");
    nameLabel.textContent = "Name ";
    const nameInput = document.createElement("input");
    nameInput.type = "text";
    nameInput.value = layer.name ?? "";
    nameInput.addEventListener("input", () => {
      pushHistory();
      layer.name = nameInput.value || layer.id;
      rebuildLayerPanel();
      noteSceneChange();
    });
    nameLabel.appendChild(nameInput);
    layerSection.appendChild(nameLabel);

    if (layer.versions?.length) {
      const versionList = document.createElement("div");
      versionList.className = "version-list";
      layer.versions.slice(0, 5).forEach((version, index) => {
        if (!version.asset_path) return;
        const row = document.createElement("button");
        row.type = "button";
        row.className = "version-row";
        row.textContent = `${index === 0 ? "Current" : "Restore"} · ${version.source ?? "asset"} · ${version.asset_path.split("/").pop()}`;
        row.addEventListener("click", () => {
          pushHistory();
          recordAssetVersion(layer, layer.asset_path, "previous");
          layer.asset_path = version.asset_path;
          layer.asset_version = Date.now();
          renderLayer(layer);
          selectLayer(layer.id);
          noteSceneChange();
        });
        versionList.appendChild(row);
      });
      layerSection.appendChild(versionList);
    }

    if (layer.prompt_history?.length) {
      const promptDetails = document.createElement("details");
      promptDetails.className = "prompt-history";
      const summary = document.createElement("summary");
      summary.textContent = "Prompt History";
      promptDetails.appendChild(summary);
      layer.prompt_history.slice(0, 5).forEach((entry) => {
        const pre = document.createElement("pre");
        pre.textContent = entry.prompt;
        promptDetails.appendChild(pre);
      });
      layerSection.appendChild(promptDetails);
    }
    extras.appendChild(layerSection);

    if (layer.type === "text") {
      const section = document.createElement("div");
      section.className = "inspector-section";
      const heading = document.createElement("h3");
      heading.textContent = "Text";
      section.appendChild(heading);

      const textLabel = document.createElement("label");
      textLabel.textContent = "Words ";
      const textarea = document.createElement("textarea");
      textarea.rows = 4;
      textarea.value = layer.text ?? "";
      textarea.addEventListener("input", () => {
        pushHistory();
        layer.text = textarea.value;
        layer.name = textarea.value.trim().slice(0, 36) || "Text";
        layer.asset_path = null;
        renderLayer(layer);
        rebuildLayerPanel();
        noteSceneChange();
      });
      textLabel.appendChild(textarea);
      section.appendChild(textLabel);

      const fields = [
        { label: "Text", key: "text_color", type: "color", value: layer.text_color ?? "#154c84" },
        { label: "Outline", key: "stroke_color", type: "color", value: layer.stroke_color ?? "#F2C94C" },
        { label: "Box", key: "box_color", type: "color", value: layer.box_color ?? "#FFFFFF" },
      ];
      fields.forEach(({ label, key, type, value }) => {
        const lbl = document.createElement("label");
        lbl.textContent = label + " ";
        const input = document.createElement("input");
        input.type = type;
        input.value = value;
        input.addEventListener("input", () => {
          pushHistory();
          layer[key] = input.value;
          if (key !== "box_color") layer.asset_path = null;
          renderLayer(layer);
          noteSceneChange();
        });
        lbl.appendChild(input);
        section.appendChild(lbl);
      });

      const sizeLbl = document.createElement("label");
      sizeLbl.className = "text-size-control";
      sizeLbl.textContent = "Font Size ";
      const sizeRange = document.createElement("input");
      sizeRange.type = "range";
      sizeRange.min = "0.02";
      sizeRange.max = "0.12";
      sizeRange.step = "0.005";
      sizeRange.value = layer.font_size ?? 0.045;
      const sizeNumber = document.createElement("input");
      sizeNumber.type = "number";
      sizeNumber.min = "0.02";
      sizeNumber.max = "0.12";
      sizeNumber.step = "0.005";
      sizeNumber.value = layer.font_size ?? 0.045;
      sizeNumber.dataset.textControl = "font-size";
      const syncFontSize = (value) => {
        pushHistory();
        const next = Math.max(0.02, Math.min(0.12, Number(value) || 0.045));
        layer.font_size = next;
        sizeRange.value = String(next);
        sizeNumber.value = String(next);
        const hadGeneratedTextArt = !!layer.asset_path;
        layer.asset_path = null;
        if (hadGeneratedTextArt) {
          renderLayer(layer);
          selectLayer(layer.id);
        } else {
          updateLayerElement(layer);
        }
        noteSceneChange();
      };
      sizeRange.addEventListener("input", () => syncFontSize(sizeRange.value));
      sizeNumber.addEventListener("input", () => syncFontSize(sizeNumber.value));
      sizeLbl.appendChild(sizeRange);
      sizeLbl.appendChild(sizeNumber);
      section.appendChild(sizeLbl);

      const boxOpacityLbl = document.createElement("label");
      boxOpacityLbl.textContent = "Box Opacity ";
      const boxOpacityInput = document.createElement("input");
      boxOpacityInput.type = "range";
      boxOpacityInput.min = "0";
      boxOpacityInput.max = "1";
      boxOpacityInput.step = "0.05";
      boxOpacityInput.value = layer.box_opacity ?? 0.88;
      boxOpacityInput.addEventListener("input", () => {
        pushHistory();
        layer.box_opacity = Number(boxOpacityInput.value);
        updateLayerElement(layer);
        noteSceneChange();
      });
      boxOpacityLbl.appendChild(boxOpacityInput);
      section.appendChild(boxOpacityLbl);

      const alignLbl = document.createElement("label");
      alignLbl.textContent = "Align ";
      const alignSel = document.createElement("select");
      ["left", "center", "right"].forEach((align) => {
        const opt = document.createElement("option");
        opt.value = align;
        opt.textContent = align.charAt(0).toUpperCase() + align.slice(1);
        opt.selected = (layer.align ?? "center") === align;
        alignSel.appendChild(opt);
      });
      alignSel.addEventListener("input", () => {
        pushHistory();
        layer.align = alignSel.value;
        layer.asset_path = null;
        renderLayer(layer);
        noteSceneChange();
      });
      alignLbl.appendChild(alignSel);
      section.appendChild(alignLbl);

      const fontLbl = document.createElement("label");
      fontLbl.textContent = "Style ";
      const fontSel = document.createElement("select");
      [
        ["rounded", "Rounded"],
        ["storybook", "Storybook"],
        ["marker", "Marker"],
        ["comic", "Comic"],
      ].forEach(([value, label]) => {
        const opt = document.createElement("option");
        opt.value = value;
        opt.textContent = label;
        opt.selected = (layer.font_family ?? "rounded") === value;
        fontSel.appendChild(opt);
      });
      fontSel.addEventListener("input", () => {
        pushHistory();
        layer.font_family = fontSel.value;
        layer.asset_path = null;
        noteSceneChange();
      });
      fontLbl.appendChild(fontSel);
      section.appendChild(fontLbl);

      const promptLabel = document.createElement("label");
      promptLabel.textContent = "Style Prompt ";
      const promptArea = document.createElement("textarea");
      promptArea.rows = 2;
      promptArea.value = layer.style_prompt ?? "";
      promptArea.placeholder = "sparkly crystal robot letters";
      promptArea.addEventListener("input", () => {
        pushHistory();
        layer.style_prompt = promptArea.value;
        layer.asset_path = null;
        noteSceneChange();
      });
      promptLabel.appendChild(promptArea);
      section.appendChild(promptLabel);

      const genBtn = document.createElement("button");
      genBtn.type = "button";
      genBtn.dataset.action = "generate-text-art";
      genBtn.textContent = "Generate Text PNG";
      section.appendChild(genBtn);

      const variantBtn = document.createElement("button");
      variantBtn.type = "button";
      variantBtn.dataset.action = "generate-text-art-variant";
      variantBtn.textContent = "Generate Variant";
      section.appendChild(variantBtn);

      const clearBtn = document.createElement("button");
      clearBtn.type = "button";
      clearBtn.textContent = "Edit Live Text";
      clearBtn.addEventListener("click", () => {
        pushHistory();
        layer.asset_path = null;
        renderLayer(layer);
        selectLayer(layer.id);
        noteSceneChange();
      });
      section.appendChild(clearBtn);

      const applyAllBtn = document.createElement("button");
      applyAllBtn.type = "button";
      applyAllBtn.dataset.action = "apply-text-style-all";
      applyAllBtn.textContent = "Apply Text Style To All Pages";
      section.appendChild(applyAllBtn);

      const statusEl = document.createElement("p");
      statusEl.className = "gen-status";
      section.appendChild(statusEl);

      applyAllBtn.addEventListener("click", async () => {
        applyAllBtn.disabled = true;
        statusEl.textContent = "Applying text style across book…";
        try {
          await window._smToolbar?.saveScene?.();
          const resp = await fetch(`/api/scenes/${scene.book_slug}/${scene.page_number}/text-style/apply-all`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ layer_id: layer.id }),
          });
          if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
          const data = await resp.json();
          statusEl.textContent = `Applied to ${data.updated_count} pages.`;
        } catch (err) {
          statusEl.textContent = "Apply-all failed.";
          console.error("Apply text style failed:", err);
        } finally {
          applyAllBtn.disabled = false;
        }
      });

      async function submitTextArt(variant = false) {
        const text = (layer.text ?? "").trim();
        if (!text) {
          statusEl.textContent = "Type the page text first.";
          return;
        }
        if (variant) {
          layer.text_art_variant = Number(layer.text_art_variant ?? 0) + 1;
        } else {
          layer.text_art_variant = Number(layer.text_art_variant ?? 0);
        }
        const safeId = slugPart(layer.id, "text");
        const variantSuffix = layer.text_art_variant ? `_v${String(layer.text_art_variant).padStart(2, "0")}` : "";
        const outputPath = `assets/layers/text/${slugPart(scene.book_slug, "book")}/page_${String(scene.page_number).padStart(3, "0")}_${safeId}${variantSuffix}.png`;
        statusEl.textContent = "Generating transparent PNG…";
        genBtn.disabled = true;
        variantBtn.disabled = true;
        try {
          const resp = await fetch("/api/generate/text-art", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              text,
              output_path: outputPath,
              width_px: 1800,
              height_px: 520,
              dpi: scene.canvas?.dpi ?? 300,
              style: {
                font_family: layer.font_family ?? "rounded",
                font_size_px: Math.round(520 * Math.max(0.12, Math.min(0.55, (layer.font_size ?? 0.045) * 7))),
                fill_color: layer.text_color ?? "#154c84",
                stroke_color: layer.stroke_color ?? "#F2C94C",
                stroke_width: 10,
                shadow_color: "#394A63",
                shadow_opacity: 0.32,
                align: layer.align ?? "center",
                style_prompt: layer.style_prompt ?? "",
                variation_seed: layer.text_art_variant ?? 0,
              },
            }),
          });
          if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
          const { asset_path } = await resp.json();
          pushHistory();
          recordPrompt(layer, `${text}\n${layer.style_prompt ?? ""}`.trim(), "text_art");
          recordAssetVersion(layer, layer.asset_path, "previous");
          layer.asset_path = asset_path;
          recordAssetVersion(layer, asset_path, "text_art");
          layer.asset_version = Date.now();
          renderLayer(layer);
          selectLayer(layer.id);
          noteSceneChange();
          statusEl.textContent = "Done ✓ — transparent PNG applied.";
        } catch (err) {
          statusEl.textContent = "Text PNG generation failed.";
          console.error("Text art generation failed:", err);
        } finally {
          genBtn.disabled = false;
          variantBtn.disabled = false;
        }
      }

      genBtn.addEventListener("click", () => submitTextArt(false));
      variantBtn.addEventListener("click", () => submitTextArt(true));

      extras.appendChild(section);
    }

    if (layer.type === "lighting") {
      const section = document.createElement("div");
      section.className = "inspector-section";
      const heading = document.createElement("h3");
      heading.textContent = "Lighting";
      section.appendChild(heading);

      const fields = [
        { label: "Tint", type: "color", key: "tint_color", value: layer.tint_color ?? "#FFFFFF" },
      ];
      fields.forEach(({ label, type, key, value }) => {
        const lbl = document.createElement("label");
        lbl.textContent = label + " ";
        const input = document.createElement("input");
        input.type = type;
        input.dataset.light = key;
        input.value = value;
        input.addEventListener("input", () => {
          pushHistory();
          layer[key] = input.value;
          updateLayerElement(layer);
          noteSceneChange();
        });
        lbl.appendChild(input);
        section.appendChild(lbl);
      });

      // Blend mode select
      const blendLbl = document.createElement("label");
      blendLbl.textContent = "Blend ";
      const blendSel = document.createElement("select");
      blendSel.dataset.light = "blend_mode";
      ["multiply", "screen"].forEach((mode) => {
        const opt = document.createElement("option");
        opt.value = mode;
        opt.textContent = mode.charAt(0).toUpperCase() + mode.slice(1);
        opt.selected = layer.blend_mode === mode;
        blendSel.appendChild(opt);
      });
      blendSel.addEventListener("input", () => {
        pushHistory();
        layer.blend_mode = blendSel.value;
        updateLayerElement(layer);
        noteSceneChange();
      });
      blendLbl.appendChild(blendSel);
      section.appendChild(blendLbl);

      // Opacity range
      const opLbl = document.createElement("label");
      opLbl.textContent = "Opacity ";
      const opInput = document.createElement("input");
      opInput.type = "range";
      opInput.min = "0";
      opInput.max = "1";
      opInput.step = "0.01";
      opInput.dataset.light = "opacity";
      opInput.value = layer.opacity ?? 0;
      opInput.addEventListener("input", () => {
        pushHistory();
        layer.opacity = Number(opInput.value);
        updateLayerElement(layer);
        noteSceneChange();
      });
      opLbl.appendChild(opInput);
      section.appendChild(opLbl);

      extras.appendChild(section);
      return;
    }

    if (layer.type === "character" || layer.type === "props") {
      const shadow = layer.shadow ?? {};
      const section = document.createElement("div");
      section.className = "inspector-section";
      const heading = document.createElement("h3");
      heading.textContent = "Shadow";
      section.appendChild(heading);

      // Enabled checkbox
      const enabledLbl = document.createElement("label");
      const enabledChk = document.createElement("input");
      enabledChk.type = "checkbox";
      enabledChk.dataset.shadow = "enabled";
      enabledChk.checked = !!shadow.enabled;
      enabledChk.addEventListener("input", () => {
        pushHistory();
        layer.shadow = layer.shadow ?? {};
        layer.shadow.enabled = enabledChk.checked;
        updateLayerElement(layer);
        noteSceneChange();
      });
      enabledLbl.appendChild(enabledChk);
      enabledLbl.appendChild(document.createTextNode(" Enabled"));
      section.appendChild(enabledLbl);

      // Numeric shadow fields
      [
        { label: "Angle", key: "angle", value: shadow.angle ?? 270, min: 0, max: 360 },
        { label: "Distance", key: "distance", value: shadow.distance ?? 12, min: 0 },
        { label: "Blur", key: "blur", value: shadow.blur ?? 8, min: 0 },
      ].forEach(({ label, key, value, min, max }) => {
        const lbl = document.createElement("label");
        lbl.textContent = label + " ";
        const input = document.createElement("input");
        input.type = "number";
        input.step = "1";
        input.min = String(min ?? 0);
        if (max !== undefined) input.max = String(max);
        input.dataset.shadow = key;
        input.value = String(value);
        input.addEventListener("input", () => {
          pushHistory();
          layer.shadow = layer.shadow ?? {};
          layer.shadow[key] = Number(input.value);
          updateLayerElement(layer);
          noteSceneChange();
        });
        lbl.appendChild(input);
        section.appendChild(lbl);
      });

      // Opacity range
      const opLbl = document.createElement("label");
      opLbl.textContent = "Opacity ";
      const opInput = document.createElement("input");
      opInput.type = "range";
      opInput.min = "0";
      opInput.max = "1";
      opInput.step = "0.01";
      opInput.dataset.shadow = "opacity";
      opInput.value = String(shadow.opacity ?? 0.3);
      opInput.addEventListener("input", () => {
        pushHistory();
        layer.shadow = layer.shadow ?? {};
        layer.shadow.opacity = Number(opInput.value);
        updateLayerElement(layer);
        noteSceneChange();
      });
      opLbl.appendChild(opInput);
      section.appendChild(opLbl);

      extras.appendChild(section);
    }

    if (layer.type === "character") {
      const slug = layer.character_slug ?? "niko";
      const requestedLayerId = layer.id;
      fetch(`/api/assets/characters/${slug}/poses`)
        .then((r) => r.json())
        .then((poses) => {
          if (selectedId !== requestedLayerId) return;
          if (!poses.length) return;
          const section = document.createElement("div");
          section.className = "inspector-section";
          const heading = document.createElement("h3");
          heading.textContent = "Pose";
          section.appendChild(heading);
          const grid = document.createElement("div");
          grid.className = "pose-grid";
          poses.forEach((pose) => {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "pose-btn";
            btn.textContent = pose.label;
            btn.classList.toggle("is-active", layer.pose === pose.id);
            btn.addEventListener("click", () => {
              pushHistory();
              layer.pose = pose.id;
              const variant = layer.lighting_variant ?? scene.lighting_brief ?? "ambient_soft";
              layer.asset_path = pose.asset_path ?? `assets/layers/characters/${slug}/niko_${pose.id}.png`;
              layer.lighting_variant = variant;
              if (pose.rig) layer.rig = structuredClone(pose.rig);
              section.querySelectorAll(".pose-btn").forEach((b) => b.classList.remove("is-active"));
              btn.classList.add("is-active");
              renderLayer(layer);
              renderBones(layer);
              noteSceneChange();
            });
            grid.appendChild(btn);
          });
          section.appendChild(grid);
          (poseExtras ?? extras).appendChild(section);
        });
    }

    if (["background", "midground", "foreground", "character", "props"].includes(layer.type)) {
      const genSection = document.createElement("div");
      genSection.className = "inspector-section";
      const genHeading = document.createElement("h3");
      genHeading.textContent = "Generate";
      genSection.appendChild(genHeading);

      const defaultPrompt = layer.type === "character"
        ? characterPrompt(layer)
        : `${layer.name}, ${layer.type} layer, ${scene.lighting_brief ?? "ambient"} lighting`;

      const textarea = document.createElement("textarea");
      textarea.rows = 4;
      textarea.dataset.genPrompt = "";
      textarea.value = layer.prompt_history?.[0]?.prompt ?? defaultPrompt;
      genSection.appendChild(textarea);

      const genBtn = document.createElement("button");
      genBtn.type = "button";
      genBtn.dataset.action = "generate";
      genBtn.textContent = "Generate Image";
      genSection.appendChild(genBtn);

      const statusEl = document.createElement("p");
      statusEl.className = "gen-status";
      statusEl.dataset.genStatus = "";
      genSection.appendChild(statusEl);

      genBtn.addEventListener("click", () => {
        const prompt = textarea.value.trim();
        if (!prompt) return;

        const outputPath = layer.asset_path ?? defaultGenerationPath(layer);
        recordPrompt(layer, prompt, layer.type);

        setGenerationStatus(layer, statusEl, "Submitting...");
        fetch("/api/generate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            layer_id: layer.id,
            layer_type: layer.type,
            prompt,
            output_path: outputPath,
            lighting_variant: scene.lighting_brief ?? "ambient_soft",
          }),
        })
          .then((r) => {
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            return r.json();
          })
          .then(({ job_id }) => {
            setGenerationStatus(layer, statusEl, "Running...");
            pollJob(job_id, layer, outputPath, statusEl);
          })
          .catch(() => { setGenerationStatus(layer, statusEl, "Error submitting job."); });
      });

      extras.appendChild(genSection);
    }
  }

  function selectLayer(id) {
    selectedId = id;
    const selected = findLayer(id);
    if (!selected) selectedId = null;
    scene.layers.forEach(updateLayerElement);
    layerList.querySelectorAll(".layer-button").forEach((btn) => {
      btn.classList.toggle("is-active", btn.dataset.layerId === id);
    });
    if (deleteLayerButton) {
      deleteLayerButton.disabled = !canDeleteLayer(selected);
    }

    syncTransformControls(selected);

    renderBones(selected);
    renderInspectorExtras(selected);
    updateSnapReadout(selected);
  }

  function refreshSceneView() {
    sortedForStage().forEach(renderLayer);
    rebuildLayerPanel();
    selectLayer(selectedId);
    renderQa();
  }

  function nextZIndex() {
    return Math.max(...scene.layers.map((layer) => Number(layer.z_index ?? 0)), 0) + 1;
  }

  function previousZIndex() {
    return Math.min(...scene.layers.map((layer) => Number(layer.z_index ?? 0)), 0) - 1;
  }

  function duplicateSelectedLayer() {
    const layer = findLayer(selectedId);
    if (!layer || layer.type === "camera" || layer.type === "lighting") return;
    pushHistory();
    const copy = structuredClone(layer);
    copy.id = `${layer.id}_copy_${Date.now()}`;
    copy.name = `${layer.name} Copy`;
    copy.locked = false;
    copy.z_index = nextZIndex();
    copy.transform = copy.transform ?? {};
    copy.transform.x = Math.min(0.95, (copy.transform.x ?? 0.5) + 0.03);
    copy.transform.y = Math.min(0.95, (copy.transform.y ?? 0.5) + 0.03);
    scene.layers.push(copy);
    selectedId = copy.id;
    refreshSceneView();
    noteSceneChange();
  }

  function applyLayerAction(action) {
    const layer = findLayer(selectedId);
    if (!layer) return;
    if (action === "duplicate") {
      duplicateSelectedLayer();
      return;
    }
    pushHistory();
    if (action === "toggle-visible") {
      layer.visible = layer.visible === false;
    } else if (action === "toggle-lock") {
      if (layer.type !== "camera") layer.locked = !layer.locked;
    } else if (action === "front") {
      layer.z_index = nextZIndex();
    } else if (action === "back") {
      layer.z_index = previousZIndex();
    }
    refreshSceneView();
    noteSceneChange();
  }

  function deleteSelectedLayer() {
    const layer = findLayer(selectedId);
    if (!canDeleteLayer(layer)) return;

    pushHistory();
    if (layer.id === "char_niko") {
      scene.suppress_hackster_niko = true;
      scene.uses_hackster_niko = false;
    }
    scene.layers = scene.layers.filter((item) => item.id !== layer.id);
    stage.querySelector(`[data-layer-id="${layer.id}"]`)?.remove();
    rebuildLayerPanel();

    const next = sortedForPanel().find((item) => item.type !== "camera") ?? sortedForPanel()[0];
    if (next) {
      selectLayer(next.id);
    } else {
      selectLayer(null);
    }
    renderQa();
    noteSceneChange();
  }

  async function removeNikoFromBook() {
    if (!confirm("Remove Hackster Niko from every page in this book? This saves the cleanup immediately.")) return;
    if (stageActionStatus) stageActionStatus.textContent = "Removing Niko...";
    try {
      const response = await fetch(`/api/books/${encodeURIComponent(scene.book_slug)}/remove-hackster-niko`, {
        method: "POST",
        headers: { "Accept": "application/json" },
      });
      if (!response.ok) throw new Error(await response.text());
      const payload = await response.json();
      pushHistory();
      scene.suppress_hackster_niko = true;
      scene.uses_hackster_niko = false;
      scene.layers = scene.layers.filter((layer) => layer.id !== "char_niko" && (layer.name || "").trim().toLowerCase() !== "hackster niko");
      if (selectedId === "char_niko") selectedId = null;
      refreshSceneView();
      setDirty(false);
      if (stageActionStatus) {
        stageActionStatus.textContent = `Removed Niko from ${payload.pages_updated} pages.`;
      }
    } catch (error) {
      if (stageActionStatus) stageActionStatus.textContent = "Could not remove Niko.";
      console.error("Remove Niko failed:", error);
    }
  }

  // ── Drag ──────────────────────────────────────────────────────────────────

  let dragging = null;
  let resizing = null;

  stage.addEventListener("pointerdown", (event) => {
    const handle = event.target.closest(".story-resize-handle");
    if (handle) {
      const el = handle.closest(".story-layer");
      const layer = el?.dataset.layerId ? findLayer(el.dataset.layerId) : null;
      if (!layer || !canResizeLayer(layer)) return;
      event.preventDefault();
      event.stopPropagation();
      selectLayer(layer.id);
      pushHistory();
      const rect = stage.getBoundingClientRect();
      resizing = {
        layer,
        rect,
        startX: event.clientX,
        startY: event.clientY,
        startWidth: layer.transform?.width ?? 0.3,
        startHeight: layer.transform?.height ?? 0.3,
      };
      el.setPointerCapture(event.pointerId);
      return;
    }

    const el = event.target.closest(".story-layer");
    if (!el || !el.dataset.layerId) return;
    const layer = findLayer(el.dataset.layerId);
    if (!layer || layer.type === "lighting" || layer.type === "camera") return;
    selectLayer(el.dataset.layerId);
    if (layer.locked) return;
    pushHistory();
    const rect = stage.getBoundingClientRect();
    dragging = { layer, rect };
    el.setPointerCapture(event.pointerId);
  });

  stage.addEventListener("pointermove", (event) => {
    if (resizing) {
      const t = resizing.layer.transform ?? {};
      const dx = (event.clientX - resizing.startX) / resizing.rect.width;
      const dy = (event.clientY - resizing.startY) / resizing.rect.height;
      const nextWidth = clampSize(snapValue(resizing.startWidth + dx * 2));
      t.width = nextWidth;
      if (resizing.layer.preserve_aspect) {
        const ratio = resizing.startHeight / Math.max(0.01, resizing.startWidth);
        t.height = clampSize(nextWidth * ratio);
      } else {
        t.height = clampSize(snapValue(resizing.startHeight + dy * 2));
      }
      resizing.layer.transform = t;
      updateLayerElement(resizing.layer);
      syncTransformControls(resizing.layer);
      updateSnapReadout(resizing.layer);
      noteSceneChange();
      return;
    }

    if (!dragging) return;
    const t = dragging.layer.transform ?? {};
    t.x = clamp01(snapValue((event.clientX - dragging.rect.left) / dragging.rect.width));
    t.y = clamp01(snapValue((event.clientY - dragging.rect.top) / dragging.rect.height));
    dragging.layer.transform = t;
    updateLayerElement(dragging.layer);
    syncTransformControls(dragging.layer);
    updateSnapReadout(dragging.layer);
    noteSceneChange();
  });

  stage.addEventListener("pointerup", () => {
    dragging = null;
    resizing = null;
  });

  // ── Inspector controls ────────────────────────────────────────────────────

  controls.forEach((input) => {
    input.addEventListener("input", () => {
      const layer = findLayer(selectedId);
      if (!layer) return;
      pushHistory();
      layer.transform = layer.transform ?? {};
      const previousWidth = layer.transform.width ?? 0.3;
      const previousHeight = layer.transform.height ?? 0.3;
      const aspect = previousHeight / Math.max(0.01, previousWidth);
      const key = input.dataset.control;
      const rawValue = Number(input.value);
      layer.transform[key] = ["x", "y", "width", "height"].includes(key) ? snapValue(rawValue) : rawValue;
      if (layer.preserve_aspect && input.dataset.control === "width") {
        layer.transform.height = Number(input.value) * aspect;
      }
      if (layer.preserve_aspect && input.dataset.control === "height") {
        layer.transform.width = Number(input.value) / Math.max(0.01, aspect);
      }
      updateLayerElement(layer);
      syncTransformControls(layer);
      updateSnapReadout(layer);
      noteSceneChange();
      // Camera movement triggers parallax update on all layers
      if (layer.type === "camera") {
        scene.layers.forEach(updateLayerElement);
      }
    });
  });

  preserveAspectOption?.addEventListener("input", () => {
    const layer = findLayer(selectedId);
    if (!layer) return;
    pushHistory();
    layer.preserve_aspect = preserveAspectOption.checked;
    syncTransformControls(layer);
    noteSceneChange();
  });

  root.querySelectorAll("[data-layer-action]").forEach((button) => {
    button.addEventListener("click", () => applyLayerAction(button.dataset.layerAction));
  });

  root.querySelectorAll("[data-transform-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const layer = findLayer(selectedId);
      if (!layer || !layer.transform || !canResizeLayer(layer)) return;
      pushHistory();
      const t = layer.transform;
      if (button.dataset.transformAction === "snap-safe") {
        const safe = safeMarginPct();
        t.x = snapValue(Math.min(1 - safe - (t.width ?? 0.3) / 2, Math.max(safe + (t.width ?? 0.3) / 2, t.x ?? 0.5)));
        t.y = snapValue(Math.min(1 - safe - (t.height ?? 0.3) / 2, Math.max(safe + (t.height ?? 0.3) / 2, t.y ?? 0.5)));
      } else if (button.dataset.transformAction === "align-center") {
        t.x = snapValue(0.5);
      } else if (button.dataset.transformAction === "reset") {
        t.x = snapValue(0.5);
        t.y = snapValue(layer.type === "text" ? 0.82 : 0.5);
        t.scale = 1;
        t.rotation = 0;
        t.opacity = 1;
      }
      updateLayerElement(layer);
      syncTransformControls(layer);
      updateSnapReadout(layer);
      noteSceneChange();
    });
  });

  document.querySelectorAll("[data-guide]").forEach((input) => {
    input.addEventListener("input", () => {
      stage.classList.toggle(`show-${input.dataset.guide}`, input.checked);
    });
  });

  gridToggle?.addEventListener("input", () => {
    stage.classList.toggle("show-grid", gridToggle.checked);
  });

  gridSizeControl?.addEventListener("input", () => {
    const size = gridSize();
    stage.style.setProperty("--grid-step", `${size * 100}%`);
    updateSnapReadout(findLayer(selectedId));
  });

  snapToggle?.addEventListener("input", () => updateSnapReadout(findLayer(selectedId)));

  viewportButtons.forEach((button) => {
    button.addEventListener("click", () => setViewportMode(button.dataset.viewportMode));
  });

  undoButton?.addEventListener("click", undoSceneChange);
  redoButton?.addEventListener("click", redoSceneChange);

  document.addEventListener("keydown", (event) => {
    const active = document.activeElement;
    const isTyping = active?.matches?.("input, textarea, select, [contenteditable='true']");
    if (!isTyping && event.key === "Delete") {
      event.preventDefault();
      deleteSelectedLayer();
      return;
    }
    const isModified = event.metaKey || event.ctrlKey;
    if (!isModified) return;
    const key = event.key.toLowerCase();
    if (key === "s") {
      event.preventDefault();
      window._smToolbar?.saveScene?.();
      return;
    }
    if (key !== "z") return;
    if (isTyping) return;
    event.preventDefault();
    if (event.shiftKey) redoSceneChange();
    else undoSceneChange();
  });

  window.addEventListener("beforeunload", (event) => {
    if (!isDirty) return;
    event.preventDefault();
    event.returnValue = "";
  });

  async function setPageStatus(status) {
    pushHistory();
    scene.status = status;
    scene.approval = scene.approval ?? {};
    scene.approval.approved = status === "approved";
    scene.approval.approved_at = status === "approved" ? nowIso() : null;
    syncPageStatus();
    noteSceneChange();
    try {
      await fetch(`/api/scenes/${scene.book_slug}/${scene.page_number}/status`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status, approved_by: "Hackster Studio" }),
      });
    } catch (err) {
      console.error("Status update failed:", err);
    }
  }

  pageStatusControl?.addEventListener("input", () => setPageStatus(pageStatusControl.value));
  document.querySelector("[data-action='mark-needs-edit']")?.addEventListener("click", () => setPageStatus("needs_edit"));
  document.querySelector("[data-action='approve-page']")?.addEventListener("click", () => setPageStatus("approved"));

  async function regenerateCurrentPage(part) {
    const statusEl = document.querySelector("[data-page-regen-status]");
    const buttons = Array.from(document.querySelectorAll("[data-page-regenerate]"));
    const label = part === "all" ? "story, prompt, and image" : part;
    buttons.forEach((button) => { button.disabled = true; });
    if (statusEl) statusEl.textContent = `Regenerating ${label}...`;
    try {
      if (part === "story" || part === "prompt") {
        await window._smToolbar?.saveScene?.();
        const endpoint = part === "story" ? "regenerate-story" : "regenerate-prompt";
        const resp = await fetch(`/api/books/${scene.book_slug}/pages/${scene.page_number}/${endpoint}`, {
          method: "POST",
          headers: { "Accept": "application/json" },
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        if (statusEl) statusEl.textContent = part === "story"
          ? "Story and prompt regenerated. Reloading page..."
          : `Prompt regenerated: ${data.prompt_path}`;
        if (part === "story") window.location.reload();
        return;
      }

      const endpoint = part === "all" ? "regenerate-all" : "regenerate-image";
      if (part === "image") await window._smToolbar?.saveScene?.();
      if (typeof showBookGenerationProgress === "function") showBookGenerationProgress();
      const resp = await fetch(`/api/books/${scene.book_slug}/pages/${scene.page_number}/${endpoint}`, {
        method: "POST",
        headers: { "Accept": "application/json" },
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const payload = await resp.json();
      if (payload.job_id && typeof startBookGenerationJobPolling === "function") {
        if (typeof appendBookGenerationLog === "function") {
          appendBookGenerationLog(`Browser: page ${scene.page_number} ${label} regeneration job accepted: ${payload.job_id}`);
        }
        const backgroundLayer = findLayer("book_illustration");
        if (backgroundLayer) {
          backgroundLayer.generation_status = `Regenerating page ${scene.page_number} image...`;
          renderLayer(backgroundLayer);
        }
        startBookGenerationJobPolling(
          payload.job_id,
          `/story-maker?book_slug=${scene.book_slug}&page=${scene.page_number}&refresh=${Date.now()}`
        );
      }
      if (statusEl) statusEl.textContent = `Image job started for page ${scene.page_number}.`;
    } catch (err) {
      if (statusEl) statusEl.textContent = `Regeneration failed: ${err}`;
      console.error("Page regeneration failed:", err);
    } finally {
      buttons.forEach((button) => { button.disabled = false; });
    }
  }

  document.querySelectorAll("[data-page-regenerate]").forEach((button) => {
    button.addEventListener("click", () => regenerateCurrentPage(button.dataset.pageRegenerate));
  });

  // ── Init ──────────────────────────────────────────────────────────────────

  // Render stage (low z_index first)
  setViewportMode(localStorage.getItem("storyMakerViewportMode") || "default");
  stage.style.setProperty("--grid-step", `${gridSize() * 100}%`);
  sortedForStage().forEach(renderLayer);
  // Build panel (high z_index first)
  rebuildLayerPanel();
  // Select first non-camera layer
  const firstNonCamera = sortedForPanel().find((l) => l.type !== "camera");
  if (firstNonCamera) selectLayer(firstNonCamera.id);
  syncPageStatus();
  updateHistoryButtons();
  setDirty(false);
  deleteLayerButton?.addEventListener("click", deleteSelectedLayer);
  document.querySelector("[data-action='remove-niko-book']")?.addEventListener("click", removeNikoFromBook);

  // Expose scene and helpers for later tasks (Task 7/8/9 add toolbar, browser, inspector)
  window._sm = {
    scene,
    selectLayer,
    findLayer,
    deleteSelectedLayer,
    updateLayerElement,
    renderLayer,
    rebuildLayerPanel,
    renderInspectorExtras,
    renderQa,
    addPlannedCharacterLayer,
    undoSceneChange,
    redoSceneChange,
    setDirty,
  };
  initToolbar(scene);
  initAssetBrowser(scene, window._sm);
}

function initAssetBrowser(scene, callbacks) {
  const dialog = document.querySelector("[data-asset-browser]");
  const tabsEl = document.querySelector("[data-asset-tabs]");
  const gridEl = document.querySelector("[data-asset-grid]");
  if (!dialog) return;

  const TAB_LABELS = {
    backgrounds: "Backgrounds",
    midground: "Midground",
    foreground: "Foreground",
    characters: "Characters",
    props: "Props",
    text: "Text",
    generated: "Generated",
  };

  const LAYER_TYPE_MAP = {
    backgrounds: "background",
    midground: "midground",
    foreground: "foreground",
    props: "props",
    text: "text",
    generated: "background",
  };

  const PARALLAX_MAP = {
    background: 0.1,
    midground: 0.4,
    foreground: 1.5,
    character: 1.0,
    props: 1.0,
  };

  let currentTab = "backgrounds";
  let assets = {};

  async function loadAssets() {
    const resp = await fetch("/api/assets");
    assets = await resp.json();
    renderTabs();
    renderGrid(currentTab);
  }

  function renderTabs() {
    tabsEl.innerHTML = "";
    Object.keys(TAB_LABELS).forEach((key) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = TAB_LABELS[key];
      btn.classList.toggle("is-active", key === currentTab);
      btn.addEventListener("click", () => {
        currentTab = key;
        tabsEl.querySelectorAll("button").forEach((b) => b.classList.remove("is-active"));
        btn.classList.add("is-active");
        renderGrid(key);
      });
      tabsEl.appendChild(btn);
    });
  }

  function renderGrid(tab) {
    gridEl.innerHTML = "";
    const items = tab === "characters"
      ? Object.values(assets.characters ?? {}).flat()
      : (assets[tab] ?? []);
    const planned = tab === "characters"
      ? (Array.isArray(scene.planned_characters) ? scene.planned_characters : [])
      : [];

    // Include hidden_objects under props tab
    const extra = tab === "props" ? (assets.hidden_objects ?? []) : [];
    if (planned.length) {
      const plannedTitle = document.createElement("div");
      plannedTitle.className = "asset-section-title";
      plannedTitle.textContent = "Story Cast";
      gridEl.appendChild(plannedTitle);

      planned.forEach((character) => {
        const assetPath = character.asset_paths?.[0] || null;
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "asset-thumb asset-thumb--planned";
        const avatar = document.createElement("span");
        avatar.className = "asset-planned-avatar";
        if (assetPath) {
          const img = document.createElement("img");
          img.src = `/project-assets/${assetPath}`;
          img.alt = character.name;
          img.onerror = () => {
            img.remove();
            avatar.textContent = (character.name || "?").slice(0, 2).toUpperCase();
          };
          avatar.appendChild(img);
        } else {
          avatar.textContent = (character.name || "?").slice(0, 2).toUpperCase();
        }
        const label = document.createElement("span");
        label.textContent = character.name || character.slug || "Character";
        const meta = document.createElement("small");
        meta.textContent = assetPath ? "Generated art available" : "Needs generated art";
        btn.append(avatar, label, meta);
        btn.addEventListener("click", () => callbacks.addPlannedCharacterLayer?.(character, assetPath));
        gridEl.appendChild(btn);
      });
    }

    if (items.length || extra.length) {
      const libraryTitle = document.createElement("div");
      libraryTitle.className = "asset-section-title";
      libraryTitle.textContent = tab === "characters" ? "Character Art" : "Asset Library";
      gridEl.appendChild(libraryTitle);
    }

    [...items, ...extra].forEach((assetPath) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "asset-thumb";
      const filename = assetPath.split("/").pop();
      const img = document.createElement("img");
      img.src = `/project-assets/${assetPath}`;
      img.alt = filename;
      img.onerror = () => { img.style.display = "none"; };
      const label = document.createElement("span");
      label.textContent = filename.replace(/_/g, " ").replace(".png", "");
      btn.appendChild(img);
      btn.appendChild(label);
      btn.addEventListener("click", () => addLayer(tab, assetPath));
      gridEl.appendChild(btn);
    });

    if (!items.length && !extra.length && !planned.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No assets yet — generate some first.";
      gridEl.appendChild(empty);
    }
  }

  function addLayer(tab, assetPath) {
    const layerType = tab === "characters" ? "character" : (LAYER_TYPE_MAP[tab] ?? "props");
    const filename = assetPath.split("/").pop().replace(".png", "");
    const id = `${layerType}_${Date.now()}`;
    const zIndexBase = { background: 0, midground: 2, character: 3, props: 4, text: 12, foreground: 8 };
    const sameTypeCount = scene.layers.filter((layer) => layer.type === layerType).length;

    const newLayer = {
      id,
      name: filename.replace(/_/g, " "),
      type: layerType,
      z_index: Number(((zIndexBase[layerType] ?? 3) + (sameTypeCount * 0.01)).toFixed(2)),
      parallax_factor: PARALLAX_MAP[layerType] ?? 1.0,
      asset_path: assetPath,
      transform: {
        x: 0.5, y: 0.5,
        width: layerType === "background" ? 1.5 : (layerType === "text" ? 0.72 : 0.3),
        height: layerType === "background" ? 1.5 : (layerType === "text" ? 0.18 : 0.3),
        scale: 1.0, rotation: 0, opacity: 1,
      },
    };

    if (layerType === "character") {
      newLayer.character_slug = assetPath.split("/").slice(-2, -1)[0] ?? "unknown";
      newLayer.pose = "standing_neutral";
      newLayer.rig = null;
      newLayer.shadow = {
        enabled: false,
        angle: LIGHTING_SHADOW_ANGLES[scene.lighting_brief] ?? 270,
        distance: 12, blur: 8, opacity: 0.3,
      };
    }

    if (layerType === "props") {
      newLayer.shadow = {
        enabled: false,
        angle: LIGHTING_SHADOW_ANGLES[scene.lighting_brief] ?? 270,
        distance: 8, blur: 6, opacity: 0.25,
      };
    }

    if (layerType === "text") {
      newLayer.text = filename.replace(/_/g, " ");
      newLayer.font_size = 0.045;
      newLayer.text_color = "#154c84";
      newLayer.stroke_color = "#F2C94C";
      newLayer.box_color = "#FFFFFF";
      newLayer.box_opacity = 0.0;
      newLayer.align = "center";
      newLayer.font_family = "rounded";
      newLayer.style_prompt = "";
      newLayer.text_art_variant = 0;
      newLayer.preserve_aspect = false;
    }

    scene.layers.push(newLayer);
    callbacks.renderLayer(newLayer);
    callbacks.rebuildLayerPanel();
    callbacks.selectLayer(newLayer.id);
    dialog.close();
  }

  document.querySelector("[data-action='add-layer']")?.addEventListener("click", () => {
    loadAssets();
    dialog.showModal();
  });

  document.querySelector("[data-close-browser]")?.addEventListener("click", () => dialog.close());
}

function initToolbar(scene) {
  const bookSlug = scene.book_slug;
  const pageNumber = scene.page_number;
  let textVisible = true;

  function addTextLayer() {
    const sameTypeCount = scene.layers.filter((layer) => layer.type === "text").length;
    const layer = {
      id: `text_${Date.now()}`,
      name: `Page Text ${sameTypeCount + 1}`,
      type: "text",
      z_index: Number((20 + sameTypeCount * 0.01).toFixed(2)),
      parallax_factor: 1.0,
      text: "Every problem has a clever fix!",
      font_size: 0.045,
      text_color: "#154c84",
      stroke_color: "#F2C94C",
      box_color: "#FFFFFF",
      box_opacity: 0.88,
      align: "center",
      font_family: "rounded",
      style_prompt: "",
      text_art_variant: 0,
      preserve_aspect: false,
      transform: {
        x: 0.5,
        y: 0.82,
        width: 0.76,
        height: 0.16,
        scale: 1.0,
        rotation: 0,
        opacity: 1,
      },
    };
    scene.layers.push(layer);
    window._sm?.renderLayer(layer);
    window._sm?.rebuildLayerPanel();
    window._sm?.selectLayer(layer.id);
  }

  async function saveScene() {
    const btn = document.querySelector("[data-action='save']");
    btn.textContent = "Saving…";
    btn.disabled = true;
    try {
      window._sm?.renderQa?.();
      const resp = await fetch(`/api/scenes/${bookSlug}/${pageNumber}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(scene),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      window._sm?.setDirty?.(false);
      btn.textContent = "Saved ✓";
      setTimeout(() => { btn.textContent = "Save"; btn.disabled = false; }, 1500);
    } catch (err) {
      btn.textContent = "Error";
      btn.disabled = false;
      console.error("Save failed:", err);
      throw err;
    }
  }

  async function exportPage(mode) {
    // Save first so the on-disk scene matches current canvas
    try {
      await saveScene();
    } catch {
      return;  // save already showed error state
    }
    const btn = document.querySelector(`[data-action='export-${mode}']`);
    const original = btn.textContent;
    btn.textContent = "Exporting…";
    btn.disabled = true;
    try {
      const resp = await fetch(`/api/export/${bookSlug}/${pageNumber}?mode=${mode}`, {
        method: "POST",
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const { output_path } = await resp.json();
      btn.textContent = "Done ✓";
      setTimeout(() => { btn.textContent = original; btn.disabled = false; }, 2000);
      console.info("Exported to:", output_path);
    } catch (err) {
      btn.textContent = "Error";
      btn.disabled = false;
      console.error("Export failed:", err);
    }
  }

  async function promotePage() {
    try {
      await saveScene();
    } catch {
      return;
    }
    const btn = document.querySelector("[data-action='promote-flat']");
    const original = btn.textContent;
    btn.textContent = "Promoting…";
    btn.disabled = true;
    try {
      const resp = await fetch(`/api/promote/${bookSlug}/${pageNumber}?mode=flat`, {
        method: "POST",
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      btn.textContent = "Promoted ✓";
      setTimeout(() => { btn.textContent = original; btn.disabled = false; }, 2000);
    } catch (err) {
      btn.textContent = "Error";
      btn.disabled = false;
      console.error("Promote failed:", err);
    }
  }

  function toggleText() {
    textVisible = !textVisible;
    document.querySelectorAll(".story-layer--text").forEach((el) => {
      el.style.visibility = textVisible ? "visible" : "hidden";
    });
  }

  document.querySelector("[data-action='save']")?.addEventListener("click", saveScene);
  document.querySelector("[data-action='export-flat']")?.addEventListener("click", () => exportPage("flat"));
  document.querySelector("[data-action='export-draft']")?.addEventListener("click", () => exportPage("draft"));
  document.querySelector("[data-action='promote-flat']")?.addEventListener("click", promotePage);
  document.querySelector("[data-action='add-text']")?.addEventListener("click", addTextLayer);
  document.querySelector("[data-action='toggle-text']")?.addEventListener("click", toggleText);
  window._smToolbar = { saveScene, exportPage, promotePage };
}

initStoryMaker();

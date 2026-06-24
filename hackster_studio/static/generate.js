/**
 * Generate page — DGX image generation form, job status polling, gallery.
 */

(() => {
  "use strict";

  // ── State ──────────────────────────────────────────────────────────────────

  /** @type {Map<string, {prompt: string, status: string, asset_path: string|null, error: string}>} */
  const jobs = new Map();
  let pollTimer = null;

  // ── DOM refs ───────────────────────────────────────────────────────────────

  const prefixEl    = /** @type {HTMLTextAreaElement} */ (document.getElementById("gen-prefix"));
  const promptEl    = /** @type {HTMLTextAreaElement} */ (document.getElementById("gen-prompt"));
  const filenameEl  = /** @type {HTMLInputElement}    */ (document.getElementById("gen-filename"));
  const submitBtn   = /** @type {HTMLButtonElement}   */ (document.getElementById("gen-submit"));
  const errorEl     = /** @type {HTMLElement}         */ (document.getElementById("gen-error"));
  const connStatusEl = /** @type {HTMLElement}        */ (document.getElementById("gen-conn-status"));
  const jobsListEl  = /** @type {HTMLElement}         */ (document.getElementById("gen-jobs-list"));
  const badgeEl     = /** @type {HTMLElement}         */ (document.getElementById("gen-jobs-badge"));
  const galleryEl   = /** @type {HTMLElement}         */ (document.getElementById("gen-gallery"));
  const filtersEl   = /** @type {HTMLElement}         */ (document.getElementById("gen-book-filters"));
  const gallerySummaryEl = /** @type {HTMLElement}    */ (document.getElementById("gen-gallery-summary"));
  const refreshBtn  = /** @type {HTMLButtonElement}   */ (document.getElementById("gen-refresh"));
  const lightbox    = /** @type {HTMLDialogElement}   */ (document.getElementById("gen-lightbox"));
  const lbImg       = /** @type {HTMLImageElement}    */ (document.getElementById("gen-lightbox-img"));
  const lbCaption   = /** @type {HTMLElement}         */ (document.getElementById("gen-lightbox-caption"));
  const lbClose     = /** @type {HTMLButtonElement}   */ (document.getElementById("gen-lightbox-close"));
  const currentBookSlug = galleryEl?.dataset.currentBookSlug || "";
  let selectedBookSlug = "";
  let lastGallery = { paths: [], bookGroups: [] };

  // ── Filename auto-generation ───────────────────────────────────────────────

  function slugFromPrompt(text) {
    return text
      .toLowerCase()
      .replace(/[^a-z0-9 ]/g, "")
      .trim()
      .split(/\s+/)
      .slice(0, 6)
      .join("_")
      .slice(0, 48) || "gen";
  }

  function timestampSuffix() {
    const now = new Date();
    return [
      now.getFullYear(),
      String(now.getMonth() + 1).padStart(2, "0"),
      String(now.getDate()).padStart(2, "0"),
      "_",
      String(now.getHours()).padStart(2, "0"),
      String(now.getMinutes()).padStart(2, "0"),
      String(now.getSeconds()).padStart(2, "0"),
    ].join("");
  }

  function buildOutputPath(customName) {
    const base = customName.trim()
      ? customName.trim().replace(/\.png$/i, "")
      : `${slugFromPrompt(promptEl.value)}_${timestampSuffix()}`;
    return `data/generated/pages/${base}.png`;
  }

  // ── Job submission ─────────────────────────────────────────────────────────

  async function submitGeneration() {
    const userPrompt = promptEl.value.trim();
    if (!userPrompt) {
      showError("Prompt is required.");
      return;
    }

    const prefix = prefixEl ? prefixEl.value.trim() : "";
    const prompt = prefix ? `${prefix}, ${userPrompt}` : userPrompt;

    hideError();
    submitBtn.disabled = true;
    submitBtn.textContent = "Sending…";

    const outputPath = buildOutputPath(filenameEl.value);

    try {
      const resp = await fetch("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          layer_id: "gen_page",
          layer_type: "background",
          prompt,
          output_path: outputPath,
          lighting_variant: "ambient_soft",
        }),
      });

      if (!resp.ok) {
        const detail = (await resp.json()).detail ?? resp.statusText;
        throw new Error(detail);
      }

      const { job_id } = await resp.json();
      jobs.set(job_id, { prompt, status: "pending", asset_path: null, error: "" });
      filenameEl.value = "";
      renderJobs();
      schedulePoll();

      submitBtn.textContent = "Queued ✓";
      setTimeout(() => {
        submitBtn.textContent = "Generate";
        submitBtn.disabled = false;
      }, 1500);
    } catch (err) {
      showError(String(err));
      submitBtn.textContent = "Generate";
      submitBtn.disabled = false;
    }
  }

  // ── Polling ────────────────────────────────────────────────────────────────

  function hasActiveJobs() {
    for (const j of jobs.values()) {
      if (j.status === "pending" || j.status === "running") return true;
    }
    return false;
  }

  function schedulePoll() {
    if (pollTimer) return;
    pollTimer = setInterval(pollAllJobs, 2000);
  }

  function stopPollIfIdle() {
    if (!hasActiveJobs() && pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  async function pollAllJobs() {
    let anyNewDone = false;

    await Promise.all(
      Array.from(jobs.entries())
        .filter(([, j]) => j.status === "pending" || j.status === "running")
        .map(async ([job_id, job]) => {
          try {
            const resp = await fetch(`/api/generate/${job_id}`);
            if (!resp.ok) return;
            const data = await resp.json();
            const wasDone = job.status === "done";
            job.status = data.status;
            job.asset_path = data.asset_path ?? null;
            job.error = data.error ?? "";
            if (!wasDone && data.status === "done") anyNewDone = true;
          } catch {
            // Network hiccup — keep polling
          }
        })
    );

    renderJobs();
    stopPollIfIdle();
    if (anyNewDone) loadGallery();
  }

  // ── Error display ──────────────────────────────────────────────────────────

  function showError(msg) {
    errorEl.textContent = msg;
    errorEl.classList.remove("hidden");
  }

  function hideError() {
    errorEl.textContent = "";
    errorEl.classList.add("hidden");
  }

  // ── Safe DOM helpers ───────────────────────────────────────────────────────

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  // ── Render jobs ────────────────────────────────────────────────────────────

  function renderJobs() {
    const entries = Array.from(jobs.entries()).reverse();
    jobsListEl.textContent = "";

    if (!entries.length) {
      jobsListEl.appendChild(el("p", "gen-empty", "No jobs yet this session."));
      badgeEl.classList.add("hidden");
      return;
    }

    const active = entries.filter(([, j]) => j.status === "pending" || j.status === "running").length;
    if (active > 0) {
      badgeEl.textContent = `${active} running`;
      badgeEl.classList.remove("hidden");
    } else {
      badgeEl.classList.add("hidden");
    }

    const STATUS_CLASS = {
      pending: "gen-status--pending",
      running: "gen-status--running",
      done:    "gen-status--done",
      failed:  "gen-status--failed",
    };
    const STATUS_LABEL = {
      pending: "⏳ Queued",
      running: "⚡ Generating…",
      done:    "✓ Done",
      failed:  "✗ Failed",
    };

    for (const [job_id, job] of entries) {
      const promptSnip = job.prompt.length > 72
        ? job.prompt.slice(0, 72) + "…"
        : job.prompt;

      const card = el("div", `gen-job ${STATUS_CLASS[job.status] ?? ""}`);
      card.dataset.jobId = job_id;

      const info = el("div", "gen-job-info");
      info.appendChild(el("span", "gen-job-id",     job_id.slice(0, 8)));
      info.appendChild(el("span", "gen-job-status", STATUS_LABEL[job.status] ?? job.status));
      info.appendChild(el("p",    "gen-job-prompt", promptSnip));
      card.appendChild(info);

      if (job.error) {
        const errEl = el("p", "gen-job-error", job.error);
        card.appendChild(errEl);
      }

      if (job.asset_path) {
        const img = /** @type {HTMLImageElement} */ (el("img", "gen-job-thumb"));
        img.src = `/project-assets/${job.asset_path}`;
        img.alt = "";
        img.loading = "lazy";
        img.addEventListener("click", () => openLightbox(img.src, promptSnip));
        card.appendChild(img);
      }

      jobsListEl.appendChild(card);
    }
  }

  // ── Gallery ────────────────────────────────────────────────────────────────

  async function loadGallery() {
    try {
      const resp = await fetch("/api/assets");
      if (!resp.ok) throw new Error(resp.statusText);
      const data = await resp.json();
      const images = /** @type {string[]} */ (data.generated ?? []);
      const bookGroups = normalizeBookGroups(data);
      lastGallery = { paths: images, bookGroups };
      if (!selectedBookSlug) {
        selectedBookSlug = bookGroups.some((group) => group.slug === currentBookSlug)
          ? currentBookSlug
          : "all";
      }
      renderGallery(images, bookGroups);
    } catch (err) {
      galleryEl.textContent = "";
      if (filtersEl) filtersEl.textContent = "";
      if (gallerySummaryEl) gallerySummaryEl.textContent = "Could not load the image library.";
      const msg = el("p", "gen-empty gen-error");
      msg.textContent = `Could not load gallery: ${err}`;
      galleryEl.appendChild(msg);
    }
  }

  function normalizeBookGroups(data) {
    const library = Array.isArray(data.book_image_library) ? data.book_image_library : [];
    const legacy = Array.isArray(data.book_illustrations) ? data.book_illustrations : [];
    const groups = library.length
      ? library
      : legacy.map((group) => ({
        ...group,
        count: Array.isArray(group.images) ? group.images.length : 0,
        categories: [
          {
            id: "illustrations",
            title: "Page Illustrations",
            count: Array.isArray(group.images) ? group.images.length : 0,
            images: Array.isArray(group.images) ? group.images : [],
          },
        ],
      }));

    return [...groups]
      .filter((group) => Array.isArray(group.categories) && group.categories.some((category) => Array.isArray(category.images) && category.images.length))
      .sort((a, b) => {
        if (a.slug === currentBookSlug) return -1;
        if (b.slug === currentBookSlug) return 1;
        return String(a.title || a.slug).localeCompare(String(b.title || b.slug));
      });
  }

  function renderGallery(paths, bookGroups = []) {
    galleryEl.textContent = "";
    renderBookFilters(bookGroups);

    const hasBookImages = bookGroups.some((group) => Array.isArray(group.images) && group.images.length);
    if (!paths.length && !hasBookImages) {
      if (gallerySummaryEl) gallerySummaryEl.textContent = "No book images or scratch generations found yet.";
      galleryEl.appendChild(el("p", "gen-empty", "No generated images yet."));
      return;
    }

    const visibleGroups = selectedBookSlug === "all"
      ? bookGroups
      : bookGroups.filter((group) => group.slug === selectedBookSlug);
    const visibleImageCount = visibleGroups.reduce((sum, group) => sum + Number(group.count || 0), 0);

    updateGallerySummary(visibleGroups, visibleImageCount, paths.length, bookGroups.length);

    visibleGroups.forEach((group) => {
      const section = el("section", "gen-book-gallery");
      const heading = el("div", "gen-book-gallery-head");
      const titleWrap = el("div", "gen-book-title");
      titleWrap.appendChild(el("h3", "", group.title || group.slug || "Book"));
      titleWrap.appendChild(el("span", "gen-book-slug", group.slug || ""));
      const count = el("span", "gen-book-count", `${group.count || 0} image${group.count === 1 ? "" : "s"}`);
      heading.append(titleWrap, count);
      section.appendChild(heading);

      group.categories.forEach((category) => {
        if (!Array.isArray(category.images) || !category.images.length) return;
        const categorySection = el("section", "gen-book-category");
        const categoryHead = el("div", "gen-book-category-head");
        categoryHead.append(
          el("h4", "", category.title || "Images"),
          el("span", "gen-book-count", `${category.images.length} image${category.images.length === 1 ? "" : "s"}`)
        );
        categorySection.appendChild(categoryHead);

        const grid = el("div", "gen-gallery-grid");
        [...category.images].sort().forEach((path) => {
          grid.appendChild(renderGalleryThumb(path, {
            deletable: false,
            captionPrefix: `${group.title || group.slug || "Book"} / ${category.title || "Images"}`,
          }));
        });
        categorySection.appendChild(grid);
        section.appendChild(categorySection);
      });

      galleryEl.appendChild(section);
    });

    if (selectedBookSlug === "all" && paths.length) {
      const section = el("section", "gen-book-gallery");
      const heading = el("div", "gen-book-gallery-head");
      heading.append(el("h3", "", "Scratch Generations"), el("span", "gen-book-count", `${paths.length} image${paths.length === 1 ? "" : "s"}`));
      section.appendChild(heading);
      const grid = el("div", "gen-gallery-grid");
      [...paths].sort().reverse().forEach((path) => {
        grid.appendChild(renderGalleryThumb(path, { deletable: true }));
      });
      section.appendChild(grid);
      galleryEl.appendChild(section);
    }

    if (!galleryEl.children.length) {
      galleryEl.appendChild(el("p", "gen-empty", "No images found for this book yet."));
    }
  }

  function renderBookFilters(bookGroups) {
    if (!filtersEl) return;
    filtersEl.textContent = "";
    if (!bookGroups.length) return;

    const allCount = bookGroups.reduce((sum, group) => sum + Number(group.count || 0), 0);
    filtersEl.appendChild(renderBookFilterButton("all", `All Books (${allCount})`));
    bookGroups.forEach((group) => {
      const label = `${group.title || group.slug || "Book"} (${group.count || 0})`;
      filtersEl.appendChild(renderBookFilterButton(group.slug, label));
    });
  }

  function renderBookFilterButton(slug, label) {
    const button = /** @type {HTMLButtonElement} */ (el("button", "gen-book-filter", label));
    button.type = "button";
    button.dataset.bookSlug = slug;
    button.setAttribute("aria-pressed", String(selectedBookSlug === slug));
    button.addEventListener("click", () => {
      selectedBookSlug = slug;
      renderGallery(lastGallery.paths, lastGallery.bookGroups);
    });
    return button;
  }

  function updateGallerySummary(visibleGroups, imageCount, scratchCount, totalBooks) {
    if (!gallerySummaryEl) return;
    if (selectedBookSlug === "all") {
      gallerySummaryEl.textContent = `${imageCount} book images across ${totalBooks} book${totalBooks === 1 ? "" : "s"}${scratchCount ? `, plus ${scratchCount} scratch generation${scratchCount === 1 ? "" : "s"}` : ""}.`;
      return;
    }
    const title = visibleGroups[0]?.title || selectedBookSlug;
    gallerySummaryEl.textContent = `${imageCount} images for ${title}. Use All Books to compare other projects.`;
  }

  function renderGalleryThumb(p, options = {}) {
    const filename = p.split("/").pop() ?? p;
    const url = `/project-assets/${p}`;

    const wrap = el("div", "gen-thumb-wrap");

    const btn = /** @type {HTMLButtonElement} */ (el("button", "gen-thumb"));
    btn.type = "button";

    const img = /** @type {HTMLImageElement} */ (el("img"));
    img.src = url;
    img.alt = filename;
    img.loading = "lazy";

    btn.appendChild(img);
    btn.appendChild(el("span", "gen-thumb-label", filename));
    btn.addEventListener("click", () => openLightbox(url, options.captionPrefix ? `${options.captionPrefix} · ${filename}` : filename));

    wrap.appendChild(btn);

    if (options.deletable) {
      const delBtn = el("button", "gen-thumb-delete", "Delete");
      delBtn.type = "button";
      delBtn.title = "Delete image";
      delBtn.addEventListener("click", async (e) => {
        e.stopPropagation();
        if (!confirm(`Delete ${filename}?`)) return;
        try {
          const r = await fetch(`/api/generated/pages/${encodeURIComponent(filename)}`, { method: "DELETE" });
          if (!r.ok) throw new Error(await r.text());
          wrap.remove();
          if (!galleryEl.children.length) {
          galleryEl.appendChild(el("p", "gen-empty", "No generated images yet."));
        }
      } catch (err) {
          showError(`Delete failed: ${err}`);
        }
      });
      wrap.appendChild(delBtn);
    }

    return wrap;
  }

  // ── Lightbox ───────────────────────────────────────────────────────────────

  function openLightbox(src, caption) {
    lbImg.src = src;
    lbCaption.textContent = caption;
    lightbox.showModal();
  }

  lbClose.addEventListener("click", () => lightbox.close());
  lightbox.addEventListener("click", (e) => {
    if (e.target === lightbox) lightbox.close();
  });

  // ── Init ───────────────────────────────────────────────────────────────────

  submitBtn.addEventListener("click", submitGeneration);
  promptEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) submitGeneration();
  });
  refreshBtn.addEventListener("click", loadGallery);

  // Sync any jobs still in flight from the server (e.g. after a page reload)
  async function syncServerJobs() {
    try {
      const resp = await fetch("/api/generate/jobs");
      if (!resp.ok) return;
      const { jobs: serverJobs } = await resp.json();
      for (const j of serverJobs) {
        if (!jobs.has(j.job_id)) {
          jobs.set(j.job_id, {
            prompt: j.prompt || "(unknown)",
            status: j.status,
            asset_path: j.asset_path,
            error: j.error ?? "",
          });
        }
      }
      renderJobs();
      if (hasActiveJobs()) schedulePoll();
    } catch {
      // Server may not have the endpoint yet
    }
  }

  async function checkConnection() {
    if (!connStatusEl) return;
    try {
      const resp = await fetch("/api/generate/connection");
      if (!resp.ok) { connStatusEl.textContent = "⚠ Could not reach connection endpoint."; return; }
      const data = await resp.json();
      if (data.ok) {
        connStatusEl.textContent = `✓ Connected to ${data.url}`;
        connStatusEl.className = "gen-conn-ok";
      } else {
        connStatusEl.textContent = `✗ Cannot reach ${data.url} — ${data.error}`;
        connStatusEl.className = "gen-conn-fail";
      }
    } catch {
      connStatusEl.textContent = "⚠ Connection check failed.";
    }
  }

  loadGallery();
  syncServerJobs();
  checkConnection();
})();

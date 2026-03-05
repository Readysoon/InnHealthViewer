/* =========================================================
   InnHealth Video Previewer – app.js
   ========================================================= */

const PLACEHOLDER = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='90'%3E%3Crect width='160' height='90' fill='%23333'/%3E%3Ctext x='50%25' y='50%25' fill='%23888' font-size='11' dominant-baseline='middle' text-anchor='middle'%3ENo thumbnail%3C/text%3E%3C/svg%3E";

function fmtDuration(seconds) {
  const s = Math.round(seconds);
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return m > 0 ? `${m}m${rem.toString().padStart(2, "0")}s` : `${rem}s`;
}

// ── Thumbnail animation ─────────────────────────────────────────────────────

function makeThumbCard(video, draggable = false) {
  const card = document.createElement("div");
  card.className = "video-card";
  if (draggable) {
    card.draggable = true;
    card.dataset.srcPath = video.path;
    card.dataset.stem = video.stem;
    card.dataset.lr = video.lr || "?";
    card.addEventListener("dragstart", onDragStart);
  }

  // Double-click → open with system default player
  card.addEventListener("dblclick", () => {
    fetch("/api/open", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: video.path }),
    });
  });

  // Thumbnail image (animated on hover)
  const img = document.createElement("img");
  img.className = "thumb";
  const validThumbs = video.thumbs.filter(Boolean);
  img.src = validThumbs.length ? validThumbs[0] : PLACEHOLDER;
  img.alt = video.filename;

  // Animation state
  let frameIdx = 0;
  let timer = null;

  if (validThumbs.length > 1) {
    card.addEventListener("mouseenter", () => {
      timer = setInterval(() => {
        frameIdx = (frameIdx + 1) % validThumbs.length;
        img.src = validThumbs[frameIdx];
      }, 300);
    });
    card.addEventListener("mouseleave", () => {
      clearInterval(timer);
      frameIdx = 0;
      img.src = validThumbs[0];
    });
  }

  // Label
  const label = document.createElement("div");
  label.className = "thumb-label";
  const lrBadge = video.lr !== "?" ? `<span class="lr-badge lr-${video.lr}">${video.lr}</span>` : "";
  const timeStr = video.modification_date
    ? `<span class="vtime">${video.modification_date.slice(0, 10)}</span><span class="vtime">${video.modification_date.slice(11, 19)}</span>`
    : "";
  const resClass = video.resolution === "4K" ? "vres" : "vres vres-720";
  const resLabel = video.resolution && video.resolution !== "?" ? `<span class="${resClass}">${video.resolution}</span>` : "";
  const durLabel = video.duration > 0 ? `<span class="vdur">${fmtDuration(video.duration)}</span>` : "";
  // row 1: badges (LR, time, res, duration) — row 2: filename
  label.innerHTML =
    `<div class="label-badges">${lrBadge}${timeStr}${resLabel}${durLabel}</div>` +
    `<div class="fname">${video.filename}</div>`;

  card.appendChild(img);
  card.appendChild(label);

  // Delete button (only for sorted videos — caller sets it)
  if (!draggable) {
    const del = document.createElement("button");
    del.className = "btn-delete";
    del.title = "Delete this video";
    del.textContent = "✕";
    del.addEventListener("click", () => deleteVideo(video.path, card));
    card.appendChild(del);
  }

  return card;
}

// ── Patient data loading ────────────────────────────────────────────────────

async function loadPatient() {
  const res = await fetch(`/api/patient/${window.PATIENT_ID}`);
  const data = await res.json();

  for (const cat of window.CATEGORIES) {
    const strip = document.getElementById(`strip-${cat}`);
    const countEl = document.getElementById(`count-${cat}`);
    const videos = data.categories[cat] || [];

    strip.innerHTML = "";
    countEl.textContent = videos.length;

    if (videos.length === 0) {
      strip.innerHTML = `<span class="empty-strip">—</span>`;
    } else {
      for (const v of videos) {
        strip.appendChild(makeThumbCard(v, false));
      }
    }
  }

  // Auto-populate unsorted panel from date-matched videos
  const grid = document.getElementById("unsorted-grid");
  const header = document.getElementById("unsorted-header");
  if (data.unsorted_videos && data.unsorted_videos.length > 0) {
    const detectedDate = data.unsorted_videos[0].modification_date
      ? data.unsorted_videos[0].modification_date.slice(0, 10)
      : "";
    if (header && detectedDate) header.textContent = `Unsorted – ${detectedDate}`;
    grid.innerHTML = "";
    for (const v of data.unsorted_videos) {
      grid.appendChild(makeThumbCard(v, true));
    }
    applyLrFilter();
  } else if (data.unsorted_videos) {
    if (header) header.textContent = "Unsorted Videos";
    grid.innerHTML = `<p class="empty-hint">No unsorted videos found for this date</p>`;
  }
}

// ── Unsorted panel ──────────────────────────────────────────────────────────

async function loadDates() {
  const sel = document.getElementById("date-select");
  const res = await fetch("/api/dates");
  const dates = await res.json();
  for (const d of dates) {
    const opt = document.createElement("option");
    opt.value = d;
    opt.textContent = d;
    sel.appendChild(opt);
  }
  // Sync dropdown to auto-detected folder if already set
  if (sel.dataset.autoselect) {
    sel.value = sel.dataset.autoselect;
  }
}

async function loadUnsorted(dateFolder) {
  const grid = document.getElementById("unsorted-grid");
  const header = document.getElementById("unsorted-header");
  grid.innerHTML = `<p class="loading-indicator">Loading…</p>`;
  const res = await fetch(`/api/unsorted/${encodeURIComponent(dateFolder)}`);
  const videos = await res.json();
  grid.innerHTML = "";
  // Show the date folder name in the panel header
  if (header) header.textContent = `Unsorted – ${dateFolder}`;
  if (!videos.length) {
    grid.innerHTML = `<p class="empty-hint">No videos in this folder</p>`;
    return;
  }
  for (const v of videos) {
    grid.appendChild(makeThumbCard(v, true));
  }
  applyLrFilter();
}

document.getElementById("date-select").addEventListener("change", e => {
  if (e.target.value) loadUnsorted(e.target.value);
});

// ── L/R filter ──────────────────────────────────────────────────────────────

let activeLrFilter = "all";

document.querySelectorAll(".btn-lr").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".btn-lr").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    activeLrFilter = btn.dataset.lr;
    applyLrFilter();
  });
});

function applyLrFilter() {
  const grid = document.getElementById("unsorted-grid");
  grid.querySelectorAll(".video-card").forEach(card => {
    const lr = card.dataset.lr || "?";
    if (activeLrFilter === "all" || lr === activeLrFilter) {
      card.style.display = "";
    } else {
      card.style.display = "none";
    }
  });
}

// ── Drag & drop ─────────────────────────────────────────────────────────────

let draggedCard = null;
let draggedSrcPath = null;

function onDragStart(e) {
  draggedCard = e.currentTarget;
  draggedSrcPath = draggedCard.dataset.srcPath;
  e.dataTransfer.effectAllowed = "move";
  e.dataTransfer.setData("text/plain", draggedSrcPath);
  draggedCard.classList.add("dragging");
}

document.addEventListener("dragend", () => {
  if (draggedCard) draggedCard.classList.remove("dragging");
  document.querySelectorAll(".drop-zone").forEach(z => z.classList.remove("drag-over"));
});

document.querySelectorAll(".drop-zone").forEach(zone => {
  zone.addEventListener("dragover", e => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    zone.classList.add("drag-over");
  });
  zone.addEventListener("dragleave", e => {
    if (!zone.contains(e.relatedTarget)) zone.classList.remove("drag-over");
  });
  zone.addEventListener("drop", async e => {
    e.preventDefault();
    zone.classList.remove("drag-over");
    const srcPath = e.dataTransfer.getData("text/plain");
    const targetCat = zone.dataset.category;
    const targetPatient = zone.dataset.patient;
    if (!srcPath || !targetCat) return;

    const lr = draggedCard?.dataset.lr || "?";
    const res = await fetch("/api/move", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ src_path: srcPath, target_patient: targetPatient, target_category: targetCat, lr }),
    });
    const result = await res.json();
    if (result.ok) {
      // Add card to the drop zone strip
      const strip = document.getElementById(`strip-${targetCat}`);
      const emptyEl = strip.querySelector(".empty-strip");
      if (emptyEl) emptyEl.remove();
      strip.appendChild(makeThumbCard(result.video, false));

      // Update count (source card stays — copy, not move)
      const countEl = document.getElementById(`count-${targetCat}`);
      countEl.textContent = parseInt(countEl.textContent || "0") + 1;

      // Do NOT remove source card — this is a copy, not a move
    } else {
      alert("Move failed: " + (result.error || "unknown error"));
    }
    draggedCard = null;
    draggedSrcPath = null;
  });
});

// ── Delete ──────────────────────────────────────────────────────────────────

async function deleteVideo(path, card) {
  const res = await fetch("/api/delete", {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  const result = await res.json();
  if (result.ok) {
    const strip = card.closest(".video-strip");
    const cat = strip?.id?.replace("strip-", "");
    card.remove();
    if (strip && !strip.querySelector(".video-card")) {
      strip.innerHTML = `<span class="empty-strip">—</span>`;
    }
    if (cat) {
      const countEl = document.getElementById(`count-${cat}`);
      if (countEl) countEl.textContent = Math.max(0, parseInt(countEl.textContent || "1") - 1);
    }
  } else {
    alert("Delete failed: " + (result.error || "unknown error"));
  }
}

// ── Prefetch neighbours ──────────────────────────────────────────────────────

const PREFETCH_RADIUS = 10; // 10 Patienten davor, 10 danach

async function prefetchOnePatient(pid) {
  let data;
  try {
    const res = await fetch(`/api/patient/${pid}`);
    data = await res.json();
  } catch (_) { return; }

  // Collect all thumbnail URLs from sorted categories + unsorted panel
  const urls = [];
  for (const cat of window.CATEGORIES) {
    for (const v of (data.categories[cat] || [])) {
      urls.push(...(v.thumbs || []).filter(Boolean));
    }
  }
  for (const v of (data.unsorted_videos || [])) {
    urls.push(...(v.thumbs || []).filter(Boolean));
  }

  // Preload each URL — browser caches the JPEG response
  for (const url of urls) {
    const img = new Image();
    img.src = url;
  }
  console.log(`[prefetch] ${pid}: ${urls.length} thumbnails`);
}

function prefetchNeighbours() {
  if (!window.ALL_PATIENTS) return;
  const idx = window.ALL_PATIENTS.indexOf(window.PATIENT_ID);
  if (idx === -1) return;

  // Immer 10 davor und 10 danach vorladen (aktueller Patient wird eh geladen)
  const start = Math.max(0, idx - PREFETCH_RADIUS);
  const end = Math.min(window.ALL_PATIENTS.length - 1, idx + PREFETCH_RADIUS);
  for (let i = start; i <= end; i++) {
    if (i === idx) continue; // aktuelle Seite lädt selbst
    prefetchOnePatient(window.ALL_PATIENTS[i]);
  }
  console.log(`[prefetch] Fenster ${start}–${end} (${end - start + 1} Patienten)`);
}

// ── Init ─────────────────────────────────────────────────────────────────────

// Pfeiltasten: Vor/Zurück zwischen Patienten (nur wenn nicht in Input/Select)
document.addEventListener("keydown", (e) => {
  if (!window.ALL_PATIENTS || !window.PATIENT_ID) return;
  const tag = (e.target && e.target.tagName) ? e.target.tagName.toUpperCase() : "";
  if (["INPUT", "TEXTAREA", "SELECT"].includes(tag)) return;

  const idx = window.ALL_PATIENTS.indexOf(window.PATIENT_ID);
  if (idx === -1) return;

  if (e.key === "ArrowLeft" && idx > 0) {
    e.preventDefault();
    window.location.href = "/patient/" + window.ALL_PATIENTS[idx - 1];
  } else if (e.key === "ArrowRight" && idx < window.ALL_PATIENTS.length - 1) {
    e.preventDefault();
    window.location.href = "/patient/" + window.ALL_PATIENTS[idx + 1];
  }
});

// Start prefetching neighbours immediately in parallel with current patient load
loadPatient();
prefetchNeighbours();
loadDates();

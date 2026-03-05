"""
Flask backend for the InnHealth Video Previewer (standalone).

Run from this directory:
  pip install -r requirements.txt
  python app.py
  python app.py -d Z
  python app.py -d X
  python app.py --gait-dir Y --port 5001
Then open http://localhost:5000 (or the port you set).
"""

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_file

import config

app = Flask(__name__)

PATIENT_RE    = re.compile(r"^IH-\d{4}-B$")
VIDEO_EXT     = {".mov", ".mp4", ".avi", ".mkv", ".mts", ".m4v"}

CATEGORIES = [
    "Calibration-Posture",
    "Gait-4K",
    "Gait-720p",
    "Sitting",
    "Timedupandgo3m",
]

# ---------------------------------------------------------------------------
# lazy caches — populated on first request, not at startup
# ---------------------------------------------------------------------------

_PATIENTS: list[str] = []
_PATIENTS_LOADED = False

_THUMB_CACHE: set[str] = set()
_THUMB_CACHE_LOADED = False

# L/R classification cache: stem -> "L" | "R" | "?"  (in-memory, not persisted)
_LR_CACHE: dict[str, str] = {}
_LR_CACHE_LOCK = __import__("threading").Lock()

# Video index: loaded once from video_index.json
# _INDEX_BY_STEM: stem -> {"path", "filename", "modification_date"}
# _INDEX_BY_DATE: date_str (YYYY-MM-DD) -> [{"path", "filename", "stem", ...}]
_INDEX_BY_STEM: dict[str, dict] = {}
_INDEX_BY_DATE: dict[str, list[dict]] = {}
_INDEX_LOADED = False

# stem -> {"resolution": "4K"|"720p", "duration": float seconds}
_RES_CACHE: dict[str, dict] = {}
_RES_CACHE_DIRTY = False


def _ffprobe_meta(video_path: str) -> dict:
    """Fallback when VideoClassifier is not available: use ffprobe for resolution and duration."""
    res = "720p"
    duration = 0.0
    try:
        r = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=p=0",
                video_path,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode == 0 and r.stdout.strip():
            parts = r.stdout.strip().split("\n")[0].split(",")
            if len(parts) >= 2:
                w, h = int(parts[0].strip()), int(parts[1].strip())
                if w >= 1920 or h >= 1080:
                    res = "4K"
    except Exception:
        pass
    try:
        r = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=nk=1:nw=1",
                video_path,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode == 0 and r.stdout.strip():
            duration = float(r.stdout.strip())
    except Exception:
        pass
    return {"resolution": res, "duration": duration}


def _load_res_cache():
    global _RES_CACHE
    try:
        if config.RES_CACHE_PATH.exists():
            with open(config.RES_CACHE_PATH, encoding="utf-8") as f:
                _RES_CACHE = json.load(f)
            print(f"  Metadata cache: {len(_RES_CACHE)} entries", flush=True)
    except Exception:
        _RES_CACHE = {}


def _save_res_cache():
    try:
        config.RES_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(config.RES_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(_RES_CACHE, f)
    except Exception as ex:
        print(f"  [meta-cache] save error: {ex}", flush=True)


def get_video_meta(stem: str, video_path: str) -> dict:
    """Returns {"resolution": "4K"|"720p", "duration": float}.
    Checks cache first; then VideoClassifier if available, else ffprobe."""
    global _RES_CACHE_DIRTY
    entry = _RES_CACHE.get(stem)
    if isinstance(entry, dict) and "duration" in entry:
        return entry
    try:
        from VideoClassifier import get_video_metadata as _gvm
        meta = _gvm(video_path)
    except Exception:
        meta = _ffprobe_meta(video_path)
    _RES_CACHE[stem] = meta
    _RES_CACHE_DIRTY = True
    if len(_RES_CACHE) % 10 == 0:
        _save_res_cache()
    return meta


_load_res_cache()


def _ensure_index():
    global _INDEX_BY_STEM, _INDEX_BY_DATE, _INDEX_LOADED
    if _INDEX_LOADED:
        return
    t0 = time.time()
    print("Loading video_index.json ...", flush=True)
    try:
        if not config.INDEX_PATH.exists():
            print(f"  No index at {config.INDEX_PATH} — unsorted date matching disabled.", flush=True)
            _INDEX_LOADED = True
            return
        with open(config.INDEX_PATH, encoding="utf-8") as f:
            data = json.load(f)
        for entry in data.get("videos", []):
            stem = Path(entry["filename"]).stem
            date = entry["modification_date"][:10]  # "YYYY-MM-DD"
            enriched = {**entry, "stem": stem, "date": date}
            _INDEX_BY_STEM[stem] = enriched
            _INDEX_BY_DATE.setdefault(date, []).append(enriched)
        print(f"  -> {len(_INDEX_BY_STEM)} videos, {len(_INDEX_BY_DATE)} dates in {(time.time()-t0)*1000:.0f}ms", flush=True)
    except Exception as ex:
        print(f"  ERROR loading index: {ex}", flush=True)
    _INDEX_LOADED = True


def _ensure_patients():
    global _PATIENTS, _PATIENTS_LOADED
    if _PATIENTS_LOADED:
        return
    t0 = time.time()
    print("Scanning patient folders (lazy) ...", flush=True)
    try:
        # Skip isdir() check — regex match is enough, avoids 628 extra network calls
        _PATIENTS = sorted(e for e in os.listdir(config.GAIT_DIR) if PATIENT_RE.match(e))
    except Exception as ex:
        print(f"  ERROR: {ex}", flush=True)
        _PATIENTS = []
    _PATIENTS_LOADED = True
    print(f"  -> {len(_PATIENTS)} patients in {(time.time()-t0)*1000:.0f}ms", flush=True)


def _ensure_thumbs():
    """Build thumbnail cache from the video index if loaded; else from disk scan of THUMB_DIR."""
    global _THUMB_CACHE, _THUMB_CACHE_LOADED
    if _THUMB_CACHE_LOADED:
        return
    _ensure_index()
    t0 = time.time()
    if _INDEX_BY_STEM:
        for stem in _INDEX_BY_STEM:
            for i in range(1, 6):
                _THUMB_CACHE.add(f"{stem}-{i}.jpg")
    else:
        try:
            for f in os.listdir(config.THUMB_DIR):
                if f.endswith(".jpg") and f.count("-") >= 1:
                    _THUMB_CACHE.add(f)
        except Exception:
            pass
    _THUMB_CACHE_LOADED = True
    print(f"  -> {len(_THUMB_CACHE)} thumbnail entries in {(time.time()-t0)*1000:.0f}ms", flush=True)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def all_patients() -> list[str]:
    _ensure_patients()
    return _PATIENTS


def invalidate_patient_cache():
    """Clears the patient cache so it reloads on next request."""
    global _PATIENTS_LOADED
    _PATIENTS_LOADED = False


def find_unsorted_videos_for_patient(patient_id: str) -> list[dict]:
    """Returns all videos from Downloads_Unsortiert recorded on the same date
    as the patient's already-sorted videos. Uses video_index.json — no network walk."""
    _ensure_index()
    t0 = time.time()

    # Collect stems of all sorted videos for this patient
    patient_dir = os.path.join(config.GAIT_DIR, patient_id)
    patient_stems: set[str] = set()
    for cat in CATEGORIES:
        sub = os.path.join(patient_dir, f"{patient_id}-{cat}")
        if os.path.isdir(sub):
            for f in os.listdir(sub):
                if Path(f).suffix.lower() in VIDEO_EXT:
                    patient_stems.add(video_stem(f))

    if not patient_stems:
        return []

    # Find recording date by looking up patient stems in the index
    recording_date = None
    for stem in patient_stems:
        if stem in _INDEX_BY_STEM:
            recording_date = _INDEX_BY_STEM[stem]["date"]
            break

    if not recording_date:
        print(f"  [date-detect] {patient_id}: no stems found in index", flush=True)
        return []

    print(f"  [date-detect] {patient_id}: recording_date={recording_date} in {(time.time()-t0)*1000:.0f}ms", flush=True)

    # Deduplicate by stem, keep sort order
    seen: set[str] = set()
    unique_entries = []
    for entry in sorted(_INDEX_BY_DATE.get(recording_date, []), key=lambda e: e["modification_date"]):
        if entry["stem"] not in seen:
            seen.add(entry["stem"])
            unique_entries.append(entry)

    print(f"  [date-detect] {len(unique_entries)} unique videos on {recording_date}, processing in parallel...", flush=True)

    # Process video_info() in parallel — each call does L/R inference + ffprobe (slow if uncached)
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _build_info(entry):
        info = video_info(entry["path"])
        info["modification_date"] = entry["modification_date"]
        return (entry["modification_date"], info)

    results_map: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_build_info, e): e for e in unique_entries}
        for fut in as_completed(futures):
            try:
                mod_date, info = fut.result()
                results_map[info["stem"]] = (mod_date, info)
            except Exception as ex:
                print(f"    [date-detect] error: {ex}", flush=True)

    # Restore original sort order
    result = [results_map[e["stem"]][1] for e in unique_entries if e["stem"] in results_map]

    print(f"  [date-detect] {len(result)} unique videos on {recording_date} in {(time.time()-t0)*1000:.0f}ms total", flush=True)
    return result


def video_stem(filename: str) -> str:
    """Extract the original recording code from any video filename.
    'L-IH-0434-B-Calibration-Posture-PCPN7404.MOV' -> 'PCPN7404'
    'BGNR1342.MOV'                                  -> 'BGNR1342'
    """
    name = Path(filename).stem
    parts = name.split("-")
    # If the name contains IH patient pattern, the original code is the last segment
    if len(parts) > 1:
        return parts[-1]
    return name


def thumb_urls(stem: str) -> list[str | None]:
    """Return list of 5 thumbnail URL strings (or None if file missing).
    Uses in-memory cache to avoid network isfile() calls."""
    _ensure_thumbs()
    urls = []
    for i in range(1, 6):
        fname = f"{stem}-{i}.jpg"
        if fname in _THUMB_CACHE:
            urls.append(f"/thumbnails/{stem}/{i}")
        else:
            # Stem not in index — do a one-time real check and cache the result
            real_path = os.path.join(config.THUMB_DIR, fname)
            if os.path.isfile(real_path):
                _THUMB_CACHE.add(fname)
                urls.append(f"/thumbnails/{stem}/{i}")
            else:
                urls.append(None)
    return urls


def classify_lr_from_thumbnails(stem: str) -> str:
    """L/R from filename or optional VideoClassifier. Without VideoClassifier/cv2 returns '?'."""
    with _LR_CACHE_LOCK:
        if stem in _LR_CACHE:
            return _LR_CACHE[stem]
        _LR_CACHE[stem] = "?"

    try:
        import cv2
        from VideoClassifier import classify_left_right
    except Exception as ex:
        return "?"

    frames = []
    for i, pct in enumerate([20, 40, 60, 80, 95], 1):
        thumb_path = os.path.join(config.THUMB_DIR, f"{stem}-{i}.jpg")
        if not os.path.isfile(thumb_path):
            continue
        img = cv2.imread(thumb_path)
        if img is not None:
            frames.append((pct, img))
    if not frames:
        with _LR_CACHE_LOCK:
            _LR_CACHE[stem] = "?"
        return "?"
    try:
        result = classify_left_right(frames)
        with _LR_CACHE_LOCK:
            _LR_CACHE[stem] = result
        return result
    except Exception:
        return "?"


def video_info(filepath: str) -> dict:
    t0 = time.time()
    filename = os.path.basename(filepath)
    stem = video_stem(filename)
    name = Path(filename).stem

    # For already-sorted videos the L/R prefix is in the filename — trust that.
    # For unsorted videos (no IH pattern), use the ML model on thumbnails.
    if name.startswith("L-"):
        lr = "L"
    elif name.startswith("R-"):
        lr = "R"
    else:
        lr = classify_lr_from_thumbnails(stem)

    t_idx = time.time()
    _ensure_index()
    mod_date = _INDEX_BY_STEM.get(stem, {}).get("modification_date", "")
    dt_idx = int((time.time() - t_idx) * 1000)

    t_meta = time.time()
    meta = get_video_meta(stem, filepath)
    dt_meta = int((time.time() - t_meta) * 1000)

    t_thumb = time.time()
    thumbs = thumb_urls(stem)
    dt_thumb = int((time.time() - t_thumb) * 1000)

    dt_total = int((time.time() - t0) * 1000)
    cached_meta = isinstance(_RES_CACHE.get(stem), dict) and "duration" in _RES_CACHE.get(stem, {})
    if dt_total > 50:  # only print if surprisingly slow
        print(f"    [video_info] {filename}: lr={lr} meta={'cached' if cached_meta else 'ffprobe'}({dt_meta}ms) idx={dt_idx}ms thumbs={dt_thumb}ms  total={dt_total}ms", flush=True)

    return {
        "filename": filename,
        "path": filepath,
        "stem": stem,
        "lr": lr,
        "thumbs": thumbs,
        "modification_date": mod_date,
        "resolution": meta["resolution"],
        "duration": meta["duration"],
    }


# ---------------------------------------------------------------------------
# thumbnail serving
# ---------------------------------------------------------------------------

@app.route("/thumbnails/<stem>/<int:n>")
def serve_thumbnail(stem: str, n: int):
    path = os.path.join(config.THUMB_DIR, f"{stem}-{n}.jpg")
    if not os.path.isfile(path):
        abort(404)
    resp = send_file(path, mimetype="image/jpeg")
    # Thumbnails sind unveraenderlich (gleicher Pfad = gleiches Bild) → lange cachen
    resp.headers["Cache-Control"] = "public, max-age=604800"  # 7 Tage
    return resp


# ---------------------------------------------------------------------------
# pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    patients = all_patients()
    return render_template("index.html", patients=patients)


@app.route("/patient/<patient_id>")
def patient_page(patient_id: str):
    patients = all_patients()
    if patient_id not in patients:
        abort(404)
    idx = patients.index(patient_id)
    prev_id = patients[idx - 1] if idx > 0 else None
    next_id = patients[idx + 1] if idx < len(patients) - 1 else None
    return render_template(
        "patient.html",
        patient_id=patient_id,
        prev_id=prev_id,
        next_id=next_id,
        all_patients=patients,
        categories=CATEGORIES,
    )


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.route("/api/patient/<patient_id>")
def api_patient(patient_id: str):
    t0 = time.time()
    print(f"[api/patient] {patient_id} ...", flush=True)

    patients = all_patients()
    if patient_id not in patients:
        abort(404)

    patient_dir = os.path.join(config.GAIT_DIR, patient_id)
    result = {}
    for cat in CATEGORIES:
        sub_path = os.path.join(patient_dir, f"{patient_id}-{cat}")
        videos = []
        t_cat = time.time()
        if os.path.isdir(sub_path):
            fnames = sorted(f for f in os.listdir(sub_path) if Path(f).suffix.lower() in VIDEO_EXT)
            if fnames:
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=len(fnames)) as pool:
                    futs = [pool.submit(video_info, os.path.join(sub_path, f)) for f in fnames]
                    videos = [fut.result() for fut in futs]
        print(f"  {cat}: {len(videos)} videos in {(time.time()-t_cat)*1000:.0f}ms", flush=True)
        result[cat] = videos

    # Auto-detect all unsorted videos from the same recording date
    t_unsorted = time.time()
    unsorted_videos = find_unsorted_videos_for_patient(patient_id)
    print(f"  [unsorted] {len(unsorted_videos)} videos in {(time.time()-t_unsorted)*1000:.0f}ms", flush=True)
    matched_folder = None  # no longer used for display, kept for API compat

    idx = patients.index(patient_id)
    print(f"[api/patient] done in {(time.time()-t0)*1000:.0f}ms total", flush=True)
    return jsonify({
        "patient_id": patient_id,
        "prev_id": patients[idx - 1] if idx > 0 else None,
        "next_id": patients[idx + 1] if idx < len(patients) - 1 else None,
        "categories": result,
        "matched_date_folder": matched_folder,
        "unsorted_videos": unsorted_videos,
    })


@app.route("/api/dates")
def api_dates():
    t0 = time.time()
    try:
        folders = sorted(
            e for e in os.listdir(config.UNSORTED_DIR)
            if os.path.isdir(os.path.join(config.UNSORTED_DIR, e))
        )
    except Exception:
        folders = []
    print(f"[api/dates] {len(folders)} folders in {(time.time()-t0)*1000:.0f}ms", flush=True)
    return jsonify(folders)


@app.route("/api/unsorted/<path:date_folder>")
def api_unsorted(date_folder: str):
    t0 = time.time()
    print(f"[api/unsorted] {date_folder} ...", flush=True)
    folder_path = os.path.join(config.UNSORTED_DIR, date_folder)
    if not os.path.isdir(folder_path):
        abort(404)
    videos = []
    seen_stems: set[str] = set()
    for root, _, files in os.walk(folder_path):
        for f in sorted(files):
            if Path(f).suffix.lower() in VIDEO_EXT:
                stem = Path(f).stem
                if stem not in seen_stems:
                    seen_stems.add(stem)
                    videos.append(video_info(os.path.join(root, f)))
    print(f"[api/unsorted] {len(videos)} videos in {(time.time()-t0)*1000:.0f}ms", flush=True)
    return jsonify(videos)


@app.route("/api/move", methods=["POST"])
def api_move():
    data = request.get_json()
    src_path      = data.get("src_path", "")
    target_patient = data.get("target_patient", "")
    target_cat    = data.get("target_category", "")

    if not src_path or not target_patient or not target_cat:
        return jsonify({"error": "missing fields"}), 400
    if not os.path.isfile(src_path):
        return jsonify({"error": "source not found"}), 404
    if target_cat not in CATEGORIES:
        return jsonify({"error": "invalid category"}), 400

    filename = os.path.basename(src_path)
    orig_stem = Path(filename).stem   # e.g. BGNR1342
    ext = Path(filename).suffix       # e.g. .MOV

    # Determine L/R: prefer value sent from frontend, fallback to filename prefix
    lr = data.get("lr", "").upper()
    if lr not in ("L", "R"):
        lr = "L" if filename.upper().startswith("L-") else ("R" if filename.upper().startswith("R-") else "L")

    # Build canonical filename: L-IH-XXXX-B-{Category}-{ORIGINALCODE}.MOV
    new_filename = f"{lr}-{target_patient}-{target_cat}-{orig_stem}{ext}"
    dest_dir = os.path.join(config.GAIT_DIR, target_patient, f"{target_patient}-{target_cat}")
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, new_filename)

    print(f"[move] {filename} -> {new_filename}", flush=True)

    try:
        shutil.copy2(src_path, dest_path)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"ok": True, "dest": dest_path, "video": video_info(dest_path)})


@app.route("/api/open", methods=["POST"])
def api_open():
    """Open a video file with the system default player."""
    data = request.get_json()
    path = data.get("path", "")
    if not path or not os.path.isfile(path):
        return jsonify({"error": "not found"}), 404
    try:
        if os.name == "nt":
            os.startfile(path)
        else:
            subprocess.run(["xdg-open", path], check=False, capture_output=True)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


@app.route("/api/delete", methods=["DELETE"])
def api_delete():
    data = request.get_json()
    path = data.get("path", "")
    # Safety: only allow deleting files inside GAIT_DIR
    try:
        rel = os.path.relpath(path, config.GAIT_DIR)
    except ValueError:
        return jsonify({"error": "invalid path"}), 400

    if rel.startswith(".."):
        return jsonify({"error": "forbidden path"}), 403
    if not os.path.isfile(path):
        return jsonify({"error": "not found"}), 404

    try:
        os.remove(path)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"ok": True})


if __name__ == "__main__":
    import argparse
    import atexit
    parser = argparse.ArgumentParser(description="InnHealth Video Viewer")
    parser.add_argument(
        "-d", "--gait-dir",
        type=str,
        default=None,
        help="Gait data root. Can be full path or just drive letter (e.g. Z or X) for that drive's \\INNHEALTH\\Gait.",
    )
    parser.add_argument("--port", type=int, default=5000, help="Port (default: 5000)")
    parser.add_argument("--debug", action="store_true", default=True, help="Run in debug mode (default: True)")
    args = parser.parse_args()
    if args.gait_dir:
        path = config.expand_gait_dir_arg(args.gait_dir)
        config.set_gait_dir(path)
        print(f"Using GAIT_DIR: {config.GAIT_DIR}", flush=True)
    atexit.register(_save_res_cache)
    app.run(debug=args.debug, port=args.port, threaded=True)

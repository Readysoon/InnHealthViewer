"""
Configuration for the standalone InnHealth Video Viewer.
Paths are read from environment variables so the app can run without the parent project.
"""
import os
from pathlib import Path

# Load .env from viewer root if present (no dependency on parent project)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:
    pass

# Viewer root (this repo)
VIEWER_ROOT = Path(__file__).resolve().parent

# Base directory for Gait data: patient folders (IH-XXXX-B), thumbnails, Downloads_Unsortiert
# Set GAIT_DIR to your actual path, e.g. Z:\INNHEALTH\Gait or /mnt/gait
GAIT_DIR = os.environ.get("GAIT_DIR", str(VIEWER_ROOT / "data" / "gait"))
UNSORTED_DIR = os.path.join(GAIT_DIR, "Downloads_Unsortiert")
THUMB_DIR = os.path.join(GAIT_DIR, "thumbnails")

# Optional: paths for video index and resolution cache (default: inside viewer/data)
INDEX_PATH = Path(os.environ.get("VIEWER_INDEX_PATH", str(VIEWER_ROOT / "data" / "video_index.json")))
RES_CACHE_PATH = Path(os.environ.get("VIEWER_RES_CACHE_PATH", str(VIEWER_ROOT / "data" / "resolution_cache.json")))


def expand_gait_dir_arg(arg: str) -> str:
    """If arg is a single drive letter (e.g. Z or X), expand to \\INNHEALTH\\Gait on that drive."""
    s = (arg or "").strip().rstrip(":\\")
    if len(s) == 1 and s.isalpha():
        return f"{s.upper()}:\\INNHEALTH\\Gait"
    return arg.rstrip("/\\")


def set_gait_dir(path: str) -> None:
    """Override GAIT_DIR (e.g. from command-line). Updates GAIT_DIR, UNSORTED_DIR, THUMB_DIR."""
    global GAIT_DIR, UNSORTED_DIR, THUMB_DIR
    path = path.rstrip("/\\")
    GAIT_DIR = path
    UNSORTED_DIR = os.path.join(GAIT_DIR, "Downloads_Unsortiert")
    THUMB_DIR = os.path.join(GAIT_DIR, "thumbnails")

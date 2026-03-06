# InnHealth Video Viewer

Standalone web app to browse Gait video folders: patient list, category rows with thumbnails, unsorted panel. Drag videos into categories; L/R and resolution from thumbnails/ffprobe.

**Requirements:** Python 3.10+, `pip install -r requirements.txt`. FFmpeg in PATH (optional).

## Quick start

```bash
cd InnHealthViewer
python -m venv .venv
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Linux / macOS:
# source .venv/bin/activate

pip install -r requirements.txt
python app.py -d Z
```

Open http://localhost:5000. Use **`-d Z`** (or `X`, `Y`) to point at `Z:\INNHEALTH\Gait`; or set `GAIT_DIR` in env or `.env`.

## Optional: L/R model

Copy `left_right_mobilenetv3.pth` from the main project’s `ML_Left_Right/` into `viewer/models/`. Without it, unsorted videos show "?" for L/R.

## Run

- `python app.py` — use `GAIT_DIR` from env
- `python app.py -d Z` — drive Z → `Z:\INNHEALTH\Gait`
- `python app.py -d X --port 5001`

Your Gait root must contain patient folders (`IH-XXXX-B`), `thumbnails/`, and `Downloads_Unsortiert/`. Optional: put `video_index.json` in `data/` for date-matched unsorted videos.

# InnHealth Video Viewer

Standalone Flask app to browse and manage Gait video folders: view patient categories, thumbnails, drag unsorted videos into categories, open/delete clips.

## Requirements

- Python 3.10+
- [Flask](https://pypi.org/project/Flask/) (see `requirements.txt`)
- **FFmpeg** (optional, for resolution/duration when no VideoClassifier)
- **VideoClassifier** (optional; if present in parent or on `PYTHONPATH`, enables L/R classification and metadata)

## Setup

1. Clone or copy this repo.
2. Create a virtualenv and install dependencies:

   ```bash
   cd viewer
   python -m venv .venv
   .venv\Scripts\activate   # Windows
   # source .venv/bin/activate   # Linux/Mac
   pip install -r requirements.txt
   ```

3. Set the path to your Gait data (patient folders, thumbnails, Downloads_Unsortiert):

   **Windows (cmd):**
   ```cmd
   set GAIT_DIR=Z:\INNHEALTH\Gait
   ```

   **Windows (PowerShell):**
   ```powershell
   $env:GAIT_DIR = "Z:\INNHEALTH\Gait"
   ```

   **Linux/Mac:**
   ```bash
   export GAIT_DIR=/path/to/gait
   ```

   Or copy `.env.example` to `.env` and set `GAIT_DIR` (you need to load it in the app or use a tool like `python-dotenv` if you add it to requirements).

   **Command-line overrides env:** You can also pass the path when starting the app (see Run below), so you don't have to change the drive letter in env each time.

4. Optional: put `video_index.json` in `data/` so the viewer can match unsorted videos by date. Otherwise leave `data/` empty; patient list comes from scanning `GAIT_DIR` for `IH-XXXX-B` folders.

## Run

From the `viewer` directory:

```bash
python app.py
```

Or pass the drive letter or full path (drive letter expands to that drive’s `\INNHEALTH\Gait`):

```bash
python app.py -d Z
python app.py -d X
python app.py --gait-dir Y:\INNHEALTH\Gait
python app.py -d Z --port 5001
```

Then open **http://localhost:5000** (or the port you set).

## Directory layout

Your `GAIT_DIR` should look like:

- `GAIT_DIR/`  
  - `IH-0001-B/`, `IH-0002-B/`, … (patient folders)  
  - `thumbnails/` — JPEGs named `{stem}-1.jpg` … `{stem}-5.jpg`  
  - `Downloads_Unsortiert/` — date-named subfolders with unsorted videos  

This repo:

- `app.py` — Flask app  
- `config.py` — paths from env  
- `templates/`, `static/` — frontend  
- `data/` — optional `video_index.json`, `resolution_cache.json`  

## Git

Initialize and push as its own repo:

```bash
cd viewer
git init
git add .
git commit -m "Initial standalone viewer"
git remote add origin <your-repo-url>
git push -u origin main
```

Ignore `data/video_index.json` and `data/resolution_cache.json` in `.gitignore` if they are machine-specific; keep `data/.gitkeep` so the folder exists after clone.

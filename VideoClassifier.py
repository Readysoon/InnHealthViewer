"""
Standalone VideoClassifier for the viewer: L/R from thumbnails + metadata via ffprobe.
No dependency on the main project. Model: viewer/models/left_right_mobilenetv3.pth
"""
import subprocess
from pathlib import Path

VIEWER_ROOT = Path(__file__).resolve().parent
MODEL_PATH = VIEWER_ROOT / "models" / "left_right_mobilenetv3.pth"

# Lazy-loaded model
_lr_model = None
_lr_device = None

# Transforms (same as training)
_transform = None


def _get_transform():
    global _transform
    if _transform is None:
        from torchvision import transforms
        _transform = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])
    return _transform


def _frames_to_tensor(frames):
    """frames: list of (pct, img) with img BGR numpy. Returns tensor (N, 3, 224, 224) or None."""
    import cv2
    from PIL import Image
    import torch
    if not frames:
        return None
    imgs = []
    for _pct, img in frames:
        if img is None or img.size == 0:
            continue
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb)
        t = _get_transform()(pil)
        imgs.append(t)
    if not imgs:
        return None
    return torch.stack(imgs)


def _get_lr_model():
    global _lr_model, _lr_device
    if _lr_model is not None:
        return _lr_model, _lr_device
    if not MODEL_PATH.is_file():
        return None, None
    import torch
    from models.lr_model import build_model
    _lr_device = "cuda" if torch.cuda.is_available() else "cpu"
    _lr_model = build_model(num_classes=2, device=_lr_device)
    _lr_model.load_state_dict(torch.load(MODEL_PATH, map_location=_lr_device))
    _lr_model.eval()
    return _lr_model, _lr_device


def classify_left_right(frames):
    """
    frames: list of (pct, img) with img as numpy BGR (from thumbnails).
    Returns "L" or "R". Returns "?" if model file missing or error.
    """
    model, device = _get_lr_model()
    if model is None:
        return "?"
    x = _frames_to_tensor(frames)
    if x is None:
        return "?"
    try:
        import torch
        with torch.no_grad():
            out = model(x.to(device))
            preds = out.argmax(dim=1).cpu().numpy()
        majority = int(round(preds.mean()))
        return "L" if majority == 0 else "R"
    except Exception:
        return "?"


def get_video_resolution(video_path):
    """Returns '4K' or '720p' via ffprobe."""
    try:
        r = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=p=0",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return "720p"
        parts = r.stdout.strip().split("\n")[0].split(",")
        if len(parts) >= 2:
            w, h = int(parts[0].strip()), int(parts[1].strip())
            if w >= 1920 or h >= 1080:
                return "4K"
    except Exception:
        pass
    return "720p"


def get_video_metadata(video_path):
    """Returns {'resolution': '4K'|'720p', 'duration': float}."""
    res = get_video_resolution(video_path)
    duration = 0.0
    try:
        r = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=nk=1:nw=1",
                str(video_path),
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

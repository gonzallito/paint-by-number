"""Face detection, for a third and finest level of region allocation.

Subject-level allocation cannot rescue a portrait of someone in flat clothing. Measured on a
real photo: a man in a black tuxedo occupies 36% of the frame but offers almost no colour
boundaries, so however much budget the subject is granted, there is nothing in the suit to
spend it on. Meanwhile the face — a small fraction of the subject mask — is where the likeness
actually lives and where extra regions genuinely pay off.

So regions get three tiers rather than two, from finest to coarsest: **face, subject,
background**.

Uses OpenCV's built-in YuNet detector. The model is ~230KB (versus 176MB for the subject
segmenter) and is fetched on first use. Haar cascades were the obvious alternative but
``opencv-python-headless`` ships no cascade XML files at all, so they are not available offline.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

MODEL_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/"
    "face_detection_yunet/face_detection_yunet_2023mar.onnx"
)
MODEL_FILENAME = "yunet.onnx"
DOWNLOAD_TIMEOUT_S = 60

SCORE_THRESHOLD = 0.7
NMS_THRESHOLD = 0.3
TOP_K = 200

# Detected boxes are tight around the eyes/nose/mouth. Expanding covers forehead, chin and
# jaw, which carry as much likeness as the features themselves.
BOX_EXPAND = 1.35

_DETECTORS: dict[str, object] = {}


@dataclass
class Faces:
    """Detected faces and the mask covering them."""

    mask: np.ndarray  # uint8, 0 or 255
    count: int
    coverage: float  # fraction of the frame

    @property
    def found(self) -> bool:
        return self.count > 0


def model_path(cache_dir: str | Path) -> Path:
    return Path(cache_dir) / MODEL_FILENAME


def ensure_model(cache_dir: str | Path) -> Path | None:
    """Download the detector model if absent. Returns its path, or None if unavailable."""
    target = model_path(cache_dir)
    if target.exists() and target.stat().st_size > 0:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        request = urllib.request.Request(MODEL_URL, headers={"User-Agent": "pbn-pipeline/0.1"})
        with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_S) as response:
            payload = response.read()
        target.write_bytes(payload)
        return target
    except (urllib.error.URLError, TimeoutError, OSError):
        # Face detection is an enhancement, not a requirement: without it the pipeline still
        # produces a valid canvas using subject-level allocation.
        return None


def _detector(path: Path, size: tuple[int, int]):
    key = str(path)
    if key not in _DETECTORS:
        _DETECTORS[key] = cv2.FaceDetectorYN.create(
            str(path), "", size, SCORE_THRESHOLD, NMS_THRESHOLD, TOP_K
        )
    detector = _DETECTORS[key]
    detector.setInputSize(size)
    return detector


def detect(img: np.ndarray, cache_dir: str | Path) -> Faces | None:
    """Detect faces in ``img`` (RGB uint8). Returns None if the detector is unavailable."""
    path = ensure_model(cache_dir)
    if path is None:
        return None

    height, width = img.shape[:2]
    detector = _detector(path, (width, height))
    # YuNet expects BGR.
    _, detections = detector.detect(cv2.cvtColor(img, cv2.COLOR_RGB2BGR))

    mask = np.zeros((height, width), dtype=np.uint8)
    count = 0
    if detections is not None:
        for detection in detections:
            x, y, w, h = detection[:4]
            centre = (int(round(x + w / 2)), int(round(y + h / 2)))
            axes = (int(round(w * BOX_EXPAND / 2)), int(round(h * BOX_EXPAND / 2)))
            if axes[0] <= 0 or axes[1] <= 0:
                continue
            # An ellipse rather than the raw rectangle: a rectangle's corners fall outside the
            # head and would grant fine-detail treatment to whatever sits behind it.
            cv2.ellipse(mask, centre, axes, 0, 0, 360, 255, thickness=-1)
            count += 1

    return Faces(mask=mask, count=count, coverage=float((mask > 127).mean()))

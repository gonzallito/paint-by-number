"""Image IO and resizing.

Channel-order convention for the whole pipeline: **RGB uint8**.

OpenCV defaults to BGR, but PIL, matplotlib and scikit-image all use RGB, and most of
our rendering goes through PIL. The only OpenCV calls that actually care about channel
order are colour-space conversions, which we always spell explicitly (``COLOR_RGB2LAB``).
Keeping everything RGB avoids a whole category of silent red/blue-swap bugs.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

# Extensions we accept as pipeline input.
SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def load(path: str | Path) -> np.ndarray:
    """Load an image as RGB uint8, stripping any alpha channel."""
    path = Path(path)
    # Read via numpy so non-ASCII paths work; cv2.imread is unreliable with those.
    buf = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError(f"could not decode image: {path}")

    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
    if img.shape[2] == 4:
        # Composite onto white rather than dropping alpha, so transparent PNGs
        # do not acquire black fringes that then get quantised as a real colour.
        rgb = cv2.cvtColor(img[:, :, :3], cv2.COLOR_BGR2RGB).astype(np.float32)
        alpha = (img[:, :, 3:4].astype(np.float32)) / 255.0
        return np.clip(rgb * alpha + 255.0 * (1.0 - alpha), 0, 255).astype(np.uint8)
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def save(path: str | Path, img: np.ndarray) -> None:
    """Save an RGB uint8 image, creating parent directories as needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if img.ndim == 2:
        ok, buf = cv2.imencode(path.suffix, img)
    else:
        ok, buf = cv2.imencode(path.suffix, cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
    if not ok:
        raise ValueError(f"could not encode image: {path}")
    buf.tofile(str(path))


def fit_long_edge(img: np.ndarray, target: int) -> np.ndarray:
    """Scale so the long edge equals ``target``. Never upscales.

    Upscaling would invent detail that the segmentation would then dutifully turn into
    regions, so small inputs are left alone and reported as-is.
    """
    h, w = img.shape[:2]
    long_edge = max(h, w)
    if long_edge <= target:
        return img
    scale = target / long_edge
    new_size = (max(1, round(w * scale)), max(1, round(h * scale)))
    # INTER_AREA is the correct choice for downscaling; it averages rather than
    # point-samples, which suppresses the aliasing that would otherwise become speckle.
    return cv2.resize(img, new_size, interpolation=cv2.INTER_AREA)


def list_images(directory: str | Path) -> list[Path]:
    """Return supported image files in ``directory``, sorted by name."""
    directory = Path(directory)
    if not directory.is_dir():
        return []
    return sorted(
        p for p in directory.iterdir() if p.suffix.lower() in SUPPORTED_SUFFIXES and p.is_file()
    )

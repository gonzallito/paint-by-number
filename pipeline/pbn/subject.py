"""Subject / background separation.

The highest-leverage quality lever in the whole pipeline. A faithful quantisation of a
photo spreads its colour and detail budget evenly across the frame, which is why naive
conversions look muddy: the sofa behind the dog gets as much fidelity as the dog. Knowing
which pixels are the subject lets every later stage spend its budget where it matters.

Inference is cached on disk by image content hash, because during tuning the same images
get reprocessed dozens of times and the model costs ~0.5s per call.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import scipy.ndimage as ndi

from pbn import images

DEFAULT_MODEL = "u2net"

# Below this the detection is almost certainly spurious; above it there is no meaningful
# background left to simplify, so subject-aware treatment buys nothing.
MIN_COVERAGE = 0.03
MAX_COVERAGE = 0.97

# Keep any blob at least this fraction of the largest one, so two pets or two people in
# frame both survive instead of the smaller being discarded as noise.
BLOB_KEEP_RATIO = 0.10

_SESSIONS: dict[str, object] = {}


@dataclass
class Subject:
    """A cleaned-up subject mask."""

    mask: np.ndarray  # uint8, 0 or 255, same HxW as the input image
    coverage: float  # fraction of frame occupied by the subject
    model: str
    blobs: int  # number of distinct subject blobs retained


def is_available() -> bool:
    """True if the optional segmentation extra is installed."""
    try:
        import rembg  # noqa: F401
    except ImportError:
        return False
    return True


def warm(model: str = DEFAULT_MODEL) -> bool:
    """Create the session ahead of time. Returns False if the extra is not installed.

    Worth calling at service start-up. The u2net weights are a **176MB download** on first use,
    and without this the cost lands on whichever user happens to convert first — appearing to
    them as a conversion that hangs, since nothing reports a model download as progress.
    """
    if not is_available():
        return False
    _session(model)
    return True


def _session(model: str):
    """Lazily create and cache a rembg session (init costs ~2.4s)."""
    if model not in _SESSIONS:
        try:
            from rembg import new_session
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise ImportError(
                "subject segmentation requires the optional extra: `uv sync --extra segmentation`"
            ) from exc
        _SESSIONS[model] = new_session(model)
    return _SESSIONS[model]


def _clean_mask(alpha: np.ndarray, long_edge: int) -> tuple[np.ndarray, int]:
    """Turn a soft alpha channel into a clean binary mask. Returns (mask, blob count)."""
    binary = (alpha > 127).astype(np.uint8)

    # Kernel scaled to image size so behaviour is resolution-independent.
    k = max(3, int(round(long_edge * 0.006)) | 1)  # odd, >=3
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))

    # Close first: bridges thin gaps (a leg against a similar-coloured background).
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    # Then fill interior holes, which the model often leaves in dark or textured areas.
    binary = ndi.binary_fill_holes(binary.astype(bool)).astype(np.uint8)
    # Open to shed thin spurs and stray specks without eroding the silhouette.
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)

    # Drop insignificant blobs, but keep genuinely multiple subjects.
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    if count <= 1:
        return np.zeros_like(binary, dtype=np.uint8), 0
    areas = stats[1:, cv2.CC_STAT_AREA]
    threshold = areas.max() * BLOB_KEEP_RATIO
    keep = {i + 1 for i, area in enumerate(areas) if area >= threshold}
    cleaned = np.isin(labels, list(keep)).astype(np.uint8) * 255
    return cleaned, len(keep)


def detect(
    img: np.ndarray,
    model: str = DEFAULT_MODEL,
    cache_dir: str | Path | None = None,
) -> Subject | None:
    """Detect the subject in ``img`` (RGB uint8).

    Returns ``None`` when no usable subject is found, in which case callers should fall
    back to uniform whole-frame treatment rather than failing.
    """
    h, w = img.shape[:2]
    alpha: np.ndarray | None = None

    cache_path: Path | None = None
    if cache_dir is not None:
        digest = hashlib.sha1(np.ascontiguousarray(img).tobytes()).hexdigest()[:16]
        cache_path = Path(cache_dir) / f"{model}_{digest}_{w}x{h}.png"
        if cache_path.exists():
            cached = images.load(cache_path)
            alpha = cached[:, :, 0] if cached.ndim == 3 else cached

    if alpha is None:
        from PIL import Image
        from rembg import remove

        out = remove(Image.fromarray(img), session=_session(model))
        rgba = np.array(out)
        if rgba.ndim != 3 or rgba.shape[2] != 4:
            return None
        alpha = rgba[:, :, 3]
        if cache_path is not None:
            images.save(cache_path, alpha)

    mask, blobs = _clean_mask(alpha, long_edge=max(h, w))
    coverage = float((mask > 127).mean())
    if not (MIN_COVERAGE < coverage < MAX_COVERAGE):
        return None
    return Subject(mask=mask, coverage=coverage, model=model, blobs=blobs)

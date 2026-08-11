"""Colour space helpers.

Everything that compares colours does so in **CIELAB with true ranges** (L 0-100,
a/b roughly -127..127), not OpenCV's 8-bit LAB encoding where all three channels are
squashed into 0-255 with a 128 offset. The distinction matters: ΔE thresholds are only
meaningful in real CIELAB units, and the 8-bit encoding silently rescales a and b by
about 1.27x, so a threshold tuned in one space is wrong in the other.

Distances are CIE76 (plain Euclidean in LAB). CIEDE2000 is more perceptually faithful
but far slower, and the merge stage evaluates hundreds of thousands of pairs. CIE76 is
standard practice for segmentation work and adequate for deciding which regions to fuse.
"""

from __future__ import annotations

import cv2
import numpy as np

# Rough maximum CIE76 distance between two sRGB colours (black to white is 100 in L
# alone; extreme chroma pairs reach ~150). Used to normalise costs into 0..1.
MAX_DELTA_E = 150.0


def rgb_to_lab(img: np.ndarray) -> np.ndarray:
    """RGB uint8 -> CIELAB float32 with true ranges."""
    scaled = img.astype(np.float32) / 255.0
    return cv2.cvtColor(scaled, cv2.COLOR_RGB2LAB)


def lab_to_rgb(lab: np.ndarray) -> np.ndarray:
    """CIELAB float32 -> RGB uint8."""
    rgb = cv2.cvtColor(lab.astype(np.float32), cv2.COLOR_LAB2RGB)
    return np.clip(rgb * 255.0, 0, 255).astype(np.uint8)


def lab_rows_to_rgb(lab_rows: np.ndarray) -> np.ndarray:
    """(N,3) CIELAB -> (N,3) RGB uint8, for palettes rather than images."""
    as_image = lab_rows.reshape(-1, 1, 3).astype(np.float32)
    return lab_to_rgb(as_image).reshape(-1, 3)


def delta_e(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """CIE76 distance. Broadcasts over the leading axes of ``a`` and ``b``."""
    return np.sqrt(np.sum((np.asarray(a, np.float32) - np.asarray(b, np.float32)) ** 2, axis=-1))


def nearest_palette_index(lab_pixels: np.ndarray, palette_lab: np.ndarray) -> np.ndarray:
    """Assign each LAB pixel to its closest palette entry.

    Computed as an incremental argmin over palette entries rather than one big broadcast:
    a 2-megapixel image against 16 colours would otherwise materialise a 96M-element
    distance array (~380MB) for no benefit.
    """
    flat = lab_pixels.reshape(-1, 3).astype(np.float32)
    best_dist = np.full(flat.shape[0], np.inf, dtype=np.float32)
    best_index = np.zeros(flat.shape[0], dtype=np.int32)
    for index, colour in enumerate(palette_lab.astype(np.float32)):
        dist = np.sum((flat - colour) ** 2, axis=1)
        closer = dist < best_dist
        best_dist[closer] = dist[closer]
        best_index[closer] = index
    return best_index.reshape(lab_pixels.shape[:2])


def luminance_order(palette_lab: np.ndarray) -> np.ndarray:
    """Indices that sort a palette light-to-dark.

    Ordering by lightness rather than by pixel frequency has two payoffs. For the user,
    the numbered canvas reads as a value study while it is being filled, and finding
    "the next lightest" is intuitive. Internally, it makes neighbouring palette indices
    perceptually adjacent, which is what lets :func:`pbn.quantize.despeckle` run a plain
    median filter directly on the label map.
    """
    return np.argsort(-palette_lab[:, 0].astype(np.float64), kind="stable")

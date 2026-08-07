"""Canvas rendering: outlines, numbers, filled preview and palette strip.

Nothing here is part of the eventual mobile artifact — the app will draw its own canvas
from the region-ID map. These renders exist so a human can look at pipeline output and
judge it, which is the entire purpose of Phase 0.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from skimage import segmentation as skseg

from pbn.numbering import Numbering

# Preference order: a medium weight reads better than regular at small sizes against
# outline clutter, without the heaviness of bold.
_FONT_CANDIDATES = (
    "/usr/share/fonts/google-noto/NotoSans-Medium.ttf",
    "/usr/share/fonts/google-noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/google-noto/NotoSans-SemiBold.ttf",
)

OUTLINE_RGB = (88, 88, 96)
CANVAS_RGB = (255, 255, 255)
NUMBER_RGB = (70, 70, 78)
SUBJECT_TINT_RGB = (255, 90, 80)
# Leaders are drawn lighter than the region outlines so they read as annotation rather than
# as a boundary the user might try to fill.
LEADER_RGB = (150, 150, 158)


@lru_cache(maxsize=1)
def _font_path() -> str | None:
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None


@lru_cache(maxsize=256)
def _font(size: int) -> ImageFont.ImageFont:
    """Font cache. Sizes are rounded by the caller so this stays small."""
    path = _font_path()
    if path is None:
        # Pillow >= 10.1 can scale its bundled default font.
        return ImageFont.load_default(size=size)
    return ImageFont.truetype(path, size=size)


def boundaries(labels: np.ndarray) -> np.ndarray:
    """Boolean mask of region borders.

    ``mode="inner"`` keeps the border inside each region, so borders stay one pixel wide
    and never straddle two regions. A thick mode would double every line and visually
    close up the smallest regions.
    """
    return skseg.find_boundaries(labels, mode="inner")


def filled_canvas(
    labels: np.ndarray, region_colour: np.ndarray, palette_rgb: np.ndarray
) -> np.ndarray:
    """The finished artwork: every region flooded with its palette colour."""
    return palette_rgb[region_colour[labels]]


def outline_canvas(
    labels: np.ndarray,
    numbering: Numbering,
    region_colour: np.ndarray,
    draw_numbers: bool = True,
) -> np.ndarray:
    """The colourable page: outlines on white, with each region's number placed inside."""
    canvas = np.full((*labels.shape, 3), CANVAS_RGB, dtype=np.uint8)
    canvas[boundaries(labels)] = OUTLINE_RGB

    if not draw_numbers:
        return canvas

    image = Image.fromarray(canvas)
    draw = ImageDraw.Draw(image)
    labelled = np.flatnonzero(numbering.fits)

    # Draw every connector first, so no leader crosses over a number.
    for region in labelled:
        if not numbering.has_leader[region]:
            continue
        anchor = tuple(int(v) for v in numbering.centres[region])
        target = tuple(int(v) for v in numbering.label_positions[region])
        draw.line([anchor, target], fill=LEADER_RGB, width=1)
        # A dot marks which region the number belongs to; without it a leader pointing into a
        # cluster of slivers is ambiguous.
        draw.ellipse([anchor[0] - 1, anchor[1] - 1, anchor[0] + 1, anchor[1] + 1], fill=LEADER_RGB)

    for region in labelled:
        height = float(numbering.digit_heights[region])
        # Round the requested size so the font cache actually hits.
        size = max(6, int(round(height)))
        x, y = (int(v) for v in numbering.label_positions[region])
        draw.text(
            (x, y),
            str(int(region_colour[region]) + 1),
            font=_font(size),
            fill=NUMBER_RGB,
            anchor="mm",  # centre the glyph box on the label position
        )
    return np.asarray(image)


def subject_overlay(img: np.ndarray, mask: np.ndarray | None, alpha: float = 0.45) -> np.ndarray:
    """Original image with the detected subject tinted, for eyeballing segmentation."""
    if mask is None:
        return img.copy()
    out = img.astype(np.float32)
    tint = np.asarray(SUBJECT_TINT_RGB, dtype=np.float32)
    selected = mask > 127
    out[selected] = out[selected] * (1.0 - alpha) + tint * alpha
    return np.clip(out, 0, 255).astype(np.uint8)


def palette_strip(
    palette_rgb: np.ndarray,
    width: int,
    height: int = 64,
    from_subject: np.ndarray | None = None,
) -> np.ndarray:
    """Numbered swatch strip, mirroring the app's palette tray.

    Swatches are already ordered light to dark by the quantiser, so the strip doubles as a
    check that luminance ordering survived.
    """
    n = int(palette_rgb.shape[0])
    strip = np.full((height, width, 3), 250, dtype=np.uint8)
    if n == 0:
        return strip

    image = Image.fromarray(strip)
    draw = ImageDraw.Draw(image)
    swatch_w = width / n
    font = _font(max(9, int(height * 0.34)))

    for index in range(n):
        x0 = int(round(index * swatch_w))
        x1 = int(round((index + 1) * swatch_w)) - 1
        colour = tuple(int(c) for c in palette_rgb[index])
        draw.rectangle([x0, 0, x1, height - 18], fill=colour, outline=(210, 210, 214))

        # Label in whichever of black/white contrasts better with the swatch.
        luma = 0.299 * colour[0] + 0.587 * colour[1] + 0.114 * colour[2]
        draw.text(
            ((x0 + x1) / 2, (height - 18) / 2),
            str(index + 1),
            font=font,
            fill=(20, 20, 20) if luma > 140 else (245, 245, 245),
            anchor="mm",
        )
        # Underline the entries that came from the subject k-means.
        if from_subject is not None and index < from_subject.shape[0] and from_subject[index]:
            draw.line([x0 + 2, height - 14, x1 - 2, height - 14], fill=SUBJECT_TINT_RGB, width=3)

    return np.asarray(image)

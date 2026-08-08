"""Contact sheets for visual review.

Phase 0's gate is a human looking at output and deciding whether it is good enough to build
a product on, so this module exists to make that judgement as easy as possible.

Sheets are composited directly with PIL rather than through matplotlib. An earlier
matplotlib/gridspec version produced large unpredictable vertical gaps, floated the palette
strip under the wrong columns, and drifted captions away from the row they described. For a
fixed grid of pre-rendered images, laying out pixels directly is both simpler and exact.

Every row carries a **1:1 detail crop** of the colourable page. Without it the page is shown
scaled to fit and the numbers become illegible in the sheet itself, which defeats the point:
whether the numbers are readable is precisely what needs judging.

Sheets are written as PNG and committed to ``out/`` so they render inline on GitHub. The
reviewer cannot browse the sandbox filesystem, so anything meant to be *seen* must land in
the repository.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from pbn import images, render

PANEL_HEIGHT = 300
GAP = 14
MARGIN = 20
LABEL_WIDTH = 92
CAPTION_WIDTH = 330
PALETTE_HEIGHT = 46
HEADER_HEIGHT = 26

BACKGROUND = (255, 255, 255)
RULE = (222, 222, 226)
HEADING = (40, 40, 46)
BODY = (60, 60, 66)

COLUMNS = (
    "original",
    "subject + faces",
    "page as first seen",
    "detail at 1:1 (all numbers)",
    "filled result",
)


@dataclass
class SheetRow:
    """One image/variant combination, already rendered."""

    panels: list[np.ndarray]
    palette: np.ndarray
    title: str
    caption: str


def _fit_height(img: np.ndarray, height: int) -> np.ndarray:
    scale = height / img.shape[0]
    width = max(1, round(img.shape[1] * scale))
    interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_NEAREST
    return cv2.resize(img, (width, height), interpolation=interpolation)


def _detail_crop(img: np.ndarray, height: int, width: int, centre: tuple[int, int]) -> np.ndarray:
    """Native-resolution crop around ``centre``, clamped to the image, padded if too small.

    Nearest-neighbour is never applied here — the crop is taken at 1:1 so outline weight and
    digit size appear exactly as the pipeline produced them.
    """
    h, w = img.shape[:2]
    cx, cy = centre
    x0 = int(np.clip(cx - width // 2, 0, max(0, w - width)))
    y0 = int(np.clip(cy - height // 2, 0, max(0, h - height)))
    crop = img[y0 : y0 + height, x0 : x0 + width]

    if crop.shape[0] < height or crop.shape[1] < width:
        padded = np.full((height, width, 3), BACKGROUND, dtype=np.uint8)
        padded[: crop.shape[0], : crop.shape[1]] = crop
        crop = padded
    return crop


def build_row(
    original: np.ndarray,
    subject_mask: np.ndarray | None,
    labels: np.ndarray,
    region_colour: np.ndarray,
    palette_rgb: np.ndarray,
    numbering,
    title: str,
    caption: str,
    from_subject: np.ndarray | None = None,
    face_mask: np.ndarray | None = None,
) -> SheetRow:
    """Render every panel for one image/variant combination."""
    # Two renders of the same page. At fit-to-screen only regions large enough to carry a
    # legible number show one; the 1:1 crop shows every number, which is what the user sees once
    # zoomed into that area. Side by side they demonstrate the zoom-reveal behaviour.
    outline_first_seen = render.outline_canvas(labels, numbering, region_colour, zoom=1.0)
    outline_all = render.outline_canvas(labels, numbering, region_colour, zoom=None)
    filled = render.filled_canvas(labels, region_colour, palette_rgb)

    # Centre the 1:1 crop on the subject when there is one, since that is where detail
    # matters; otherwise use the frame centre.
    if subject_mask is not None and (subject_mask > 127).any():
        ys, xs = np.nonzero(subject_mask > 127)
        centre = (int(xs.mean()), int(ys.mean()))
    else:
        centre = (labels.shape[1] // 2, labels.shape[0] // 2)

    aspect = original.shape[1] / original.shape[0]
    detail = _detail_crop(outline_all, PANEL_HEIGHT, max(80, int(PANEL_HEIGHT * aspect)), centre)

    panels = [
        _fit_height(original, PANEL_HEIGHT),
        _fit_height(
            render.subject_overlay(original, subject_mask, face_mask=face_mask), PANEL_HEIGHT
        ),
        _fit_height(outline_first_seen, PANEL_HEIGHT),
        detail,
        _fit_height(filled, PANEL_HEIGHT),
    ]
    palette_width = sum(p.shape[1] for p in panels) + GAP * (len(panels) - 1)
    palette = render.palette_strip(
        palette_rgb, width=palette_width, height=PALETTE_HEIGHT, from_subject=from_subject
    )
    return SheetRow(panels=panels, palette=palette, title=title, caption=caption)


def write_sheet(rows: list[SheetRow], path: str | Path) -> Path:
    """Composite rows into one PNG."""
    if not rows:
        raise ValueError("no rows to write")
    path = Path(path)

    panel_widths = [p.shape[1] for p in rows[0].panels]
    strip_width = sum(panel_widths) + GAP * (len(panel_widths) - 1)
    total_width = MARGIN * 2 + LABEL_WIDTH + strip_width + GAP + CAPTION_WIDTH
    row_height = PANEL_HEIGHT + GAP + max(PALETTE_HEIGHT, rows[0].palette.shape[0])
    total_height = MARGIN * 2 + HEADER_HEIGHT + len(rows) * (row_height + GAP * 2)

    canvas = Image.new("RGB", (total_width, total_height), BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    header_font = render._font(15)
    title_font = render._font(14)
    caption_font = render._font(13)

    # Column headings, aligned to each panel's left edge.
    x = MARGIN + LABEL_WIDTH
    for width, label in zip(panel_widths, COLUMNS, strict=True):
        draw.text((x, MARGIN), label, font=header_font, fill=HEADING)
        x += width + GAP
    draw.text(
        (MARGIN + LABEL_WIDTH + strip_width + GAP, MARGIN),
        "diagnostics",
        font=header_font,
        fill=HEADING,
    )

    y = MARGIN + HEADER_HEIGHT
    for index, row in enumerate(rows):
        if index:
            draw.line([(MARGIN, y - GAP), (total_width - MARGIN, y - GAP)], fill=RULE, width=1)

        for line_number, line in enumerate(row.title.split("\n")):
            draw.text((MARGIN, y + 4 + line_number * 18), line, font=title_font, fill=HEADING)

        x = MARGIN + LABEL_WIDTH
        for panel in row.panels:
            canvas.paste(Image.fromarray(panel), (x, y))
            x += panel.shape[1] + GAP

        canvas.paste(Image.fromarray(row.palette), (MARGIN + LABEL_WIDTH, y + PANEL_HEIGHT + GAP))

        caption_x = MARGIN + LABEL_WIDTH + strip_width + GAP
        for line_number, line in enumerate(row.caption.split("\n")):
            draw.text((caption_x, y + 4 + line_number * 17), line, font=caption_font, fill=BODY)

        y += row_height + GAP * 2

    images.save(path, np.asarray(canvas))
    return path

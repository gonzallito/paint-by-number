"""Recalibrate the region-count floors against a real corpus.

The Phase 0 constants were fitted to 7 development images whose subjects were large and
high-texture. Real uploads have smaller, often flat subjects (a black tuxedo has almost no
colour boundaries), so the floors merge far too aggressively: measured 0.9-8.4% of initial
regions surviving, giving 16-259 region canvases.

Sweeps the two floors that control this and reports region count against the cost of
relaxing them (unnumbered fraction).
"""

import sys

import numpy as np

from pbn import color, images, numbering, preprocess, quantize, segment, subject

CORPUS = sys.argv[1] if len(sys.argv) > 1 else "../corpus"
N_COLOURS = 18
BUDGET = 1500
TARGET_LOW, TARGET_HIGH = 250, 1500

RADIUS_SCALES = (0.30, 0.40, 0.50, 0.60)
BACKGROUND_MULTIPLIERS = (1.0, 1.4, 1.8, 2.6)

prepared = []
for path in images.list_images(CORPUS):
    raw = images.load(path)
    working = images.fit_long_edge(raw, 1400)
    found = subject.detect(working, cache_dir=".cache/subject")
    mask = None if found is None else found.mask
    flat = preprocess.flatten_differential(working, mask)
    quantised = quantize.quantize(flat, N_COLOURS, subject_mask=mask)
    prepared.append((path.stem, quantised, color.rgb_to_lab(flat), mask, found))

print(f"corpus: {len(prepared)} images from {CORPUS}\n")
print("Region count (and unnumbered %) by radius floor x background multiplier")
header = f"{'image':16s} {'floor':>6s}" + "".join(
    f"{f'bg x{m}':>15s}" for m in BACKGROUND_MULTIPLIERS
)
print(header)
print("-" * len(header))

grid: dict[tuple[float, float], list[tuple[int, float]]] = {}

for stem, quantised, lab, mask, _found in prepared:
    for scale in RADIUS_SCALES:
        row = f"{stem:16s} {scale:6.2f}"
        for multiplier in BACKGROUND_MULTIPLIERS:
            original = segment.BACKGROUND_MIN_RADIUS_MULTIPLIER
            segment.BACKGROUND_MIN_RADIUS_MULTIPLIER = multiplier
            try:
                seg = segment.segment(
                    quantised.labels,
                    quantised.n_colours,
                    lab,
                    quantised.palette_lab,
                    budget=BUDGET,
                    subject_mask=mask,
                    min_radius_scale=scale,
                )
                num = numbering.place(seg.labels, seg.region_colour, seg.n_regions)
            finally:
                segment.BACKGROUND_MIN_RADIUS_MULTIPLIER = original
            grid.setdefault((scale, multiplier), []).append(
                (seg.n_regions, num.unlabelled_fraction)
            )
            row += f"{seg.n_regions:9,d} {num.unlabelled_fraction:4.0%}"
        print(row)
    print()

print("=" * len(header))
print(f"SUMMARY: median regions / mean unnumbered / images inside {TARGET_LOW}-{TARGET_HIGH}")
print(f"{'floor':>6s}" + "".join(f"{f'bg x{m}':>22s}" for m in BACKGROUND_MULTIPLIERS))
print("-" * (6 + 22 * len(BACKGROUND_MULTIPLIERS)))
for scale in RADIUS_SCALES:
    row = f"{scale:6.2f}"
    for multiplier in BACKGROUND_MULTIPLIERS:
        rows = grid[(scale, multiplier)]
        counts = [c for c, _ in rows]
        unnumbered = [u for _, u in rows]
        in_band = sum(1 for c in counts if TARGET_LOW <= c <= TARGET_HIGH)
        row += (
            f"{int(np.median(counts)):8,d} {np.mean(unnumbered):5.0%} "
            f"{in_band:2d}/{len(counts):<2d} "
        )
    print(row)

print("\nSubject region share vs area share (is the subject actually getting budget?)")
print(f"{'image':16s} {'area':>6s} {'x1.0':>7s} {'x1.8':>7s} {'x2.6':>7s}")
print("-" * 48)
for stem, quantised, lab, mask, found in prepared:
    if found is None:
        continue
    row = f"{stem:16s} {found.coverage:6.0%}"
    for multiplier in (1.0, 1.8, 2.6):
        original = segment.BACKGROUND_MIN_RADIUS_MULTIPLIER
        segment.BACKGROUND_MIN_RADIUS_MULTIPLIER = multiplier
        try:
            seg = segment.segment(
                quantised.labels,
                quantised.n_colours,
                lab,
                quantised.palette_lab,
                budget=BUDGET,
                subject_mask=mask,
                min_radius_scale=0.40,
            )
        finally:
            segment.BACKGROUND_MIN_RADIUS_MULTIPLIER = original
        row += f"{seg.region_is_subject.mean():7.0%}"
    print(row)

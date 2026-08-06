"""How many regions end up with no legible number, and is placement actually inside?"""

import time

import numpy as np

from pbn import color, images, numbering, preprocess, quantize, segment, subject

WORK = 1400
N_COLOURS = 16
BUDGET = 1500

print(f"{'image':20s} {'regions':>8s} {'place s':>8s} {'r median':>9s} {'r min':>6s} "
      f"{'unlabelled':>11s} {'centre in region':>17s}")
print("-" * 88)

totals = []
for p in images.list_images("../corpus/dev"):
    img = images.fit_long_edge(images.load(p), WORK)
    sub = subject.detect(img, cache_dir=".cache/subject")
    mask = None if sub is None else sub.mask
    flat = preprocess.flatten_differential(img, mask)
    q = quantize.quantize(flat, N_COLOURS, subject_mask=mask)
    lab = color.rgb_to_lab(flat)
    seg = segment.segment(
        q.labels, q.n_colours, lab, q.palette_lab, budget=BUDGET, subject_mask=mask
    )

    t = time.time()
    num = numbering.place(seg.labels, seg.region_colour, seg.n_regions)
    elapsed = time.time() - t

    # Correctness: the chosen centre must lie inside its own region.
    xs, ys = num.centres[:, 0], num.centres[:, 1]
    inside = seg.labels[ys, xs] == np.arange(seg.n_regions)
    inside_pct = inside.mean()

    totals.append(num.unlabelled_fraction)
    print(f"{p.stem:20s} {seg.n_regions:8,d} {elapsed:7.2f}s "
          f"{np.median(num.radii):9.1f} {num.radii.min():6.1f} "
          f"{num.unlabelled_fraction:10.1%} {inside_pct:16.1%}")

print("-" * 88)
print(f"{'mean unlabelled':20s} {np.mean(totals):>8.1%}")

print("\n" + "=" * 88)
print("Why regions fail: inscribed radius vs area (thin regions have area but no room)")
print(f"{'image':20s} {'area>=floor':>12s} {'radius fails':>13s} {'thin (area ok, r bad)':>22s}")
print("-" * 88)
for p in images.list_images("../corpus/dev"):
    img = images.fit_long_edge(images.load(p), WORK)
    sub = subject.detect(img, cache_dir=".cache/subject")
    mask = None if sub is None else sub.mask
    flat = preprocess.flatten_differential(img, mask)
    q = quantize.quantize(flat, N_COLOURS, subject_mask=mask)
    lab = color.rgb_to_lab(flat)
    seg = segment.segment(
        q.labels, q.n_colours, lab, q.palette_lab, budget=BUDGET, subject_mask=mask
    )
    num = numbering.place(seg.labels, seg.region_colour, seg.n_regions)

    long_edge = max(seg.labels.shape)
    floor = (
        segment.RADIUS_REF_AT_1400
        * segment.DEFAULT_MIN_RADIUS_SCALE
        * (long_edge / segment.REFERENCE_LONG_EDGE) ** 2
    )
    area_ok = seg.region_area >= floor
    radius_bad = ~num.fits
    thin = int((area_ok & radius_bad).sum())
    print(f"{p.stem:20s} {int(area_ok.sum()):12,d} {int(radius_bad.sum()):13,d} {thin:22,d}")

print("\n" + "=" * 88)
print(f"Required inscribed radius at min digit height {numbering.MIN_DIGIT_HEIGHT_AT_1400:.0f}px:")
for digits in (1, 2):
    print(f"  {digits}-digit number -> radius >= "
          f"{numbering.required_radius(digits, numbering.MIN_DIGIT_HEIGHT_AT_1400):.1f}px")

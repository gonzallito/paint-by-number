"""How far should the palette go?

Commercial custom photo-to-paint-by-number services sell 24 / 36 / 48 colour tiers and steer
portraits toward 36-48. Our variants shipped 12 / 18 / 24, i.e. one tier low throughout.

An earlier sweep judged palette size by *region count* and concluded it barely helped. That was
the wrong metric: more colours mainly buys colour **fidelity**, which is what "it doesn't look
like the photo" actually means. This measures fidelity as mean CIE76 reconstruction error, split
by subject and background, alongside the costs (region count, unnumberable fraction, and how
much of the requested palette survives deduplication).
"""

import sys

import numpy as np

from pbn import color, images, numbering, preprocess, quantize, segment, subject

CORPUS = sys.argv[1] if len(sys.argv) > 1 else "../corpus"
COLOURS = (18, 24, 32, 40, 48, 56)
RADIUS_FLOOR = 0.38  # the `detailed` variant, which the reviewer preferred
BUDGET = 2000

prepared = []
for path in images.list_images(CORPUS):
    working = images.fit_long_edge(images.load(path), 1400)
    found = subject.detect(working, cache_dir=".cache/subject")
    mask = None if found is None else found.mask
    flat = preprocess.flatten_differential(working, mask)
    prepared.append((path.stem, flat, color.rgb_to_lab(flat), mask))

print(f"corpus: {len(prepared)} images, radius floor {RADIUS_FLOOR}\n")
print("Mean CIE76 reconstruction error inside the subject (lower = more like the photo)")
print(f"{'image':16s}" + "".join(f"{f'k={k}':>9s}" for k in COLOURS))
print("-" * (16 + 9 * len(COLOURS)))

fidelity: dict[int, list[float]] = {k: [] for k in COLOURS}
kept: dict[int, list[int]] = {k: [] for k in COLOURS}
regions: dict[int, list[int]] = {k: [] for k in COLOURS}
unnumbered: dict[int, list[float]] = {k: [] for k in COLOURS}

for stem, flat, lab, mask in prepared:
    row = f"{stem:16s}"
    for k in COLOURS:
        q = quantize.quantize(flat, k, subject_mask=mask)
        approx = q.palette_lab[q.labels]
        err = color.delta_e(lab, approx)
        inside = err[mask > 127].mean() if mask is not None and (mask > 127).any() else err.mean()

        seg = segment.segment(
            q.labels,
            q.n_colours,
            lab,
            q.palette_lab,
            budget=BUDGET,
            subject_mask=mask,
            min_radius_scale=RADIUS_FLOOR,
        )
        num = numbering.place(seg.labels, seg.region_colour, seg.n_regions)

        fidelity[k].append(float(inside))
        kept[k].append(q.n_colours)
        regions[k].append(seg.n_regions)
        unnumbered[k].append(num.unlabelled_fraction)
        row += f"{inside:9.2f}"
    print(row)

print("-" * (16 + 9 * len(COLOURS)))
print(f"{'mean':16s}" + "".join(f"{np.mean(fidelity[k]):9.2f}" for k in COLOURS))
base = np.mean(fidelity[COLOURS[0]])
print(f"{'vs k=18':16s}" + "".join(f"{np.mean(fidelity[k]) / base - 1:8.0%} " for k in COLOURS))

print("\n" + "=" * 70)
print("COSTS")
print(f"{'requested k':>12s} {'kept':>7s} {'regions':>9s} {'unnumbered':>11s} {'fidelity':>9s}")
print("-" * 70)
for k in COLOURS:
    print(
        f"{k:12d} {int(np.median(kept[k])):7d} {int(np.median(regions[k])):9,d} "
        f"{np.mean(unnumbered[k]):10.1%} {np.mean(fidelity[k]):9.2f}"
    )

print(f"\nDeduplication threshold is DELTA_E={quantize.DEDUPE_DELTA_E}. If 'kept' falls well")
print("below 'requested', the threshold is the binding constraint, not k-means.")

print("\n" + "=" * 70)
print("Digit burden: numbers above 9 need more room than single digits")
for digits in (1, 2):
    need = numbering.required_radius(digits, numbering.MIN_DIGIT_HEIGHT_AT_1400)
    print(f"  {digits}-digit -> inscribed radius >= {need:.1f}px at 1400px")
print("A 48-colour palette makes ~80% of numbers two digits, so the numbering floor rises.")

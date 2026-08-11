"""Are 'more colours' and 'uniform coarse regions' compatible, or do they fight?

Fidelity is capped jointly by palette size AND region granularity: every region is filled with
one flat colour, so once within-region variation dominates, extra palette entries cannot help.
This tests a large palette against a UNIFORM, deliberately coarse floor with the face tier
disabled -- i.e. exactly what the reviewer asked for.
"""

import sys

import numpy as np

from pbn import color, images, preprocess, quantize, segment, subject

CORPUS = sys.argv[1] if len(sys.argv) > 1 else "../corpus"
COLOURS = (36, 48, 96, 150)
FLOOR = 0.60  # uniform and coarse, like the `simple` variant
BUDGET = 4000

# Neutralise the face tier: the reviewer explicitly wants uniform detail, not a detailed face.
segment.FACE_MIN_RADIUS_MULTIPLIER = 1.0

print(f"uniform floor {FLOOR}, face tier OFF, budget {BUDGET}")
print("err = mean CIE76 over the WHOLE image (region fill vs original)")
print(f"{'image':14s}" + "".join(f"{f'k={k}':>26s}" for k in COLOURS))
print(f"{'':14s}" + "   kept regions   err" * len(COLOURS))
print("-" * (14 + 26 * len(COLOURS)))

agg = {k: {"e": [], "n": [], "kept": []} for k in COLOURS}
for p in images.list_images(CORPUS):
    w = images.fit_long_edge(images.load(p), 1400)
    s = subject.detect(w, cache_dir=".cache/subject")
    mask = None if s is None else s.mask
    simp = preprocess.background_simplification(w, mask)
    flat = preprocess.flatten_differential(w, mask, simplify_background=simp)
    lab_src = color.rgb_to_lab(w)  # compare against the ORIGINAL, not the flattened version
    row = f"{p.stem:14s}"
    for k in COLOURS:
        q = quantize.quantize(flat, k, subject_mask=mask)
        lab = color.rgb_to_lab(flat)
        seg = segment.segment(
            q.labels,
            q.n_colours,
            lab,
            q.palette_lab,
            budget=BUDGET,
            subject_mask=mask,
            min_radius_scale=FLOOR,
        )
        # What the user actually sees: every region flooded with its single palette colour.
        filled_lab = q.palette_lab[seg.region_colour[seg.labels]]
        err = float(color.delta_e(lab_src, filled_lab).mean())
        agg[k]["e"].append(err)
        agg[k]["n"].append(seg.n_regions)
        agg[k]["kept"].append(q.n_colours)
        row += f"{q.n_colours:7d}{seg.n_regions:8,d}{err:7.2f}"
    print(row)

print("-" * (14 + 26 * len(COLOURS)))
print(
    f"{'mean':14s}"
    + "".join(
        f"{int(np.mean(agg[k]['kept'])):7d}{int(np.mean(agg[k]['n'])):8,d}{np.mean(agg[k]['e']):7.2f}"
        for k in COLOURS
    )
)
base = np.mean(agg[COLOURS[0]]["e"])
print(f"\n{'vs k=36':14s}" + "".join(f"{np.mean(agg[k]['e']) / base - 1:>25.0%} " for k in COLOURS))
print("\nIf err barely falls past ~48, region granularity is the binding constraint and a")
print("larger palette is cosmetic. If it keeps falling, more colours genuinely help.")

"""The face tier can generate more labels than physically fit.

Two levers: a coarser face floor (fewer tiny regions) or a longer leader reach (labels travel
further to find space). Label packing is a hard ceiling on region count, independent of region
geometry, so one of these has to give.
"""

import sys

import numpy as np

from pbn import images, numbering, pipeline, segment

CORPUS = sys.argv[1] if len(sys.argv) > 1 else "../corpus"
COMBOS = ((0.55, 10.0), (0.55, 16.0), (0.70, 10.0), (0.70, 16.0))

print("detailed variant. combos = (face floor multiplier, leader max length factor)")
print(f"{'image':15s}" + "".join(f"{f'{m}/{le:.0f}':>20s}" for m, le in COMBOS))
print(f"{'':15s}" + "  regions leader unnum" * len(COMBOS))
print("-" * (15 + 20 * len(COMBOS)))

agg = {c: {"n": [], "l": [], "u": []} for c in COMBOS}
for p in images.list_images(CORPUS):
    img = images.load(p)
    row = f"{p.stem:15s}"
    for combo in COMBOS:
        mult, reach = combo
        o_m, o_r = segment.FACE_MIN_RADIUS_MULTIPLIER, numbering.LEADER_MAX_LENGTH_FACTOR
        segment.FACE_MIN_RADIUS_MULTIPLIER = mult
        numbering.LEADER_MAX_LENGTH_FACTOR = reach
        try:
            c = pipeline.convert(
                img,
                pipeline.VARIANTS["detailed"],
                subject_cache=".cache/subject",
                model_cache=".cache/models",
            )
        finally:
            segment.FACE_MIN_RADIUS_MULTIPLIER = o_m
            numbering.LEADER_MAX_LENGTH_FACTOR = o_r
        agg[combo]["n"].append(c.n_regions)
        agg[combo]["l"].append(c.numbering.leader_fraction)
        agg[combo]["u"].append(c.unlabelled_fraction)
        row += f"{c.n_regions:9,d}{c.numbering.leader_fraction:7.0%}{c.unlabelled_fraction:6.1%}"
    print(row)

print("-" * (15 + 20 * len(COMBOS)))
print(
    f"{'median / mean':15s}"
    + "".join(
        f"{int(np.median(agg[c]['n'])):9,d}{np.mean(agg[c]['l']):7.0%}{np.mean(agg[c]['u']):6.1%}"
        for c in COMBOS
    )
)
print(f"{'worst unnum':15s}" + "".join(f"{'':16s}{np.max(agg[c]['u']):4.1%}" for c in COMBOS))

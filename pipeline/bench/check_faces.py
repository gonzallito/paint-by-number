"""Does the face tier raise region density where the likeness lives?

Metric: regions per megapixel inside the face mask, with the tier on versus off. Subject-level
allocation cannot help a person in flat clothing, so the face tier is aimed squarely at that.
"""

import sys

import numpy as np

from pbn import faces, images, pipeline

CORPUS = sys.argv[1] if len(sys.argv) > 1 else "../corpus"
CACHE = ".cache/models"


def face_density(conversion, face_mask):
    """Regions per megapixel within the face mask."""
    inside = face_mask > 127
    if not inside.any():
        return 0.0, 0
    ids = np.unique(conversion.labels[inside])
    mp = inside.sum() / 1e6
    return len(ids) / mp, len(ids)


print(
    f"{'image':15s} {'faces':>6s} {'face cov':>9s} {'regions off/on':>16s} "
    f"{'face regions':>14s} {'density /MP':>22s} {'gain':>6s}"
)
print("-" * 92)
for p in images.list_images(CORPUS):
    img = images.load(p)
    w = images.fit_long_edge(img, 1400)
    detected = faces.detect(w, cache_dir=CACHE)
    if detected is None or not detected.found:
        print(f"{p.stem:15s} {0:6d}  (no face detected)")
        continue

    off = pipeline.convert(
        img,
        pipeline.VARIANTS["standard"],
        subject_cache=".cache/subject",
        model_cache=CACHE,
        detect_faces=False,
    )
    on = pipeline.convert(
        img,
        pipeline.VARIANTS["standard"],
        subject_cache=".cache/subject",
        model_cache=CACHE,
        detect_faces=True,
    )
    d_off, n_off = face_density(off, detected.mask)
    d_on, n_on = face_density(on, detected.mask)
    gain = d_on / d_off if d_off > 0 else float("nan")
    print(
        f"{p.stem:15s} {detected.count:6d} {detected.coverage:8.1%} "
        f"{off.n_regions:7,d}/{on.n_regions:<7,d} {n_off:6d}/{n_on:<7d} "
        f"{d_off:10,.0f}/{d_on:<10,.0f} {gain:5.2f}x"
    )

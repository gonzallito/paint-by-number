"""Contact sheet comparing a small source at native size versus upscaled."""

import sys

import cv2

from pbn import contact, images, pipeline

name = sys.argv[1] if len(sys.argv) > 1 else "juve"
out = sys.argv[2] if len(sys.argv) > 2 else "../out-upscale-test"
path = [q for q in images.list_images("../corpus") if q.stem == name][0]
raw = images.load(path)


def upscale(img, long_edge):
    h, w = img.shape[:2]
    if max(h, w) >= long_edge:
        return img
    scale = long_edge / max(h, w)
    return cv2.resize(img, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_LANCZOS4)


rows = []
for label, src in (("native", raw), ("upscaled 1900px", upscale(raw, 1900))):
    c = pipeline.convert(
        src,
        pipeline.VARIANTS["detailed"],
        subject_cache=".cache/subject",
        model_cache=".cache/models",
        working_long_edge=max(src.shape[:2]),
    )
    rows.append(
        contact.build_row(
            original=c.working,
            subject_mask=c.subject_mask,
            labels=c.labels,
            region_colour=c.region_colour,
            palette_rgb=c.palette_rgb,
            numbering=c.numbering,
            title=f"{name}\n{label}",
            caption=c.caption(),
            from_subject=c.from_subject,
            face_mask=c.face_mask,
        )
    )
    print(
        f"{label:18s} canvas {c.working.shape[1]}x{c.working.shape[0]}  "
        f"regions {c.n_regions:,}  colours {c.n_colours}  unnum {c.unlabelled_fraction:.1%}"
    )
contact.write_sheet(rows, f"{out}/{name}.png")
print(f"wrote {out}/{name}.png")

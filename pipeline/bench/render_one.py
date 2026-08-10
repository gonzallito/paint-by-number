"""Render a single image's contact sheet under an explicit output name."""

import sys

from pbn import contact, images, pipeline

name = sys.argv[1]
dest = sys.argv[2]
search = ["../corpus", "../corpus/dev"]
path = next(q for d in search for q in images.list_images(d) if q.stem == name)
raw = images.load(path)

rows = []
for v in ("simple", "standard", "detailed"):
    c = pipeline.convert(
        raw, pipeline.VARIANTS[v], subject_cache=".cache/subject", model_cache=".cache/models"
    )
    rows.append(
        contact.build_row(
            original=c.working,
            subject_mask=c.subject_mask,
            labels=c.labels,
            region_colour=c.region_colour,
            palette_rgb=c.palette_rgb,
            numbering=c.numbering,
            title=f"{name}\n{v}",
            caption=c.caption(),
            from_subject=c.from_subject,
            face_mask=c.face_mask,
        )
    )
    print(
        f"  {v:9s} {c.n_regions:5,d} regions  {c.n_colours:3d} col  "
        f"texture {c.texture:5.0f} -> flatten {c.flatten_strength:.2f}  "
        f"initial {c.initial_regions:,}"
    )
contact.write_sheet(rows, dest)
print(f"wrote {dest}")

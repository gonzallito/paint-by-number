"""Contact sheet isolating the stylisation stage: identical settings, stylise on vs off."""

import sys

from pbn import contact, images, pipeline

name = sys.argv[1] if len(sys.argv) > 1 else "leonorGoncalo"
out = sys.argv[2] if len(sys.argv) > 2 else "../out-stylise-compare"
path = [q for q in images.list_images("../corpus") if q.stem == name][0]
raw = images.load(path)

rows = []
for label, flag in (("stylise OFF", False), ("stylise ON", True)):
    c = pipeline.convert(
        raw,
        pipeline.VARIANTS["detailed"],
        subject_cache=".cache/subject",
        model_cache=".cache/models",
        stylise_input=flag,
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
        f"{label:12s} regions {c.n_regions:,}  of {c.initial_regions:,} initial  "
        f"colours {c.n_colours}  unnum {c.unlabelled_fraction:.1%}  "
        f"{sum(c.timings.values()):.0f}s"
    )
contact.write_sheet(rows, f"{out}/{name}.png")
print(f"wrote {out}/{name}.png")

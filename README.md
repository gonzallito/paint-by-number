# paint-by-number

Mobile color-by-number app. Core feature: converting the user's **own photos** into
interactive tap-to-color canvases.

- **`ROADMAP.md`** — phasing, estimates, risk gates
- **`.kiro/steering/project.md`** — architecture decisions and rationale, artifact
  contract, toolchain gotchas

## Layout

```
pipeline/   Python conversion pipeline (Phases 0-1)
service/    FastAPI + job queue (Phase 3)
app/        Flutter app (Phases 2, 4+)
corpus/     Test photos - gitignored; manifest.csv is tracked
out/        Contact sheets - committed, reviewed on GitHub
```

## Pipeline setup

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
cd pipeline
uv sync                        # base deps
uv sync --extra segmentation   # + rembg (heavy: ~176MB model on first run)
uv run pbn doctor              # verify toolchain
```

## Status

**Phase 0 — feasibility spike.** Toolchain verified; pipeline not yet written; corpus not
yet assembled.

Phase 0 is a genuine go/no-go gate: it determines whether photo conversion produces
results good enough to build a product on. Everything expensive is sequenced behind it.

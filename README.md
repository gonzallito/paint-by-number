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

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/). Install `uv` first:

```powershell
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Close and reopen the terminal afterwards so `uv` lands on `PATH`.

```bash
cd pipeline
uv sync --extra segmentation   # includes rembg; downloads a ~176MB model on first run
uv run pbn doctor              # verify toolchain
```

`uv` installs the right Python itself, so no separate Python install is needed.

## Converting photos

**All `pbn` commands run from `pipeline/`, and paths are relative to it** — hence `../corpus`
rather than `corpus`:

```bash
cd pipeline
uv run pbn convert --input ../corpus --out ../out
```

Or from the repository root, without changing directory:

```bash
uv run --project pipeline pbn convert --input corpus --out out
```

Contact sheets land in `out/`, one PNG per image with a row per detail variant. `uv run pbn
fetch` populates `corpus/dev/` with a small reproducible development set.

## Status

**Phase 0 — feasibility spike.** Toolchain verified; pipeline not yet written; corpus not
yet assembled.

Phase 0 is a genuine go/no-go gate: it determines whether photo conversion produces
results good enough to build a product on. Everything expensive is sequenced behind it.

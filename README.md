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

## Building curated content

Player photos are converted on demand by the service. The **daily, story and library canvases are
converted here**, reviewed by a person, and published as finished artifacts — which is how the genre
works, and why the pipeline is a studio tool rather than something that ships inside the app.

```
content/
  sources/
    whispering-woods/            <- collection, nesting is free-form
      cottage-at-dusk/           <- artwork id
        source.png               <- the colour illustration
        artwork.toml             <- optional metadata
```

`artwork.toml` is optional, and everything in it has a default:

```toml
title = "Cottage at Dusk"
profile = "daily"                # default: library-medium
tags = ["cozy", "evening"]
credit = "AI generated"
```

```bash
cd pipeline
uv run pbn profiles                                          # list profiles and their gates
uv run pbn build --sources ../content/sources --out ../content
```

Output:

| path | |
|---|---|
| `content/build/<id>/` | `regions.png`, `meta.json`, `preview.webp` and a build stamp |
| `content/build/manifest.json` | static index for the CDN |
| `content/report.html` | **open this** — thumbnail grid with pass/fail and reasons |
| `content/report.json` | the same, for machines |

### Profiles

A *variant* is a detail level offered to the player for their own photo. A *profile* is a production
recipe for curated content, and each carries its own acceptance gate — because the profiles do not
agree on what "good" means. A zoomable library canvas may hold regions too small to tap at
fit-to-screen, since the player zooms in. The daily canvas cannot zoom, so the same region makes the
painting impossible to finish.

| profile | regions | colours | canvas | zoom | gate |
|---|---|---|---|---|---|
| `daily` | 55 | 10 | 1400 | **no** | 30–60 regions, **exactly 10** colours, every region ≥14px on screen, all numbers visible at 1x |
| `library-easy` | 250 | 28 | 1400 | yes | 180–320 regions, ≥18 colours |
| `library-medium` | 550 | 48 | 1900 | yes | 420–700 regions, ≥32 colours |
| `library-hard` | 1200 | 88 | 2400 | yes | 900–1600 regions, ≥60 colours |

Region counts are hit **exactly**; colour counts land close and fall short above roughly 90.
Match the canvas size to the region count — a low region count on a large canvas is *slower*,
because the second merge pass has to reduce tens of thousands of initial regions instead of
hundreds. Measured at 52.3s for 100 regions on a 1900px canvas against ~2s at 1400px.

### What the build guarantees

- **Rebuilds are skipped** when the source bytes, the profile and `CONVERSION_VERSION` all match.
  That is what makes a thousand-canvas library practical, and it is the "pin" curated content needs:
  a published artifact is not silently replaced because the pipeline changed. `--force` reconverts
  deliberately.
- **A failing gate never un-publishes.** A source that now fails keeps its previous artifact and is
  reported; withdrawing live content because someone edited a file is the worse mistake.
- **Drift is loud.** Each stamp records a hash of the canvas. If identical inputs ever produce a
  different canvas, the build says `NOT REPRODUCIBLE` rather than quietly diverging from what is
  already published.

Generating source art with AI? Prompt for **flat vector illustration, limited palette, clean
outlines, no gradients, no texture, no grain**. Grain is what makes region counts explode.

Daily art needs authoring to its own spec, and the gate is strict about it: **10 clearly separated
colours, each covering enough area to survive merging down to ~55 regions**, built from a few large
simple shapes. A colour that appears only in slivers gets pruned, and the canvas then fails on 9
colours instead of 10. Busy source art fails on region count instead. Both rejections are the gate
doing its job — daily art is generated to this spec, so regenerate rather than loosen.

## Status

**Phase 0 (conversion pipeline) — done and accepted.** Every variant lands exactly on its target
region count at 0.0% unnumbered, with subject/background density in the range reviewed and approved.

**Phase 1 (canvas) — working on real hardware.** Tap-to-fill, pinch-zoom, zoom-revealed numbers and
the palette tray, measured at raster p50 10.0ms with 1600 regions on an old Huawei.

**Phase 2 (conversion service) — working.** Upload, poll, download, paint, end to end from the app.

**Phase 3 (content pipeline) — working.** Profiles, acceptance gates, previews, manifest, review page.

Next: progress persistence, which is the largest functional gap — sessions run 30–90 minutes and are
currently lost when the app closes. See `docs/APP-SPEC.md` for the full picture and build order.

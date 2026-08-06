# Paint by Number — Project Context

Mobile color-by-number app whose **core feature is converting the user's own photos**
(pets, family, travel) into interactive tap-to-color canvases. Photo upload is the
product bet, not a premium add-on — there is no curated-library safety net for
conversion quality.

See `ROADMAP.md` for full phasing and estimates.

## Current status

**Phase 0 — Feasibility spike.** Scaffold and toolchain verified. Pipeline not yet written.
Corpus not yet assembled.

## Decisions already made (and why)

| Decision | Rationale |
|---|---|
| **Flutter** for the app | ~80% of this app is custom canvas + gestures. One Impeller/Skia pipeline behaves identically on both platforms; RN+Skia means assembling that from separately-versioned parts. |
| **Raster region-ID map**, not SVG paths | Per-pixel region index encoded in RGB gives O(1) hit testing on tap — one pixel read, no point-in-polygon. Also removes vectorization, Douglas-Peucker, and the shared-border smoothing problem entirely. |
| **No vectorization** in v1 | Rasterize segmentation at ~4096px for crisp zoom instead. Revisit only if zoom crispness proves insufficient. |
| **Pre-segmented region fill**, not runtime flood fill | Regions are known ahead of time; filling is a composite with a radial reveal from the tap point. Cannot leak across borders, far cheaper. |
| **Server-side conversion for v1** | Conversion quality needs constant tuning; on-device would gate every quality iteration behind app-store review. Move on-device (Phase 7) once the pipeline stabilizes. |
| **Pipeline in Python now, C++ later** | Python for fast iteration during exploration. Deliberate planned port to C++/OpenCV in Phase 7 so the same code serves both server and on-device via `dart:ffi`. |
| **Region *count* budget, not pixel-size threshold** | Pinch-zoom makes almost any region tappable, so tappability isn't the real constraint — tedium is. Target 300–1,500 total regions. |
| **Subject-aware segmentation** | Highest-leverage quality lever: fine regions + rich palette on the subject, aggressive flattening of background. This is what an illustrator would do and it's most of the gap between "muddy photo" and "looks designed". |
| **Variant picker (2–3 outputs)** | Converts a quality gamble into a user choice, transferring ownership of the result. Load-bearing for perceived quality — do not cut. |
| **Palette ordered by luminance** (1 = lightest) | More intuitive than frequency ordering; canvas reads as a value study while in progress. |
| **Distance transform for number placement** | `cv2.distanceTransform` + argmax on the region mask gives the most-interior point *and* the inscribed radius (which tells you if the digit fits). Simpler and more robust than polygon pole-of-inaccessibility since regions are already rasters. |

## Artifact contract (the key interface)

The pipeline emits a **versioned bundle**; the app consumes only this. It is the single
seam between pipeline and app work, so changes here are breaking changes.

- `display.png` — outlines + numbers, high resolution (~4096px long edge)
- `regions.png` — region ID map, per-pixel region index encoded in RGB
- `meta.json` — format version, palette (luminance-ordered, region→color assignment),
  per-region centroid + inscribed radius + area, total region count

`ARTIFACT_FORMAT_VERSION` lives in `pipeline/pbn/__init__.py`. Bump it on any breaking
change and keep old versions readable — users will have in-progress artworks.

## Environment

Sandbox has **no Flutter/Dart SDK**. Python pipeline and service work (Phases 0,1,3) run
here; Flutter work (Phases 2,4+) is written here but built, run, and profiled on the
user's local machine. Phase 2's exit criterion is 60fps on a low-end physical Android
device, which needs real hardware regardless.

```bash
cd pipeline
uv sync                        # base pipeline deps
uv sync --extra segmentation   # + rembg/onnxruntime (heavy, ~176MB model on first run)
uv run pbn doctor              # verify toolchain
```

Pinned to Python 3.12. Verified working: OpenCV 5.0, scikit-image 0.26, networkx 3.6,
rembg 2.0.77.

### Toolchain gotchas

- `skimage.graph.merge_hierarchical` is the region-merge scaffolding, but it stops on a
  color-similarity *threshold*. We need to stop on a *region count budget* with a cost
  blending area and ΔE — so pass custom `merge_func` / `weight_func`. Verified working.
- The RAG API lives at `skimage.graph`; older tutorials say `skimage.future.graph`.
- **Never smoke-test segmentation with random noise** — SLIC collapses it to a single
  segment and the RAG comes back with zero nodes, which looks like a library bug but
  isn't. Use `skimage.data.astronaut()` or a real photo.
- `rembg` pulls `numba`/`llvmlite` release candidates as of this writing. Watch for
  instability; pin if it bites.
- The u2net model is ~176MB — fine server-side, a problem for on-device app bundle size
  in Phase 7. `u2netp` is a much smaller variant to evaluate then.
- CPU inference measured at ~0.5s per image (plus ~2.4s one-time session init).

## Working conventions

- Work on branches, open a PR, never commit straight to `main`.
- **Phase 0 review happens on GitHub.** Its output is visual — commit contact sheets to
  `out/` and the user reviews them rendered in the PR. The user cannot browse the
  sandbox filesystem, so anything they need to *see* must be committed.
- `corpus/` images are gitignored (personal, bulky). `corpus/manifest.csv` is tracked so
  results stay discussable and reproducible.
- Reuse algorithms, write decisions. OpenCV/scikit-image/scikit-learn for anything
  standard; the merge cost function, region budgeting, variant generation, suitability
  scoring, and artifact packaging are ours.
- Check licenses before borrowing from hobby paint-by-number repos — many have no license
  (no rights granted) or GPL, which is a problem for a closed-source app. Verify
  pretrained model weight licenses separately from the loading library.

## Quality rubric

Write the rubric **before** looking at pipeline output, or you will rationalize whatever
you get. Phase 0's gate is a genuine go/no-go, judged on ~50 deliberately difficult real
photos, shown to ~10 people who are not the author.

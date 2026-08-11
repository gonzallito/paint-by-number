# Paint by Number — Project Context

Mobile color-by-number app whose **core feature is converting the user's own photos**
(pets, family, travel) into interactive tap-to-color canvases. Photo upload is the
product bet, not a premium add-on — there is no curated-library safety net for
conversion quality.

See `ROADMAP.md` for full phasing and estimates.

## Settled decisions — do not re-litigate

**Conversion quality is accepted.** The reviewer reviewed all three variants on real camera-roll
photos and accepted `detailed` as the output to ship. `RECOMMENDED_VARIANT = "detailed"` and the
artifact carries a `recommended` flag so the app can preselect it without hardcoding a name. The
other two remain offered: the picker exists so the user chooses, which also turns an imperfect
conversion from a gamble into a decision they own.

**Phase 0 is therefore complete.** Do not keep tuning conversion quality without a specific
reviewer complaint to answer — the remaining known gaps are recorded in `docs/PHASE0-FINDINGS.md`
and none of them blocked acceptance.


**Stylisation is OFF by default and stays that way.** The reviewer compared stylised against
unstylised output across the full corpus, twice, and chose unstylised both times: the stylised
result still reads soft where it matters. `pbn/stylise.py` remains available behind
`pbn convert --stylise` because the finding is worth keeping, but it is not the product.

The remaining softness is **irreducible, not a bug**, and that distinction is what makes the
decision final rather than provisional:

* The *fixable* part was real and was fixed — early stylised output took its region colours from
  the stylised image, which washed the fill out. Colours now come from the unstylised image.
* The *irreducible* part is that region **boundaries** derive from the stylised image, so textured
  areas get larger regions. A larger region averages more of the original photo into one flat
  colour. Less detail in those areas is the definition of what was asked for, not a defect.

So "smoother regions to paint" and "sharp finished artwork" are genuinely in conflict *in textured
areas specifically*, and the reviewer's priority is the finished artwork. Any future attempt has to
beat that trade, not rediscover it.

**Softened outlines are in the default path.** Feathered boundary alpha rather than hard 1px lines,
applied to every render. This was the reviewer's explicit request and carries no fidelity cost, so it
delivers most of the page-comfort benefit that stylisation was chasing, for free.

## Three-tier region allocation

Regions get one of three floors on effective radius, finest to coarsest: **face, subject,
background**. Each tier exists because the tier above it was measured to be insufficient.

* **Background coarser than subject** — cost discounting alone left backgrounds blotchy, because
  a discount changes merge *order*, not where merging stops.
* **Explicit per-side budget split** — size-based prioritisation only controlled count
  indirectly. Since no region merges across the silhouette, the two sides are independent
  sub-problems and each can simply be given a budget. Headroom transfers **one way only**:
  unused background allowance may go to the subject, never the reverse.
* **Face finer than subject** — subject-level allocation cannot rescue a person in flat
  clothing, because the clothing has no colour structure to subdivide.
* **Blurred backgrounds are detected and simplified further** — measured by *absolute*
  background texture, not the subject/background ratio (see gotchas).

## Current status

**Phase 0 — Feasibility spike, complete on the development set.** Pipeline runs end to end at
~1.9s per conversion. Verdict: proceed, with the "colourable page reads as a contour map"
problem as the main carried risk. Full assessment in `docs/PHASE0-FINDINGS.md`.

**The real corpus is still outstanding, and it is what actually gates Phase 1.** The dev set
(`pbn fetch`) is 7 images — 4 small scikit-image samples, 3 arbitrary stock photos — all well
lit. It cannot answer whether dim indoor pet photos, group shots or backlit subjects produce
usable subject masks, and subject detection already failed outright on 2 of the 7.

```bash
cd pipeline
uv run pbn convert --input ../corpus/dev --out ../out   # regenerate contact sheets
```

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
| **Constrain effective radius (`2·area/perimeter`), never area** | Measured: an area floor left 65% of regions unable to hold a digit, and 100% of those failures had *adequate area* with inscribed radius 2.2-3.0px. Colour-gradient boundaries produce slivers. Switching to effective radius took unnumbered from 65% → 1.1%. |
| **Bilateral filtering for flattening, not mean-shift** | Measured, against expectation: mean-shift gave 0.64x region reduction at 2.33s; bilateral 0.50x at 0.03s. |
| **Segment at 1400px, always** | Measured: raising working resolution does *not* increase region count (131 → 124 median from 1400 → 2800px) because thresholds and content scale together, while cost rises. The high-res artifact must come from upscaling the label map. |
| **Own merge implementation, not `skimage.graph`** | Needed count-based stopping (the library only thresholds on colour similarity), and `skimage.graph.RAG` builds adjacency via `ndi.generic_filter` with a per-pixel Python callback, which dominates runtime at 1.5MP. Adjacency here is array shifts + an int64 pair-key bincount. |

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

### Sandbox quirks

- **`fs_write` outside `/projects/sandbox` silently fails.** The file is redirected into a
  session snapshot directory and does not appear at the requested path. Keep scratch files in
  the workspace.
- **`/tmp` does not persist between `execute_bash` calls.** Hence the gitignored
  `pipeline/scratch/` (benchmarks) and `pipeline/.cache/` (subject masks).

### Pipeline traps that cost real time

- **Two constraints require two merge passes.** A single loop conditioned on "count > budget
  *or* anything undersized" pops the globally cheapest edge, which usually does not touch an
  undersized region — so silhouette-isolated specks keep the condition true and the whole
  image merges away. Photos collapsed to 1-24 regions. Undersized absorption must be its own
  pass, restricted to edges touching an undersized region.
- **Splitting initial connected components by the subject mask is mandatory.** Refusing to
  *merge* across the silhouette is not enough: a white cat on a white couch quantises to one
  colour and connects, so plain CC already returns one straddling region.
- **Keep resolution-scaled units consistent across stages.** The merge floor scaled with
  resolution while digit height was fixed in pixels, so a 451px canvas guaranteed 2.1px of
  interior room while numbering demanded 6.4px → 67% unnumbered with both stages working
  correctly in isolation.
- **Cost discounts change merge order, not where merging stops.** Discounting background merges
  left backgrounds blotchy; only a genuinely coarser background radius floor
  (`BACKGROUND_MIN_RADIUS_MULTIPLIER`) produced large flat shapes. It must be gated on a
  subject actually being detected, or subject-less images treat every region as background and
  over-merge.
- **The palette's subject flags must be permuted with the palette.** Luminance ordering
  interleaves subject and background entries, so a count of subject colours is not enough —
  track the boolean array.
- **Contact sheets are composited with PIL, not matplotlib.** The gridspec version produced
  unpredictable vertical gaps and floated palette strips under the wrong columns.
- **Never smoke-test on random noise** (see below) and never judge the colourable page from a
  scaled-down panel — the sheet includes a 1:1 crop for exactly that reason.

- **Region count is ultimately bounded by label packing, not region geometry.** A small face
  area has no room for hundreds of numbers however well shaped the regions are. Pushing the
  floor lower eventually reintroduces unnumbered regions for this reason alone.
- **Leader connectors must be dashed.** A solid 1px grey line is nearly indistinguishable from a
  region outline, and confusing the two is the worst possible failure: the user tries to fill it.
- **Erode both sides before measuring background blur.** The silhouette is a very strong edge, so
  measuring up to it makes even heavy bokeh look sharp. Changes the measured ratio by up to 3.3x.
- **Use absolute background texture, not the subject/background ratio.** The ratio under-reads
  the commonest portrait case, because a flat-clothed subject shrinks the numerator.
- **Cap background regions absolutely, not as a share of budget.** A share scales the wrong way —
  a more detailed variant would hand the *background* more regions too.
- **Face boxes must be drawn as ellipses.** A rectangle's corners fall outside the head and grant
  fine-detail treatment to whatever is behind it.
- **Two attempts to fix region shape both failed** and should not be re-litigated: boundary
  smoothing (`pbn/smooth.py`, +2% radius) and a shape-aware merge cost (`CONTACT_EXPONENT`,
  −0.2% unnumbered). The unnumberable regions are thin in the *source photograph*. Leader lines
  are the answer. The contact term is kept only because it yields +18% regions for free.

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

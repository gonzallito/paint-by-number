# Cozy RPG Paint-by-Number — Full Specification

Written for someone joining with no prior context, or building this from zero.

Everything here is marked **DECIDED** (settled, backed by a measurement or an explicit product
call) or **PROPOSED** (a recommendation open to change). Numbers in this document are measured, not
estimated, unless stated. Where a measurement exists, the device it came from is named — a figure
without a device is meaningless.

Companion documents:

- `.kiro/steering/project.md` — settled engineering decisions, in short form
- `docs/PHASE0-FINDINGS.md` — the conversion pipeline's measurement history
- `pipeline/README.md`, `service/README.md`, `app/README.md` — per-component detail

---

## 1. What this is

A mobile colour-by-number game where painting drives a cozy fantasy RPG, and where the player can
turn their own photographs into paintable canvases.

The genre reference is Happy Color. The two departures from it:

1. **Painting is progression, not a content menu.** Completing canvases restores villages, advances
   chapters, and unlocks companions. The player is somewhere, not browsing a grid.
2. **Personal photos are a core feature, not a premium hook.** DECIDED. A player converts a photo of
   their dog and paints it. This is the feature most likely to make someone stay, and it is the
   hardest part of the build.

### How it should feel

**Calm first, game second.** The reason people open a colouring app is to decompress. Every RPG
element must survive the question "does this make painting feel more like a chore?" Streaks,
quests, and currencies are all capable of turning a restful activity into an obligation.

Concretely, DECIDED:

- **Painting is never rushed.** No timers, no energy meters, no penalty for stopping mid-canvas.
- **A wrong tap does nothing.** No damage, no undo prompt, no sound of failure. Filling a region
  with the wrong colour would be unrecoverable without undo, and mis-taps are the second most
  common interaction after correct ones.
- **The canvas is never crowded by UI.** The daily canvas is deliberately laid out so no paintable
  area sits behind the HUD or navigation bar.
- **Results must look sharp.** Softness in the finished artwork was repeatedly rejected during
  pipeline development. A blurry or mushy result reads as a broken conversion, even when the
  region structure is good.

PROPOSED art direction, consistent with the above: warm and low-contrast, hand-illustrated rather
than photographic, muted daylight palettes, generous whitespace, gentle motion. Named regions of
the world (Whispering Woods, Cosybrook Valley) suggest a storybook rather than a fantasy epic.

---

## 2. The two canvas types

This is the most important structural distinction in the app, and it is easy to miss. **They are
not the same canvas with different settings — they have different acceptance criteria.**

| | Daily canvas | Library / Story / Photo canvas |
|---|---|---|
| Zoom | **None** — fixed, fit-to-screen | Pinch and pan, up to 8x |
| Regions | 60–120 | 900–1600 |
| Colours | 10–12 | 78–95 |
| Session | 3–5 minutes | 30–90 minutes |
| Numbers | **All visible at 1x** | Revealed progressively by zoom |
| Every region tappable at 1x | **Required** | Not required — zoom solves it |
| Memory | ~26 MB | ~65–78 MB |
| Rendering | Raster is pixel-perfect | Raster now; vectors are the long-term answer |

DECIDED. The daily canvas cannot zoom, which removes the mechanism that makes small regions
workable elsewhere. That single constraint changes the pipeline configuration completely, and it is
why the daily format needs its own variant rather than a tweak to an existing one.

### The daily canvas has an unsolved blocker

Measured on illustration-style corpus art at the radius floor that otherwise works
(`FIXED_RADIUS_FLOOR` raised to 1.4, giving 31–59 regions and 95–100% of numbers visible at 1x):

**Some regions resist merging at every floor tested.** One test image retained a region with a
3.3-pixel on-screen radius at floors 0.8, 1.4, 2.0 *and* 2.6. These regions are isolated by the
subject silhouette, so every available merge is forbidden by `preserve_silhouette`.

On a zoomable canvas this is invisible — the player zooms in. **On the daily canvas it is a
painting that cannot be completed**, which breaks the streak that the whole daily loop depends on.

Required before the daily tab can ship: a final forced merge pass that folds any region still under
the floor into its largest neighbour, ignoring the silhouette rule. This does not exist yet.

Also DECIDED: the radius floor should be *derived*, not chosen. For a non-zoomable canvas shown at
a known size, the required region radius is `finger_px / display_scale`. A formula, not a constant.

---

## 3. Core painting interaction

DECIDED and validated on device. The player confirmed: *"its perfect its really working... exactly
as i imagine the feature to work."*

1. **Palette tray** along the bottom: horizontally scrolling numbered swatches, each showing how
   many regions remain in that colour, dimming when the colour is finished.
2. **Select a colour**, and every unfilled region of that colour is marked with a grey-and-white
   checkerboard so it is easy to find. Explicitly requested by the player.
3. **Tap a marked region** and it fills. Tap anything else and nothing happens.
4. **Numbers keep a constant on-screen size** while the artwork scales, because they are painted
   *outside* the zoom transform. This is what makes small regions numberable at all.
5. **Numbers appear as you zoom.** Each region carries a `reveal_zoom`; its number appears once zoom
   passes it. Requested by the player after observing it in other apps, and it is what let the
   pipeline drop leader lines entirely (0.0% of regions need them).

PROPOSED, not yet built: a radial fill animation, haptic tick on fill, a chime and sparkle when a
colour completes, auto-advance to the next unfinished colour, and a gentle shake on a wrong tap.

---

## 4. The five tabs

Navigation is a fixed bottom bar with a persistent global header showing avatar, XP, coins, gems
and settings.

**Critical structural rule — DECIDED:** tabs hold *browsers*, never canvases. A canvas is a route
you **push**. Three tabs each holding a zoomable canvas would consume 233 MB and crash on older
Android. With canvases as pushed routes, the realistic peak is the daily canvas plus one open
painting, about 91 MB.

### 1. Home — the daily hub

- The daily painting is the screen. The player paints directly here.
- Non-zoomable, laid out so nothing paintable sits under the header or nav bar.
- Completing it advances the streak and pays the daily reward.
- **Kept alive in memory permanently.** At ~26 MB this is affordable, and disposing it would put a
  ~900 ms reload in front of every return to Home.
- Quest cards, coins and gems live in the header and a drawer, not over the paintable area.

### 2. Story — the world map

- Node-based map with branching paths and themed arcs.
- Finishing key paintings unlocks lore, companions and cosmetics.
- The map is a browser; tapping a node pushes a canvas route.

### 3. Library

- **Photo converter** — pick from gallery or camera, convert, paint. The core feature.
- **Curated catalogue** — hundreds to thousands of canvases, searchable and filterable.
- **Personal collection** — in progress and completed.

### 4. Social — PROPOSED FOR REMOVAL FROM v1

Friend feeds, showcase galleries, QR invites, and co-op foundations. Recommended cut from the first
release: it carries the highest backend cost and the only real moderation and safety surface (user
photos plus social feeds), while being the least likely of the five to drive early retention.

One genuine finding if co-op is built later: **the canvas cannot diverge.** A region has exactly
one correct colour and a wrong tap does nothing, so painting is a grow-only set — a CRDT. Any
order, any duplicates, any replay converges to the identical canvas. No operational transform, no
vector clocks. Ordering is only needed for *credit* — who earned the XP, who filled it first, and
undo. This makes co-op far cheaper than multiplayer usually is.

### 5. Profile

Avatar customisation, titles, frames, trophies, level and XP, longest streak, completion stats.

---

## 5. Quests and progression

DECIDED, and a correction to an earlier design. Quests must be **aggregate counters**, not
colour-specific:

- Good: "finish one painting", "paint 100 regions", "complete a colour"
- Bad: "colour 5 green regions"

Three reasons, all structural:

1. **Canvas-agnostic.** A colour-specific quest silently breaks when today's art has no green.
2. **Recomputable.** An aggregate counter can be rebuilt from saved progress after a crash. "5
   green regions" cannot, unless the palette is stored alongside it.
3. **Off the tap path.** Quests are evaluated on a debounce from the fill summary, never per tap.
   A per-tap evaluation through the state layer previously cost **119 ms per tap**; that cost was
   removed and must not be reintroduced.

---

## 6. The conversion pipeline

Turns a photograph or illustration into a paintable canvas. This is the deepest part of the
project and the most thoroughly measured. Full history in `docs/PHASE0-FINDINGS.md`.

### Output: the artifact bundle

| file | size | contents |
|---|---|---|
| `regions.png` | 372 KB | region index per pixel, encoded as `r + g*256 + b*65536` |
| `meta.json` | 385 KB | palette, per-region centroid / radius / `reveal_zoom`, `regions_by_colour` |

`display.png` is **not** written. The app derives outlines from the region map at load, which took
the bundle from 4.1 MB to 760 KB — a 5.5x saving. DECIDED.

### The three variants

| variant | colours | grain | canvas | typical regions |
|---|---|---|---|---|
| simple | 48 | 1.6 | 1400 | 215–319 |
| standard | 72 | 1.0 | 1900 | 635–846 |
| **detailed** (recommended) | 96 | 0.72 | 2400 | 859–1600 |

The player chose `detailed` as the shipping default and asked to keep `simple` available so users
can decide. All three are produced per upload; **the recommended one is converted first** so the app
can open after roughly a third of the wait.

### Quality bar, currently met

- Every variant lands **exactly** on its target region count
- **0.0% unnumbered** regions across the corpus
- **0.0%** of regions need leader lines
- Subject/background region density **1.7–2.0x**, matching the 1.3–2.3x the player approved

### The density rule — the mistake most likely to be repeated

Region budget is allocated **by subject area** with a modest density boost:

```
share = boost * coverage / (boost * coverage + (1 - coverage))    boost = 2.0
```

**Do not replace this with a fixed share to "emphasise the subject."** That has now been rejected
twice: once as a face-detail tier, and once when a fixed 72% share went live and put **12.6x** the
region density on a subject covering 17% of the frame. The player's report was immediate: "too much
focused on one object leaving one piece detailed and the rest really simple."

Uniform-ish detail is a standing product requirement, not a default.

### Determinism is a dependency

`cv2.kmeans` uses OpenCV's global RNG and was never seeded, so the same photo produced a different
artwork each run — measured at 1000 regions/81 colours on one run and 1021/80 on the next for a
byte-identical input. It is now seeded. This matters for three reasons: content builds must be
reproducible, approved art must stay approved, and no quality claim is falsifiable without it.

### Format decisions worth knowing

- **HEIF/HEIC must be decodable.** It is the default capture format on iPhones and recent Android.
  OpenCV cannot read it at all; decoding falls back to PIL with `pillow-heif`. A real upload failed
  on this.
- **EXIF orientation must be applied.** `cv2.IMREAD_UNCHANGED` ignores it, so portrait phone photos
  were converting sideways — and the subject detector was being handed a rotated world.
- **Upload at full resolution.** The pipeline measures texture on the *original* source, so
  downscaling client-side silently changes a measurement validated across the whole corpus.

---

## 7. Content strategy

The largest cost in this project is **art volume**, not code. A daily canvas plus story arcs plus a
catalogue of hundreds to thousands is a content treadmill, and it has no engineering solution.

### How this genre actually works — DECIDED

Curated canvases are **converted offline and published as finished artifacts.** Not shipped as
source images for on-device conversion. The reasons:

- **Deterministic** — every player gets a byte-identical canvas, so a QA pass means something
- **Reviewable** — a bad conversion is rejected before anyone sees it
- **No per-device cost or variance** — an old phone does not get a worse canvas
- **Smaller download** — packed canvas data beats a high-resolution source image
- **Fixable** — a region can be hand-corrected without an app update

**Therefore the Python pipeline is the studio tool and must be kept.** It never ships inside the
app. Deleting it in favour of on-device-only conversion would mean hand-authoring every canvas.

The split:

| content | converted | why |
|---|---|---|
| Player photos (UGC) | on device, eventually | privacy, offline, zero compute cost |
| Daily, story, catalogue | studio pipeline, published as artifacts | determinism, QA, reviewability |

### Generating art with AI — PROPOSED

1. **Prompt for what the pipeline handles well**: flat vector illustration, limited palette, clean
   outlines, *no gradients, no texture, no film grain*. AI output defaults to subtle noise, which is
   exactly what makes region counts explode. Generate large; the pipeline downscales.
2. **Batch convert** through the CLI.
3. **Automated gate** on metrics the pipeline already reports — reject if `unlabelled_fraction > 0`,
   `merges_blocked` is true, region or colour count is out of band, or any region is untappable at
   the intended display size.
4. **Human review** of survivors. Publish approved artifacts to R2 with a manifest.
5. **Pin curated artifacts.** Unlike player photos, curated content must *not* auto-reconvert when
   `CONVERSION_VERSION` changes — that would silently alter art already approved and shipped.
   Re-convert deliberately, re-review, re-publish.

Licensing note: whether AI-generated art may be used commercially depends on the specific
generator's terms, which differ. Check the terms of whichever tool is chosen.

---

## 8. Architecture

### Client

| Layer | Choice | Notes |
|---|---|---|
| Framework | **Flutter** | ~80% of this app is a custom canvas; one rendering pipeline beats two |
| Renderer | Impeller **when available** | Flutter disabled it on the test Huawei's GPU; Skia fallback measured fine |
| State | **Riverpod** — meta only | Must **not** touch the canvas hot path; see below |
| Navigation | **go_router** `StatefulShellRoute` | Tabs hold browsers; canvases are pushed routes |
| Local DB | **Drift (SQLite)** | Quests, economy, metadata, sync queue |
| On-device vision | **Deferred.** Prototype in Dart first | See section 10 |

**The Riverpod boundary is not a style preference.** A fill must not trigger a widget rebuild. The
canvas keeps a revision counter that `shouldRepaint` compares, and fills upload small per-region
patches rather than re-uploading the full canvas. Routing per-tap state through the state layer is
what previously cost 119 ms per tap.

### Canvas engine — DECIDED

**A raster region-ID map, not vector polygons, for hit-testing.** `regions.png` encodes each pixel's
region index in its RGB value, so identifying a tapped region is one array lookup at any region
count. No polygon maths anywhere in the app.

**On vectors:** for maximum crispness at deep zoom, vectors are genuinely better, and they also
reduce memory. They are the right long-term choice for the zoomable canvases and unnecessary for
the non-zoomable daily one. Two conditions before adopting them:

1. **Trace a shared edge graph.** Simplifying each region's outline independently makes two
   neighbours simplify their shared border differently, producing visible seams and gaps and making
   taps near edges disagree with the ID map. Each shared edge must be traced once, simplified once,
   and given to both neighbours.
2. **Measure on real hardware first.** "2000 polygons at 120 FPS" is an assertion. Raster measures
   p50 10.0 ms on the test device; vectors must beat that on the same device.

This is not an architectural fork. Vectorisation is a post-process on the region map, so nothing
built so far is wasted and delaying costs nothing.

### Backend

| Layer | Choice | Notes |
|---|---|---|
| Conversion service | **FastAPI (Python)** | Built and tested. Studio tool plus UGC fallback |
| Asset hosting | **Cloudflare R2** | Zero egress fees; front with Cloudflare CDN |
| Daily manifest | **Static JSON on the CDN** | Not an API. Zero compute, infinitely cacheable |
| Purchases | **RevenueCat** | Cross-platform receipt validation is real pain to hand-roll |
| Go microservices | **Not for now** | A second backend language for CRUD and auth, when a working service exists |
| gRPC | **No** | Codegen and debugging cost for a handful of endpoints |

The conversion service is a job queue, because conversion cannot happen inside a request: upload
returns 202 with a job, the client polls. Two things learned the hard way:

- **The worker pool is in-process, so it dies with the server.** Any job left `queued` or `running`
  at startup has no worker and never will; they are failed on boot. Reusing one made every
  re-upload of that photo poll a job that could never progress.
- **Deduplication is keyed on photo digest *and* `CONVERSION_VERSION`.** Digest alone pins every
  already-converted photo to whatever the algorithm did at the time.

---

## 9. Performance and memory

### Measured on the test device — Huawei, old, Skia renderer, 1600 regions

| | |
|---|---|
| raster | **p50 10.0 ms**, p95 48.9 ms |
| build | p50 9.7 ms, p95 61.1 ms |
| load | 922 ms |
| fill (per tap) | **6 ms** |
| highlight (per colour selection) | **199 ms** — the one bad number |
| frames over 16 ms | 65% |

For contrast, the same canvas on a Pixel 6 **emulator** measured raster p50 91.5 ms. An emulator
runs on the host CPU and GPU and cannot answer this question in either direction. Never gate on
emulator numbers.

`highlight` at 199 ms is a visible hitch on colour selection and scales badly — it was 36 ms at 417
regions. It is meant to cost per-region, not per-canvas, so the scaling indicates a defect. This is
the most likely thing to make the app feel worse as region counts grow.

### Memory per canvas, computed from the real bundle (1800x2400)

| buffer | |
|---|---|
| region ID map (Uint16) | 8.6 MB |
| fill buffer (RGBA) | 17.3 MB |
| outline layer (RGBA) | 17.3 MB |
| GPU textures | 34.6 MB |
| **total, one zoomable canvas** | **77.8 MB** |
| daily canvas, non-zoomable | 26 MB |

Two cheap wins available now:

- **Outline as A8 instead of RGBA: saves 13 MB.** It only carries alpha.
- **Partial disposal on background: frees ~69 MB.** Keep the region map and fill state, drop the
  fill buffer, outline layer and GPU textures. Resuming skips the JSON parse, the PNG decode and
  the derive pass — the three expensive parts of the 922 ms load.

### Bundle size

`meta.json` is 385 KB and **gzips to 34 KB, an 11.3x reduction.** The service does not currently
compress responses; enabling it is one middleware line.

Beyond that, the `regions` table is **56% of the file and 3,799 of its 4,070 Map/List allocations.**
Packing just that table as typed arrays makes it ~13 KB and allocates nothing on parse. That
captures nearly all the benefit of a full binary format without designing and versioning one.

---

## 10. On-device conversion

The destination is right — privacy, offline capability, and no server compute for UGC. Both the
route and the timing in the original plan were wrong.

### The "under 700 ms" claim is off by 20–30x

Every operation below is already OpenCV C++ behind thin Python glue, so these effectively **are**
the C++ timings:

| stage, 3.8 MP canvas, 8-core desktop | |
|---|---|
| bilateralFilter | 83 ms |
| RGB to LAB | 113 ms |
| **k-means, k=24** | **4,731 ms** |
| findContours | 12 ms |
| approxPolyDP x1600 | 5 ms |
| **naive floor** | **4,943 ms** |
| at k=96 (shipping quality) | 18,303 ms |

A mid-range phone core is 3–4x slower, so the on-device floor is **15–20 seconds** — and that
excludes subject detection, region targeting, radius-floor merging and numbering. 700 ms is
reachable only for a pipeline whose output has already been rejected.

### The bottleneck is algorithmic, not linguistic

Clustering 3.8 M pixels to find 96 average colours is wasteful:

| k-means fit | time | palette shift |
|---|---|---|
| all 3,840,000 px | 12,270 ms | — |
| **150,000 px sample** | **643 ms (19x)** | mean dE **1.7** |
| 50,000 px sample | 218 ms (56x) | mean dE 1.8 |

The pipeline already treats dE < 3.0 as the same colour, so a 1.7 shift is below its own
perceptual-identity threshold. That is ~11.6 s off a ~20 s conversion, in Python, with no rewrite.

### Language choice — PROPOSED

Where the time goes after subsampling is the argument:

| stage | cost | needs SIMD? |
|---|---|---|
| bilateral + LAB | 196 ms | yes — and already fast |
| k-means on subsample | 218 ms | no |
| **merge loop** | **7,800 ms** | no — pure scalar |

**The parts where C++ wins are already cheap; the expensive part is scalar work.** The Python
speedup came from removing NumPy and reducing to plain scalar arithmetic on flat lists — which is
exactly what Dart AOT compiles well, in a background isolate, with no FFI boundary and no NDK or
Xcode build.

So: prototype the merge loop in Dart. If it lands under a second, Dart-only is viable and the dual
native toolchain is avoided entirely. C++ remains the ceiling for battery and worst-case latency,
and Dart does have `Float32x4`/`Int32x4` SIMD, though narrower and harder to use than OpenCV's
tuned kernels.

### Subject detection on device — PROPOSED

Shipping the 176 MB `u2net` model is not viable. Both platforms expose native segmentation — iOS
Vision and Android ML Kit — at no app-size cost. Caveats:

- **ML Kit's models come through Google Play Services**, which Huawei devices lack. The current test
  device cannot use this path.
- iOS foreground-instance masking is iOS 17+.
- Masks differ between platforms, so the same photo yields different canvases on iOS and Android.
  Fine for private artwork; it matters the moment a canvas is showcased or painted co-op. Resolved
  by syncing the **artifact**, never the source photo.

The safety net is easy because of a decision already made: now that density is uniform, the subject
mask only drives silhouette preservation. Conversion can degrade gracefully to no subject
detection where the API is unavailable.

---

## 11. Data and offline behaviour

### Progress persistence — the largest functional gap

Not implemented. Closing the app loses a session, and sessions are 30–90 minutes.

DECIDED design:

- **One row per canvas** in Drift, painted state in a single column.
- **A byte array, not JSON or one row per region.** One byte per region is ~1,266 bytes for a
  typical canvas. Per-region rows are far too heavy; JSON is larger and slower to parse.
- **Store state, not a log.** A region-to-colour array is idempotent and self-healing. An event log
  needs replay and can desync.
- **Write on a ~2 second debounce *and* on lifecycle change** — backgrounded, route popped. A
  debounce alone loses the tail, which is exactly when sessions end.
- Queries like "how many blue regions remain" are answered from memory using the shipped
  `regions_by_colour` index, not from SQL.

### Storage location

Artworks and progress live in the **documents** directory, never a cache directory. The OS evicts
caches under storage pressure, and losing a half-finished 90-minute painting that way would be
indefensible.

### Offline

| Feature | Offline | On reconnect |
|---|---|---|
| Daily canvas | Paint the last downloaded one | Fetch manifest, download the new canvas, sync |
| Photo converter | Fully functional once conversion is on-device | Sync completion to cloud backup |
| Story and catalogue | Paint anything downloaded | Fetch new packs from R2 on demand |

Downloads land in a `.partial` directory and are renamed on success. An interrupted download would
otherwise leave a truncated `regions.png` that appears in the library and throws every time it is
opened — permanently.

---

## 12. Monetisation — PROPOSED

Via RevenueCat: premium story chapters, cosmetic packs, hint consumables, and a subscription
removing whatever friction exists for free players.

Two recommendations:

- **One currency for v1.** Two currencies before the loop is known to retain is economy design
  without data.
- **No banner ads.** The pitch is explicitly the absence of them, and they would undercut the calm
  the app is selling.

---

## 13. Deliberately excluded

| Excluded | Why |
|---|---|
| Vector rendering (for now) | Raster measures p50 10.0 ms on real hardware; adopt later with a shared edge graph |
| Vector hit-testing | The raster ID map is O(1) and exact |
| SVG artwork | Nothing in the app does polygon maths |
| Leader lines for numbers | Zoom reveal took them to 0.0%; they solve a *print* problem |
| A face-detail tier | Worked, but produced uneven region size, which was rejected |
| Stylisation before conversion | Made results mushy; the player chose unstylised twice |
| Go backend, gRPC | A working Python service exists; the manifest should be a static file |
| Shipping Python in the app | Size, battery, and toolchain cost. It is a studio tool |
| Social tab in v1 | Highest backend and moderation cost, lowest early retention value |

Six separate attempts to improve page appearance were measured and rejected: boundary smoothing
(+2%), shape-aware merge cost (−0.2%), background simplification, texture-adaptive flattening,
morphological stylisation, and texture-gated stylisation. **Do not re-litigate these without new
evidence.**

---

## 14. Build order

Sequenced so expensive rewrites wait until the game is known to be fun.

1. **k-means subsampling** — 19x on the dominant cost, no rewrite, validated against dE 3.0
2. **gzip, then pack the `regions` table** — 11.3x network free, then 17x off the largest allocation
3. **A8 outline, partial disposal, Home kept alive** — 13 MB, then ~69 MB, then the UX fix
4. **Progress persistence** — debounced plus lifecycle write. The largest functional gap
5. **Forced final merge** — removes untappable regions. Gates the daily canvas
6. **Vertical slice: Home tab, daily canvas, streak** — playtest before building five tabs
7. **Content pipeline** — AI generation, automated gate, R2 publishing
8. **On-device UGC** — prototype the merge loop in Dart, then decide on C++
9. **Fix `highlight` at 199 ms** — before region counts grow further
10. **Vectors, if deep-zoom crispness justifies it** — shared edge graph, measured on device

Deferred: Story map, Profile, monetisation, co-op. Cut from v1: Social.

---

## 15. Reference constants

Pipeline (`pipeline/pbn/`):

| Constant | Value | Meaning |
|---|---|---|
| `MAX_WORKING_LONG_EDGE` | 2400 | Largest working canvas |
| `MIN_WORKING_LONG_EDGE` | 1800 | Small sources are upscaled, Lanczos |
| `TARGET_REGION_AREA_PX` | 3200 | Comfortable region area |
| `TARGET_REGIONS_MIN` / `MAX` | 100 / 1600 | Region count bounds |
| `COLOURS_PER_REGION_CEILING` | 0.40 | Palette ceiling relative to region count |
| `FIXED_RADIUS_FLOOR` | 0.10 | Minimum region radius; **needs ~1.4 for the daily canvas** |
| `SUBJECT_DENSITY_BOOST` | 2.0 | Subject density relative to background. **Do not raise** |
| `MAX_SUBJECT_SHARE` | 0.82 | Clamp only |
| `DEDUPE_DELTA_E` | 3.0 | Below this, two colours are the same |
| `MAX_PRACTICAL_ZOOM` | 8.0 | Informs number reveal |
| `ARTIFACT_FORMAT_VERSION` | 2 | Bundle *shape* |
| `CONVERSION_VERSION` | 2 | Bundle *content*. Bump when output changes |

Colour saturates around 80: an isolated test raising 93 to 139 colours produced **0%** change in
error, and two images got worse. Variants differ by **canvas size**, not palette or grain.

---

## 16. Open questions

1. **Does the RPG meta-game actually retain?** The entire premise, and nothing measures it yet.
   Analytics is absent from every plan so far.
2. **Where does the art come from, and at what rate?** The daily canvas alone is 365 pieces a year.
3. **What is the daily canvas's region count band?** Measured 31–59 at floor 1.4 on test art, and
   3–5 minutes suggests 60–120. The art must be authored to land in band — which is controllable,
   since it is generated.
4. **Is Dart fast enough for on-device conversion?** Answerable with one prototype of the merge loop.
5. **Why does `highlight` scale with canvas rather than region count?** It is 36 ms at 417 regions
   and 199 ms at 1600.
6. **Formal performance gate.** `over 16 ms` read 65% on the test device, but with startup frames
   included. Needs a clean read: reset, then one sustained pinch-zoom.

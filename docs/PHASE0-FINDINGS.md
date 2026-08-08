# Phase 0 Findings

Feasibility spike for photo → colourable canvas conversion. Reproduce with:

```bash
cd pipeline
uv sync --extra segmentation
uv run pbn fetch --dest ../corpus/dev
uv run pbn convert --input ../corpus/dev --out ../out
```

Contact sheets in [`out/`](../out) — one PNG per image, three variants each.

## About the rubric

The roadmap says to write the quality rubric *before* looking at output, so that judgement
cannot be rationalised after the fact. That is not what happened here: the pipeline was built
and inspected iteratively, and the criteria below were written afterwards. They should be
treated as a description of what was assessed, not as a pre-registered standard.

**The rubric below is the one to apply to the real corpus, before looking at it.**

| Criterion | Pass condition |
|---|---|
| Recognisability | The filled result is unmistakably the same subject as the photo |
| Appeal | A stranger would call the finished artwork attractive, not "a bit odd" |
| Page legibility | Region boundaries read as deliberate shapes, not contour-map noise |
| Numberability | Under 3% of regions lack a legible number |
| Silhouette | The subject's outline survives as a region boundary |
| Session length | Region count implies a satisfying but finishable sitting |
| Robustness | No crashes, no degenerate output, across every input category |

## Verdict

**Proceed, with one significant reservation.** The pipeline is technically sound and the
*finished artwork* is good. The *colourable page* is not yet as appealing as curated
illustration, and that gap is the main risk to carry into Phase 1.

By category, on the development set:

| Category | Recognisable | Appealing | Verdict |
|---|---|---|---|
| Pet (cat, 61% frame) | yes | yes at `standard`/`detailed` | **good** |
| Portrait (54% frame) | yes | yes at `standard` | **good** |
| Object (47% frame) | yes | acceptable | **acceptable** |
| Vehicle, no subject | yes | acceptable | **acceptable** |
| Near-featureless photo | n/a | too few regions (17-37) | **weak** — trivially short artwork |
| High-texture, no subject | partly | no — reads as camouflage blotches | **poor** |

The pattern is clear and matches the original concern: **photos with a clear subject convert
well; busy photos without one do not.** Subject presence, not photo quality, is the strongest
predictor of a good result.

## Measured results

21 conversions (7 images x 3 variants) in 40.2s, ~1.9s each at 1400px.

| Variant | Colours | Regions | Unnumbered |
|---|---|---|---|
| `simple` | 12 | 17-135 | 0-0.9% |
| `standard` | 18 | 31-359 | 0-4.5% |
| `detailed` | 24 | 37-646 | 0-15.6% |

Across all conversions: regions min 17, median 112, max 646. Unnumbered mean 2.5%.

## What works

- **Subject segmentation is the single biggest quality lever, as predicted.** Directing
  palette and region budget at the subject measurably reallocates fidelity: subject
  reconstruction error falls and background error rises in 4 of 5 subject images. The largest
  gain (−27%) was on the image where the subject covered just 3% of the frame.
- **Subject region share reaches 88-92%** on subject images, against 47-61% area share.
- **The silhouette survives**, verified programmatically: zero regions straddle the mask.
- **Numbering is effectively solved** at 2.5% mean unnumbered, and every number lands inside
  its own region.
- **Performance is a non-issue.** ~1.9s per conversion; the worst image merges 26,000 regions
  in about 2s.
- **Variants give a genuine progression**, which matters because the variant picker is
  load-bearing for perceived quality.

## What does not work

- **The colourable page reads as a contour map.** Because boundaries follow colour gradients,
  fur and texture become nested wavy lines. It is legible and correct but lacks the
  deliberate, designed quality of illustration-derived pages. **This is the main risk.**
- **Thin features are destroyed.** The cat's whiskers vanish completely — they cannot survive
  a minimum-radius floor. For pets specifically this removes something characteristic.
- **`simple` (12 colours) loses likeness on faces.** Fine as a deliberate "quick" option; not
  viable as a default.
- **High-texture photos without a subject convert poorly** and no amount of tuning fixed it.
- **Featureless photos yield too few regions** (17-37), i.e. a 5-minute artwork.

## Technical findings worth keeping

Several of these contradicted expectations, which is the point of a spike.

**Area is the wrong constraint; effective radius is the right one.** With a minimum-*area*
floor, 65% of regions could not hold a digit — and *100%* of those failures had adequate area
with a median inscribed radius of 2.2-3.0px. Colour-gradient boundaries produce slivers: lots
of area, no interior room. Constraining `2·area/perimeter` instead took unnumbered regions
from 65% to 1.1%. Perimeter is maintained incrementally through merging, so it is free.

**Bilateral filtering beats mean-shift for flattening.** Mean-shift was the expected winner —
it clusters in joint colour+space, which is the posterisation we want — and it lost on both
axes: 0.64x region reduction at 2.33s versus 0.50x at 0.03s. Measured, not assumed.

**Working resolution is not a lever for region count.** 1400px → 131 median regions, 2800px →
124, while cost rose 3.1s → 4.3s. Thresholds and image content scale together. Segment at
1400px; the high-resolution artifact should come from upscaling the label map.

**Region count is content-determined, not tuning-determined.** A 2.3x larger palette buys only
~1.55x the regions. Dropping the radius floor from 0.60 to 0.40 triples region count but
leaves 18-24% of regions unnumberable. The roadmap's 300-1,500 target is optimistic for
typical photos.

**Two constraints need two passes.** Merging while "count > budget *or* anything undersized"
looks equivalent to enforcing both and is catastrophically wrong: it pops the globally
cheapest edge, which usually does not involve an undersized region, so a few
silhouette-isolated specks keep the condition true and the loop merges the entire image.
Photos collapsed to 1-24 regions. Undersized absorption must be its own pass, restricted to
edges that touch an undersized region.

**Cost discounts change merge order, not stopping point.** Discounting background merges left
backgrounds visibly blotchy. Giving the background a genuinely coarser radius floor (2.6x) is
what produced the few large flat shapes an illustrator would use.

**Units must scale consistently.** The merge floor scaled with resolution while digit height
was fixed at 7px, so on a 451px canvas the merge guaranteed 2.1px of interior room while
numbering demanded 6.4px — 67% unnumbered despite the merge working perfectly.

## Recommendations for Phase 1

1. **Score photo suitability and steer users away from bad inputs.** Subject presence plus
   texture predicts outcome well enough to do this before processing. Refusing a photo politely
   beats returning camouflage blotches. Laplacian variance already correlates with region
   density at Spearman 0.893.
2. **Attack the contour-map problem.** Most promising: boundary simplification and smoothing as
   a post-merge pass, so shapes read as drawn rather than traced. This is the highest-value
   remaining quality work.
3. **Add leader lines for small regions.** It is what commercial paint-by-number kits do, and it
   is the only way to raise region count without unnumbered regions.
4. **Recalibrate the texture→flatten-strength table** on the real corpus. It is currently fitted
   to 7 development images, 3 of them arbitrary stock photos.
5. **Decide the thin-feature question.** Whiskers, eyelashes and jewellery are all casualties.
   A "preserve thin dark features as unfillable ink lines" layer would fix it and is how
   illustration handles the same problem.
6. **Solve label-map upscaling** for the ~4096px artifact, since segmentation stays at 1400px.
   Nearest-neighbour will look blocky.

## What the real corpus still has to decide

The development set is 7 images: 4 small scikit-image samples (300-640px) and 3 arbitrary
stock photos. It was enough to build and instrument the pipeline. It cannot answer the
questions that matter:

- Do **dim indoor pet photos** — the single most likely real upload — produce a usable subject
  mask? Every subject here was well lit and well separated.
- Do **group photos** work at all? Multi-subject handling is implemented but only exercised on
  one two-blob image.
- Does **subject detection survive** motion blur, backlighting, and cluttered rooms? Detection
  already failed outright on 2 of 7 development images.
- Is the **contour-map quality** acceptable to real users, or a dealbreaker?

Two of the four are about subject-mask robustness, which makes sense: subject segmentation is
where most of the quality comes from, so it is also where most of the risk sits.


---

# Addendum: results on the real corpus

9 real photos (0.4-17.9 MP): four portraits, two 17.9MP travel shots, one illustration, one
badge graphic, one meme photo. This section supersedes the tuning numbers above; the
development-set constants were recalibrated against these images via `bench/recalibrate.py`.

## The good news

**Subject detection worked on all 9 images** (27-62% coverage, a single clean blob each),
versus 2 outright failures in 7 development images. Robustness is better than expected.

**Performance held**: 27 conversions in 45.9s, ~1.7s each, including two 17.9MP inputs.

**Filled results on portraits are genuinely good.** The clearest test case is recognisable at
`standard` and `detailed` — skin tones, clothing and props all read correctly.

## The bad news, and it is structural

**Cost-based merging allocates region budget to colour *variation*, but perceptual importance
is not colour variation.** This is the deepest finding of Phase 0 and it is not fixable with a
constant.

The failing case is a portrait: a man in a **flat black tuxedo** against an **out-of-focus
bokeh backdrop**. The subject carries all the importance and almost no colour boundaries; the
backdrop carries no importance and strong colour boundaries. Left to compete on merge cost, the
budget flows exactly backwards — the subject received 21% of regions for 36% of the frame,
while the blurred backdrop absorbed the rest as long horizontal wavy bands that are actively
unpleasant to colour.

Three mechanisms were tried against this:

| Attempt | Result |
|---|---|
| Discount background merge cost (`BACKGROUND_COST_SCALE`) | Insufficient — a discount changes merge *order*, not where merging stops |
| Coarser background radius floor (`×2.6`, then `×1.8`) | Controls region *size* but only indirectly controls count; at ×2.6 canvases collapsed to 16-259 regions |
| **Explicit per-side budget split** (adopted) | Works as designed, and exposed the real limit below |

The budget split is the right mechanism — since no region ever merges across the silhouette,
the two sides are independent sub-problems, so each can simply be given a budget. It revealed
that the actual constraint is different from what was assumed:

> For the failing portrait at `standard`, the output is **51 subject regions + 225 background
> regions**. The background cap works correctly. The subject only has 51 numberable regions
> *available*, because a flat black tuxedo has no colour structure to subdivide.

**You cannot create numberable regions in a subject that has none.** Finer floors would produce
more regions, but they would be unnumberable slivers. This is a wall, not a tuning problem.

## Recalibrated constants

| Constant | Was | Now | Why |
|---|---|---|---|
| `BACKGROUND_MIN_RADIUS_MULTIPLIER` | 2.6 | 2.0 | 2.6 collapsed real canvases to 16-259 regions |
| `DEFAULT_SUBJECT_BUDGET_SHARE` | — | 0.80 | New mechanism; replaces size-based prioritisation |
| `simple` radius floor | 0.85 | 0.60 | Dev-set floors were far too aggressive on real photos |
| `standard` radius floor | 0.60 | 0.46 | |
| `detailed` radius floor | 0.50 | 0.38 | |

Headroom transfer between sides is deliberately **one-directional**: an unused background
allowance may go to the subject, never the reverse. Allowing the reverse let a flat subject
donate its unused share to the backdrop, restoring the exact problem the cap exists to prevent.

## Results after recalibration

27 conversions, median 155 regions, mean 6.2% unnumbered.

| Variant | Regions | Unnumbered |
|---|---|---|
| `simple` | 50-165 | 0-1.8% |
| `standard` | 102-299 | 0.4-10.5% |
| `detailed` | 155-390 | 4.0-21.8% |

`simple` is comfortably shippable. `standard` is usable. **`detailed` is not shippable as-is** —
up to 21.8% of its regions cannot carry a number, so it depends on leader-line rendering, which
does not exist yet.

## Correction to an earlier claim

The main findings above treated the static colourable-page render as the quality bar. That was
wrong. Numbers are 7-13px on a 1400px canvas, so they vanish when the page is scaled to fit a
contact sheet — but in the app numbers render at **constant screen size**, so they are legible
at any zoom. The static page render systematically understates numbering quality; the 1:1 crop
panel is the honest view.

The unnumbered *fraction* is nevertheless real and scale-free: it measures region shape relative
to the canvas, so rendering the artifact at 4096px does not improve it.

## Revised Phase 1 priorities

Reordered by what the real corpus showed:

1. **Face-aware region allocation.** The single highest-value fix. Subject-level allocation
   cannot help a flat-clothed person, but the *face* is where detail is both present and
   meaningful. Portraits are a core use case and currently the weakest category.
2. **Boundary simplification.** Still the fix for both the contour-map appearance and the
   sliver problem — rounder regions raise the achievable region count at a given
   numberability. This is what unblocks `detailed`.
3. **Leader lines**, without which `detailed` cannot ship.
4. **Background structure detection.** Blurred/bokeh backgrounds should collapse to a handful
   of shapes; a detailed cityscape should not. A blur measure restricted to the background
   would distinguish them.
5. Recalibrate the texture→flatten table (still fitted to development images).
6. Label-map upscaling for the high-resolution artifact.


---

# Addendum 2: palette size, and two failed attempts at region shape

## Palette size was calibrated a full tier too low

Commercial custom photo-to-paint-by-number services sell **24 / 36 / 48** colour tiers and steer
portraits toward 36-48; 6-12 colours is the children's range. Our variants shipped 12 / 18 / 24 —
so the most detailed option we offered matched the industry's *entry* tier, and `simple` was a
kids' kit. Sources: [tier guidance](https://paintwithnumber.com/pages/what-is-the-difference-between-24-36-and-48-colors),
[custom photo kits](https://justpaintbynumber.com/products/custom-paint-by-numbers-kit-from-any-photo/).
*(Content rephrased for licensing compliance.)*

Measured on the real corpus, subject reconstruction error against palette size:

| requested k | kept | subject ΔE | vs k=18 | regions | unnumbered |
|---|---|---|---|---|---|
| 18 | 16 | 5.03 | — | 227 | 12.0% |
| 24 | 20 | 4.70 | −6% | 271 | 13.7% |
| 32 | 28 | 4.01 | −20% | 310 | 14.1% |
| 40 | 34 | 3.86 | −23% | 321 | 15.7% |
| **48** | **40** | **3.68** | **−27%** | **339** | 18.6% |
| 56 | 45 | 3.68 | −27% | 365 | 17.6% |

Fidelity improves 27% and then plateaus at 48 — the same ceiling the industry arrived at
independently. Variants are now 24 / 36 / 48.

**An earlier sweep judged palette size by region count and concluded it barely helped. That was
the wrong metric.** Palette size buys colour *fidelity*, which is precisely what "it doesn't look
like the photo" means. Region count was never the complaint.

`DEDUPE_DELTA_E` was also silently capping large palettes: at 6.0, asking for 48 returned 33-48
depending on the image, so the user would not have received the tier they chose. Lowered to 3.0,
which keeps 43-48 of 48 and stays above the just-noticeable difference for side-by-side swatches.

## Two attempts at rounder regions, both measured, both largely failed

Regions that cannot hold a number are slivers, so making regions rounder ought to fix numbering
*and* the contour-map appearance. Two mechanisms were built and measured.

**1. Boundary smoothing** (`pbn/smooth.py`) — iterative 8-neighbourhood majority relaxation on
boundary pixels, i.e. discrete curvature flow. Result: median effective radius **+2%**,
unnumbered **−0.6%**. Negligible.

The reason is worth keeping: the regions are not *rough*, they are **elongated**. They snake
across tens of pixels. Smoothing the edges of a snake yields a smooth snake. Local relaxation
cannot change global shape.

**2. Shape-aware merge cost** (`CONTACT_EXPONENT`) — divide merge cost by the shared border as a
fraction of the smaller perimeter, so well-joined pairs fuse into blobs and barely-touching pairs
are discouraged from forming chains. Result: **+18% more regions** at the same radius floor
(314 → 369) and median radius +3%, but unnumbered moved only **−0.2%**.

The contact term is kept because more regions at equal comfort is free value. But the conclusion
about numbering is now well supported by two independent negative results:

> **The unnumberable regions are thin in the source photograph** — edges, outlines, gaps between
> objects — not artefacts of merging. No amount of shape engineering removes them, which is
> exactly why commercial paint-by-number kits use leader lines.

Leader lines are therefore not a nice-to-have workaround; they are the correct solution, and the
only thing standing between `detailed` and being shippable.

## What the 48-colour output shows

Filled results are markedly closer to the source: facial modelling, fabric shading and metallic
highlights all survive where 24 colours flattened them. The reviewer's preference for the most
detailed variant is supported by the fidelity numbers.

It also relocates the quality problem. With the subject now well served, **the background is the
dominant visual offender**: an out-of-focus backdrop of crowd and stage lighting becomes long
parallel diagonal bands spanning the page. Those bands are *faithful* to the photo and *terrible*
to colour. Faithfulness and appeal diverge, and here appeal should win.

This makes background structure detection the top remaining quality item: a blurred background
carries no information worth colouring and should collapse to a handful of flat shapes, whereas a
sharp cityscape behind a subject should not. Blur is directly measurable — the existing Laplacian
variance measure, restricted to the background mask, distinguishes the two cases.

## Current state

27 conversions, ~3.0s each. Median 295 regions (was 155).

| Variant | Colours | Regions | Unnumbered | Status |
|---|---|---|---|---|
| `simple` | 22-24 | 85-245 | 0-1.9% | shippable |
| `standard` | 33-36 | 164-454 | 4.2-16.1% | usable |
| `detailed` | 42-48 | 247-724 | 12.1-31.1% | blocked on leader lines |


---

# Addendum 3: leader lines, background simplification, face tier

Three agreed quality items, all implemented and measured on the real corpus. All three variants
retained (24 / 36 / 48) so the user chooses rather than being chosen for.

## 1. Leader lines — the `detailed` variant is unblocked

Regions with no interior room now have their number drawn outside and joined by a dashed
connector, as commercial kits do.

**Unnumbered went from 12.1-31.1% to 0.0% on every image.**

Implementation notes worth keeping:

* Placement is two passes. Interior placement runs first, **largest area first**, reserving
  space in an occupancy mask; leaders then search outward over 16 directions at increasing
  distance for a free slot. Ordering matters because pass 1 constrains pass 2.
* Leaders always use the *minimum* digit height. They are a fallback, and a compact label is
  far more likely to find space.
* Each successive region offsets its angular search by the golden angle, so clusters of
  leaders fan out instead of all pointing the same way.
* Where no slot exists at all, the region is left unlabelled rather than overlapping another
  number — an absent number is better than an ambiguous one.
* **Connectors are dashed, not solid.** A solid 1px grey line is nearly indistinguishable from
  a region outline, which is the one thing it must not be confused with: the user would try to
  fill it.

### Leaders make the radius floor much cheaper

This is the compounding benefit. Before leaders, lowering the floor produced regions that could
not be numbered, so the floor had to stay high. Now the cost of a lower floor is leader clutter
rather than missing numbers:

| radius floor | median regions | on leaders | unnumbered |
|---|---|---|---|
| 0.38 | 458 | 19% | 0.0% |
| **0.30** | **603** | 33% | 0.0% |
| 0.24 | 820 | 47% | 0.3% |
| 0.18 | 1,112 | 61% | 2.5% |

Floors lowered accordingly: `standard` 0.46 → 0.40, `detailed` 0.38 → 0.30.

## 2. Blurred backgrounds are detected and simplified

`background_simplification()` returns 0..1. Two lessons from building it:

**Erosion is mandatory.** The silhouette is one of the strongest edges in the image, so
measuring texture right up to it registers a huge Laplacian response on both sides and makes a
heavily blurred background look sharp — inverting the signal. On one image, eroding changes the
measured ratio by 3.3x.

**A ratio alone is the wrong signal.** Subject-to-background texture ratio under-reads the most
common portrait case: a man in flat clothing against a defocused backdrop scores only 2.4,
because the flat subject shrinks the numerator even though the background is plainly bokeh.
**Absolute** background texture reads it correctly, so that is the primary signal, with the
ratio kept as a booster.

Measured on the corpus — bokeh backdrops land at 6-20, moderately busy at 104-144, genuinely
detailed scenes at 805-1191. Sharp backgrounds correctly score 0.00 and are left untouched.

A defocused background loses both detail (flatten boost) and region budget (share plus an
absolute cap). The cap has to be **absolute**, not a share: 7% of a 1200 budget is still 84
regions, far more than a backdrop deserves, and it scales the wrong way — a more detailed
variant would give the *background* more regions too.

### Calibrating the cap was a genuine trade, and the first attempt overshot

At a cap of 22 the background became 2-3 enormous shapes, total regions fell by over half, and
the result departed sharply from the photo — the wrong trade given that fidelity was the stated
priority and noise the secondary complaint. Isolating the two levers showed the **flatten boost
was doing most of the useful work** (subject share 21% → 59% with no cap at all), and the cap
only traded further. Settled at 45.

## 3. Face tier: three levels instead of two

Faces get a *finer* radius floor than the rest of the subject, via OpenCV's YuNet (~230KB, versus
176MB for the subject segmenter). Haar cascades were the obvious alternative but
`opencv-python-headless` ships no cascade XML files at all.

This addresses the wall found earlier: subject-level allocation cannot rescue a person in flat
clothing, because the clothing has no colour structure to subdivide, whereas the face is both
detailed and where the likeness lives.

**Face region density rose 1.44-2.67x.** On the motivating portrait, face regions went from 87 to
194 and total regions from 203 to 313. Faces detected on 7 of 9 images; correctly absent on the
landscape.

Boxes are expanded 1.35x and drawn as an **ellipse**, not a rectangle — a rectangle's corners fall
outside the head and would grant fine-detail treatment to whatever sits behind it.

### Label packing is a hard ceiling on region count

The face tier initially reintroduced unnumbered regions (up to 8.7%), and the cause is worth
recording: in a small face area there is simply not room for hundreds of numbers, however well
shaped the regions are. **Region count is ultimately bounded by label packing, independently of
region geometry.** Resolved by a coarser face floor (0.70) plus a longer leader reach (16x),
giving 0.0% mean / 0.1% worst.

## Current state

27 conversions, ~3.0s each. Median 356 regions (85 min, 1,100 max), unnumbered 0.0% mean /
0.1% max.

| Variant | Colours | Regions | On leaders |
|---|---|---|---|
| `simple` | 22-24 | 85-247 | 0-8% |
| `standard` | 33-36 | 198-544 | 10-33% |
| `detailed` | 42-48 | 336-1,100 | 25-61% |

## Open question for review

**`detailed` puts up to 61% of numbers on leaders.** Every region is numbered and the dashed
connectors are distinguishable from outlines, but a majority of numbers sitting outside their
region is a legibility question that measurement cannot settle — it needs a human judgement on
whether the page still feels pleasant to work through. The 1:1 crop panel is the view to judge
it from, since that is roughly what the app shows at working zoom.

If it reads as too busy, the lever is the `detailed` radius floor: 0.38 gives 19% leaders instead
of 61%, at roughly 30% fewer regions.


---

# Addendum 4: uniform regions, deep palettes, zoom reveal

Reviewer feedback reframed the product: **fidelity should come from colour depth, paintability
from uniform region size.** Those are separate axes, and the pipeline had been buying fidelity
with region count — which is why faces ended up with cells too small to paint.

## What changed

**Face tier removed.** It worked exactly as designed (face region density rose 1.44-2.67x) and
produced the wrong artwork. Region size decides whether a canvas is pleasant to paint, so mixing
tiny face cells with large background shapes is unpleasant however faithful it is. Faces are still
detected, but only to annotate contact sheets.

**Palettes raised to 48 / 96 / 150**, with the floor held at one comfortable density instead of
being tightened per variant. Variants now differ mainly in colour depth.

**Zoom-based label reveal.** Numbers render at constant screen size, so a region's screen area
grows with zoom while its digit does not — every region becomes numberable at sufficient zoom. Each
region carries a `reveal_zoom`, and only regions that can hold a legible number are labelled at
fit-to-screen. Measured: **53-80% of numbers visible at fit-to-screen, 93-100% at 2x**.

This **eliminated leader lines entirely — 0.0% on every image.** Leaders solve a *print* problem,
where there is no zoom to defer to. Building them first was solving the right problem in the wrong
medium; they remain as a fallback beyond `MAX_PRACTICAL_ZOOM` but never trigger in practice.

**Artifact bundle written** (`pbn/artifact.py`, format version 2): `display.png`, `regions.png`
(region ids encoded in 24-bit RGB, verified to round-trip exactly) and `meta.json` carrying the
palette, per-region geometry including `reveal_zoom`, and a `regions_by_colour` index so selecting
a colour can highlight its regions without scanning the ID map. With a 100+ colour palette each
colour owns few regions, which makes that highlight essential rather than decorative.

## Bug found: dead palette entries

The palette is built *before* merging, and merging re-snaps each surviving region to its nearest
entry — so entries can end up orphaned. Measured: **82 palette entries of which only 59 were
reachable**, i.e. 23 numbers in the tray with nothing to paint. Fixed by pruning unused entries and
renumbering before placement (renumbering must precede placement, since digit count affects fit).

## The binding constraint: palette size is capped by region count

Correlation between region count and usable palette size: **0.849**, at roughly one usable colour
per 2-4 regions.

| detailed (150 requested) | regions | usable colours |
|---|---|---|
| praga | 137 | 73 |
| deniro | 151 | 75 |
| juve | 455 | 119 |
| rubinho | 387 | 129 |

**A 100-200 colour palette therefore requires roughly 300-600 regions.** Requesting 150 colours on
a 150-region canvas returns about 75, because there is nowhere to put the rest.

### Canvas size is the lever, and source resolution bounds it

The radius floor was scaled by canvas long edge, which held region count constant at any resolution
— the cause of the earlier, wrong conclusion that "resolution is not a lever". An **absolute** floor
was implemented and measured:

| | 1400px canvas | 2800px canvas |
|---|---|---|
| CIES (17.9MP source) | 281 regions / 115 colours | **844 / 132** |
| praga (17.9MP source) | 146 / 79 | **463 / 105** |
| deniro (0.8MP source) | 112 / 60 | 122 / 69 |
| anime (0.5MP source) | 102 / 50 | 100 / 49 |

It behaves exactly as the reasoning predicts and was still **reverted**: it lifts high-resolution
sources dramatically while *reducing* region count for ordinary web-sized images, which lose the
proportionally finer floor they were getting. Most real uploads are 0.4-2.6MP, so relative wins on
the mix.

The conclusion is a product one rather than a tuning one: **region count is ultimately bounded by
detail present in the source photo.** Reaching 100-200 colours consistently needs high-resolution
uploads and a canvas the user pans and zooms around, which is what large-artwork colour-by-number
apps actually are.

## Background simplification softened

Isolating it showed aggressive background collapse was costing one portrait **40% of its regions**
(250 -> 148) and 11 usable colours. Tidiness was being bought with exactly the fidelity and colour
depth the product sells. Now a mild coarsening: flatten boost 1.5 -> 0.5, background radius
multiplier 2.0 -> 1.4, subject budget share 0.80 -> 0.72, background region cap 45 -> 120.

## Current state

27 conversions, ~5.9s each. Median 255 regions (123 min, 465 max), unnumbered 0.0%, leaders 0.0%.

| Variant | Requested | Usable colours | Regions | Visible at fit-to-screen |
|---|---|---|---|---|
| `simple` | 48 | 37-48 | 123-268 | ~80% |
| `standard` | 96 | 61-88 | 207-423 | ~57% |
| `detailed` | 150 | 67-135 | 204-465 | ~53% |

## Open decision

Reaching a consistent 100-200 colour palette requires 300-600 regions, and that requires
high-resolution source photos. Of the current corpus only the two 17.9MP images can supply it; the
web-sized ones top out around 70-90 colours whatever is requested. The choice is whether to target
large, high-resolution artworks (long sessions, deep palettes, heavy panning) or accept that
ordinary phone-sized uploads produce 200-400 region canvases with 70-130 colours.


---

# Addendum 5: adaptive sizing, and colour saturates far earlier than expected

## Input classes were misjudged

A phone gallery upload is **not** a small image. Recent phones shoot 12-48MP, which is at or above
the 17.9MP DSLR files in the corpus. The real distinction is:

* **Camera-roll uploads (12-48MP)** — the common case for a phone app, firmly high-resolution.
* **Saved images, screenshots, memes (0.4-3MP)** — also real, a different class entirely.

The dev corpus is 7 web-class images to 2 camera-roll, so **every calibration to this point was
tuned against the wrong input distribution.**

## Adaptive sizing

Canvas size now follows the source (never upscaling), and region count is derived from canvas
*area* at a fixed comfortable grain (~3,200px per region), rather than from a hand-picked floor. The
floor is found per image by bisection on the target count. One configuration therefore serves both
input classes: regions come out the same comfortable size, and only their number differs.

Palette requests are clamped to what the regions can host (~0.4 colours per region), since asking
for more just returns fewer after pruning.

## The measurement that overturned the premise

Isolating colour from region count — comparing variants where region count is near-constant but
palette rises substantially:

| image | colours | regions | filled-result error |
|---|---|---|---|
| CIES | 93 → 139 | 858 → 980 | **0%** |
| king | 89 → 128 | 499 → 554 | −2.5% |
| praga | 80 → 114 | 986 → 1088 | −1% |
| anime | 45 → 42 | 144 → 146 | **+2% (worse)** |
| juve | 37 → 38 | 128 → 122 | **+4% (worse)** |

Against that, doubling *region count* moved error by **−7% to −19%**.

**Colour saturates at roughly 80 entries. Region count is the dominant lever.** The reviewer's
earlier preference for the most detailed variant was real but misattributed: at the time that
variant had both more colours *and* more regions, and the two were never separated. Acting on the
colour hypothesis without isolating it was a mistake.

Every region is flooded with one flat colour, so error has two sources — palette quantisation and
within-region variation. Past ~80 colours the second dominates completely, and no palette can fix
it.

Variants were restructured accordingly: identical grain, palettes capped at 96, and detail
expressed as **canvas size** (more comfortable-sized regions, therefore a longer artwork).

## Consequences worth knowing

**Variants converge for low-resolution sources.** A 0.4MP image cannot reach the larger canvas caps,
so all three renditions come out nearly identical — honest, since such an image genuinely supports
one rendition, but it means the variant picker is only meaningful for camera-roll uploads. The app
should probably offer fewer options for small inputs rather than three identical ones.

**The palette tray does not scale linearly.** At 89 and 128 entries the contact-sheet strip became an
illegible smear; it now wraps at 48 per row. The same limit applies to the app: a linear tray cannot
present 100+ colours and will need to scroll, page or grid.

**Cost is now 15.6s per conversion** in Python at up to 2400px, driven by the bisection running
segmentation four times. Acceptable for offline batches and for an async server job, but it is a
strong argument for the planned C++ port before conversion ever sits in front of a waiting user.

## The structural limit, stated plainly

Commercial colour-by-number apps look excellent because they use **illustrations** — artwork with
flat colour areas by design, which a region-fill model reproduces exactly. Photographs are
continuous gradients, and a region fill can only ever *posterise* them. More regions narrow the gap
and more colours barely touch it.

So the achievable product is a **stylised poster interpretation** of the user's photo, not a replica
of it. That can be genuinely attractive, and the two 17.9MP images at 800-1,000 regions are the best
evidence so far, but it is a different promise from what an illustration-based app delivers and the
product should be honest about which it is making.

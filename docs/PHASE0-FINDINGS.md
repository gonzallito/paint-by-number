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

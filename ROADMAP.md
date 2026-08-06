# Color-by-Number from Photos — Project Roadmap

## Assumptions

These estimates assume **one experienced full-stack developer working full-time**, already comfortable with Python and image processing basics, learning Flutter along the way.

Estimates are in **weeks of focused work**, not calendar weeks. Adjust:

| Situation | Multiplier |
|---|---|
| Learning Flutter from scratch | +25% on Phases 2 and 4 |
| Part-time (~15h/week) | ~2.75x calendar time |
| Second developer (clean pipeline/app split) | ~0.65x, not 0.5x |
| No prior image-processing experience | +2 weeks on Phase 0 |

**Total to public launch: 22–32 weeks (~6 months full-time solo).**

---

## Phase 0 — Feasibility Spike

**1–2 weeks. Python only. No app code.**

This is a genuine go/no-go gate. The entire product rests on whether converted photos are *delightful*, and that is knowable in two weeks for the price of a throwaway script.

- Assemble a corpus of 50 deliberately difficult real photos: dim indoor pet shots, backlit selfies, group photos, busy landscapes, low-res screenshots, motion blur.
- Baseline pipeline: bilateral filter → k-means in CIELAB → connected-component labeling → region adjacency graph merge → render numbered canvas.
- Add a subject-segmentation branch (`rembg` / U²-Net) that treats subject and background differently: fine regions and rich palette on the subject, aggressive flattening on the background.
- Output contact sheets: original, numbered canvas, and filled result side by side.

**Write the quality rubric before you look at any output.** Define what "good" means in advance or you will rationalize whatever you get. Then show the sheets to ~10 people who are not you.

**Exit criteria:** a clear verdict on quality, tuned parameter ranges, and a map of which photo categories work and which don't.

---

## Phase 1 — Pipeline Hardening

**3–4 weeks. Still Python. Still no app.**

Turn a promising spike into something that behaves predictably on arbitrary input.

- **Region budget targeting** — iterative RAG merge until total region count lands in range (aim 300–1,500), rather than thresholding on individual region size.
- **Number placement** — largest inscribed circle (pole of inaccessibility) per region, so digits sit legibly inside irregular shapes.
- **Variant generation** — produce 2–3 detail/palette levels per photo for the user to choose between.
- **Suitability scoring** — score input photos before processing so you can steer users away from ones that will convert badly.
- **Artifact contract** — define exactly what the app receives. This interface matters more than anything else in this phase:
  - display bitmap (outlines + numbers, high resolution)
  - region ID map (per-pixel region index encoded in RGB)
  - palette metadata (colors ordered by luminance, region→color assignment, region centroids)
  - version field, so old artifacts stay readable as the pipeline evolves
- **Regression harness** — run the full corpus, diff against golden outputs, catch quality regressions automatically. You will be tuning this pipeline for the life of the product; this harness is what makes that safe.

**Exit criteria:** photo in, stable versioned artifact bundle out, reliably, across the whole corpus.

---

## Phase 2 — Flutter Canvas Prototype

**3–4 weeks. Throwaway-quality code, real performance answers.**

Prove the hard rendering problem in isolation before building a product around it.

- Load an artifact bundle from local assets.
- Hit testing via region ID map lookup — one pixel read per tap, O(1).
- Pan and pinch-zoom with correct coordinate transforms between screen, canvas, and region-map space.
- Region fill with radial reveal animation from the tap point.
- Number rendering at constant *screen* size regardless of zoom, with progressive disclosure as small regions become legible.

**The real gate here is performance on a cheap Android phone**, not on your dev machine or an iPhone. Test on something in the $150 range and hold 60fps.

**Exit criteria:** one hardcoded artwork, colorable smoothly, on low-end Android. If this fails, you find out now and can fall back to tiling or level-of-detail before it's expensive.

---

## Phase 3 — Conversion Service

**2 weeks.**

- FastAPI wrapping the Phase 1 pipeline, plus a job queue (RQ or Celery) and object storage for artifacts.
- Upload endpoint, status polling, artifact download.
- Lightweight device-token auth — defer real accounts.
- Cost and latency instrumentation per conversion. You need to know your unit economics early.
- Retention and deletion policy *implemented*, not just written down. People are uploading photos of their families.

**Exit criteria:** POST a photo, receive an artifact bundle.

---

## Phase 4 — Core App

**6–8 weeks. The bulk of conventional product work.**

- **First-run flow:** photo picker → suitability check → conversion progress → variant picker → canvas. This flow *is* your onboarding, and it decides retention.
- Camera and gallery integration, permissions handling.
- **Canvas screen productionized:** numbered palette tray, color-complete detection and celebration, auto-advance to next color, find-next-region hint, wrong-tap feedback, optional haptics.
- Progress persistence and offline-first local storage (Drift or Isar). Sessions run 30–90 minutes across multiple sittings; resume must be flawless.
- Gallery of in-progress and finished artworks.
- Settings, plus a high-contrast numbering mode for color vision deficiency.
- Small curated library (10–20 pieces) for onboarding and empty states.

**Exit criteria:** complete, usable app. No monetization yet.

---

## Phase 5 — Growth and Monetization

**3–4 weeks.**

- **Timelapse capture and video export.** This is the primary organic growth loop for every successful app in this category — not a nice-to-have.
- Paywall: free monthly conversion quota, subscription for unlimited. RevenueCat handles the store plumbing.
- Analytics and funnel instrumentation, focused on the first-run conversion flow.
- Light-touch re-engagement notifications.
- Ads: I'd defer entirely. They degrade a calm experience and the subscription story is cleaner.

---

## Phase 6 — Beta, Polish, Launch

**4–6 weeks.**

- TestFlight and Play internal testing with 50–200 users.
- Crash and performance monitoring (Crashlytics or Sentry).
- **Pipeline quality iteration on real user photos.** This is where your biggest quality wins live — real uploads will break assumptions your 50-photo corpus never touched. Budget most of this phase here.
- Store listings, screenshots, privacy policy.
- App Privacy and Data Safety declarations. Photo upload plus server processing makes these consequential and slow to get right — start them early in this phase, not at the end.

---

## Phase 7 — On-Device Pipeline (Post-Launch)

**4–6 weeks. Deferrable indefinitely if server costs stay acceptable.**

- Port the settled Python pipeline to C++ with OpenCV (~1–2 weeks against a well-specified algorithm with golden outputs to test against).
- Bind into Flutter via `dart:ffi`.
- Unlocks offline conversion, eliminates marginal cost per conversion, and lets you market genuine privacy — "never leaves your device" is a strong line you currently can't use.

Treat the Python→C++ port as a deliberate, planned rewrite, not a failure of the original.

---

## Critical Path and Risk

**Two hard gates.** Phase 0 (is the output good?) and Phase 2 (does it run at 60fps on cheap Android?). Both are early and both are cheap to fail. That's by design — everything expensive comes after them.

**Pipeline quality is never "done."** It's a continuous investment for the life of the product. Budget ongoing time for it after launch rather than treating Phase 1 as completion.

**Clean parallelization split.** Pipeline work (Python → C++ → service) and app work (Flutter) share only the artifact contract from Phase 1. If you add a second developer, that's the seam to split on — define the contract carefully in Phase 1 and the two tracks barely need to talk.

**Biggest schedule risk** is Phase 4 sprawl. The canvas is the product; the surrounding app is where scope quietly doubles.

---

## Leaner v1

If 6 months is too long, these cuts get you to roughly 16–20 weeks:

| Cut | Saves |
|---|---|
| Curated library down to 5 pieces | ~1 week |
| Ads (defer entirely) | ~1 week |
| Timelapse export | ~1.5 weeks — but this is your growth loop, cut reluctantly |
| Gallery reduced to a simple list | ~1 week |
| iOS only for launch | ~2 weeks of platform-specific polish |
| Variant picker down to a single result | ~1 week — I would *not* cut this; it's load-bearing for perceived quality |

Already cut by design: SVG vectorization (raster region maps instead), and on-device conversion (Phase 7).

---

## Recurring Costs

- Server compute for conversions — the main variable cost, and the reason Phase 7 exists. Instrument it from Phase 3.
- Object storage for artifacts, bounded by your retention policy.
- Apple Developer ($99/yr) and Google Play (one-time $25).
- RevenueCat — free below a revenue threshold.
- Curated art licensing — minimal at 5–20 pieces, grows if the library becomes a real feature.

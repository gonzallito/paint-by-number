# Flutter app

Phase 2: canvas prototype. Its single purpose is to answer one question —
**does the colouring canvas hold 60fps on a low-end physical Android device?** — because that is the
largest unvalidated risk in the project and no amount of pipeline work discharges it.

## Creating the project

Run from the repository root, targeting this existing directory:

```bash
flutter create \
  --project-name paint_by_number \
  --org com.gonzallito \
  --platforms android,ios \
  app
```

`--project-name` is required because the directory is `app`; without it the Dart package would be
named `app`. `--org` fixes the Android `applicationId` and iOS bundle identifier, which are
effectively permanent once the app is published — change it now if you own a domain.

## Test artwork

`assets/artwork/martim/` holds a real artifact bundle produced by the pipeline, so the prototype
needs no server:

| file | purpose |
|---|---|
| `regions.png` | region-ID map — each pixel's 24-bit RGB **is** the region index |
| `meta.json` | palette, per-region centroid, inscribed radius, `reveal_zoom`, `regions_by_colour` |
| `display.png` | pre-rendered outlines and numbers, for reference |

Declare them in `pubspec.yaml` after `flutter create`:

```yaml
flutter:
  assets:
    - assets/artwork/martim/
```

## Why the region-ID map matters

Tapping is one pixel read: decode `id = r + g*256 + b*65536` at the tapped point and you have the
region. No point-in-polygon test, no spatial index, no geometry. This is the reason the pipeline
never needed vectorisation, and it is what should make hit-testing free at any region count.

The prototype should confirm that in practice, on real hardware, at ~1,300 regions.

## What to measure

Not "does it feel smooth" — capture numbers, on a low-end device, in **profile** mode (never debug,
which is misleadingly slow):

- Frame build and raster times during a sustained pinch-zoom and pan
- Frames exceeding 16ms as a percentage
- Memory held for a 1800x2400 canvas plus its region map
- Time from launch to interactive

# Calibration sweeps

Measurement scripts backing the numbers in `docs/PHASE0-FINDINGS.md`. They are tracked rather
than thrown away because several pipeline constants are fitted to the 7-image development set
and **must be recalibrated against the real corpus**.

Run from `pipeline/` with the corpus directory in place:

```bash
uv run python bench/texture.py            # texture -> region density correlation
uv run python bench/sweep_minarea.py      # minimum effective radius vs region count
uv run python bench/sweep_colours.py      # palette size vs region count and numberability
uv run python bench/sweep_resolution.py   # working resolution (found NOT to be a lever)
uv run python bench/check_numbering.py    # unnumbered fraction and placement correctness
```

What to re-fit once real photos are available:

| Constant | Location | Why |
|---|---|---|
| `_TEXTURE_LOG` / `_TEXTURE_STRENGTH` | `pbn/preprocess.py` | Texture→flatten map, fitted to 7 images |
| `DEFAULT_MIN_RADIUS_SCALE` | `pbn/segment.py` | Trades region count against numberability |
| `BACKGROUND_MIN_RADIUS_MULTIPLIER` | `pbn/segment.py` | How coarse backgrounds become |
| `VARIANTS` | `pbn/pipeline.py` | Preset colour counts and radius floors |

`sweep_resolution.py` records a negative result and is kept so nobody re-litigates it: raising
working resolution does not increase region count.

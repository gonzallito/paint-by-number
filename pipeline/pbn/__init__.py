"""Photo to color-by-number conversion pipeline."""

__version__ = "0.1.0"

# Bump when the artifact bundle format changes in a way the app must know about.
# See .kiro/steering/project.md for the artifact contract.
#
# 2: added per-region ``reveal_zoom`` (numbers appear as the user zooms in) and a
#    ``regions_by_colour`` index (highlighting an active colour without scanning the ID map).
ARTIFACT_FORMAT_VERSION = 2

# Bump whenever a change alters the artwork a given photo produces.
#
# Distinct from ARTIFACT_FORMAT_VERSION, which describes the bundle's *shape*. This describes its
# *content*. The service deduplicates uploads by photo digest, so without this an artwork converted
# by an older pipeline is returned forever and no improvement ever reaches a photo already
# converted — which is exactly what happened: re-uploading a photo kept returning the version with
# all its detail piled onto one object.
#
# Bump it in the same commit as the change. A cosmetic edit does not count; a different label map
# does.
#
# 1: pre-versioning.
# 2: segment once and trim to target rather than searching for a radius floor; region budget
#    allocated by subject area with a 2x density boost rather than a fixed 72% share; the
#    flat-background region cap removed; k-means seeded, making conversion deterministic.
CONVERSION_VERSION = 2

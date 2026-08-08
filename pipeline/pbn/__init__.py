"""Photo to color-by-number conversion pipeline."""

__version__ = "0.1.0"

# Bump when the artifact bundle format changes in a way the app must know about.
# See .kiro/steering/project.md for the artifact contract.
#
# 2: added per-region ``reveal_zoom`` (numbers appear as the user zooms in) and a
#    ``regions_by_colour`` index (highlighting an active colour without scanning the ID map).
ARTIFACT_FORMAT_VERSION = 2

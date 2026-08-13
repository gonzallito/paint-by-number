"""Image IO and resizing.

Channel-order convention for the whole pipeline: **RGB uint8**.

OpenCV defaults to BGR, but PIL, matplotlib and scikit-image all use RGB, and most of
our rendering goes through PIL. The only OpenCV calls that actually care about channel
order are colour-space conversions, which we always spell explicitly (``COLOR_RGB2LAB``).
Keeping everything RGB avoids a whole category of silent red/blue-swap bugs.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

# Extensions we accept as pipeline input. HEIC/HEIF are here because phones produce them by
# default; they are decoded through PIL, since OpenCV has no HEIF support.
SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic", ".heif"}


def load(path: str | Path) -> np.ndarray:
    """Load an image as RGB uint8, stripping any alpha channel and honouring EXIF rotation."""
    path = Path(path)
    # Read via numpy so non-ASCII paths work; cv2.imread is unreliable with those.
    buf = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)
    if img is None:
        # OpenCV cannot decode HEIC/HEIF at all, which is the format phones shoot by default.
        # Falling back rather than failing is what makes a real camera roll usable.
        return _load_via_pil(path)

    if img.ndim == 2:
        return _apply_exif_rotation(cv2.cvtColor(img, cv2.COLOR_GRAY2RGB), path)
    if img.shape[2] == 4:
        # Composite onto white rather than dropping alpha, so transparent PNGs
        # do not acquire black fringes that then get quantised as a real colour.
        rgb = cv2.cvtColor(img[:, :, :3], cv2.COLOR_BGR2RGB).astype(np.float32)
        alpha = (img[:, :, 3:4].astype(np.float32)) / 255.0
        flattened = np.clip(rgb * alpha + 255.0 * (1.0 - alpha), 0, 255).astype(np.uint8)
        return _apply_exif_rotation(flattened, path)
    return _apply_exif_rotation(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), path)


def _register_heif() -> None:
    """Teach PIL to open HEIF/HEIC. Safe to call repeatedly."""
    try:
        import pillow_heif
    except ImportError:  # pragma: no cover - depends on the wheel being installed
        return
    pillow_heif.register_heif_opener()


def _load_via_pil(path: Path) -> np.ndarray:
    """Decode anything OpenCV refused, including HEIC/HEIF."""
    _register_heif()
    from PIL import Image, ImageOps

    try:
        with Image.open(path) as handle:
            # exif_transpose here rather than _apply_exif_rotation: PIL knows the tag already,
            # and HEIF from a phone is nearly always rotated.
            upright = ImageOps.exif_transpose(handle)
            return np.asarray(upright.convert("RGB"), dtype=np.uint8)
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        raise ValueError(f"could not decode image: {path} ({detail})") from exc


def _apply_exif_rotation(rgb: np.ndarray, path: Path) -> np.ndarray:
    """Rotate to upright per the EXIF orientation tag.

    Necessary because ``cv2.IMREAD_UNCHANGED`` deliberately ignores EXIF, unlike plain
    ``imread``. Phones record orientation in metadata rather than rotating pixels, so without
    this a portrait photo converts sideways — and the subject detector, which expects an
    upright world, would be looking at a rotated one.
    """
    try:
        from PIL import Image

        with Image.open(path) as handle:
            orientation = handle.getexif().get(_EXIF_ORIENTATION_TAG)
    except Exception:
        # No EXIF, or a format PIL will not open. Absent metadata means upright.
        return rgb

    if orientation in (None, 1):
        return rgb
    if orientation == 3:
        return np.ascontiguousarray(np.rot90(rgb, 2))
    if orientation == 6:
        return np.ascontiguousarray(np.rot90(rgb, 3))
    if orientation == 8:
        return np.ascontiguousarray(np.rot90(rgb, 1))
    # 2, 4, 5 and 7 involve mirroring. Rare enough from a camera that guessing is worse than
    # leaving the pixels alone.
    return rgb


# Orientation tag id (274). Resolved by name so the constant is not a bare magic number.
_EXIF_ORIENTATION_TAG = 274


def save(path: str | Path, img: np.ndarray) -> None:
    """Save an RGB uint8 image, creating parent directories as needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if img.ndim == 2:
        ok, buf = cv2.imencode(path.suffix, img)
    else:
        ok, buf = cv2.imencode(path.suffix, cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
    if not ok:
        raise ValueError(f"could not encode image: {path}")
    buf.tofile(str(path))


def fit_long_edge(img: np.ndarray, target: int) -> np.ndarray:
    """Scale so the long edge equals ``target``. Never upscales.

    Upscaling would invent detail that the segmentation would then dutifully turn into
    regions, so small inputs are left alone and reported as-is. Use :func:`ensure_long_edge`
    when enlarging a small source is wanted.
    """
    h, w = img.shape[:2]
    long_edge = max(h, w)
    if long_edge <= target:
        return img
    scale = target / long_edge
    new_size = (max(1, round(w * scale)), max(1, round(h * scale)))
    # INTER_AREA is the correct choice for downscaling; it averages rather than
    # point-samples, which suppresses the aliasing that would otherwise become speckle.
    return cv2.resize(img, new_size, interpolation=cv2.INTER_AREA)


def ensure_long_edge(img: np.ndarray, target: int) -> np.ndarray:
    """Enlarge so the long edge reaches ``target``. Never downscales.

    Region count is proportional to canvas area, so a small source otherwise yields a very short
    artwork: a 0.4MP image gets ~120 regions against ~1,350 for a 6MP phone photo, purely because
    of the 11x difference in area.

    The instinct that upscaling "invents detail that becomes regions" turns out to be wrong in
    practice, measured on real low-resolution photos. Enlarging a 0.4MP photo to 1900px raised it
    from 119 regions and 36 colours to 852 regions and 93 colours with no visible interpolation
    artefacts, and the filled result went from crudely posterised to close to the original.

    Lanczos rather than bilinear: bilinear leaves a soft halo at every edge, which quantises into
    thin ring regions. Lanczos also *lowers* measured texture (it suppresses high-frequency noise),
    so the adaptive flattening backs off and preserves more genuine detail — the enlargement helps
    twice over.
    """
    h, w = img.shape[:2]
    long_edge = max(h, w)
    if long_edge >= target:
        return img
    scale = target / long_edge
    new_size = (max(1, round(w * scale)), max(1, round(h * scale)))
    return cv2.resize(img, new_size, interpolation=cv2.INTER_LANCZOS4)


def list_images(directory: str | Path) -> list[Path]:
    """Return supported image files in ``directory``, sorted by name."""
    directory = Path(directory)
    if not directory.is_dir():
        return []
    return sorted(
        p for p in directory.iterdir() if p.suffix.lower() in SUPPORTED_SUFFIXES and p.is_file()
    )

"""Photo cleanup: background removal → white replacement → crop-to-subject → levels.

All local CPU (rembg U2-Net + Pillow), no cloud. The U2-Net weights are baked into the
Docker image (see Dockerfile) so the container works offline. Degrades honestly: rembg
unavailable or removal fails ⇒ Pillow-only pass (levels, no background swap) — the
pipeline never blocks a draft on cleanup.

Pure-ish and synchronous by design (CPU-bound); the scan pipeline runs it in a thread.
"""

import io
import logging

from PIL import Image, ImageOps

from app.config import settings

logger = logging.getLogger(__name__)

# Margin kept around the subject when cropping to its alpha bounding box, as a fraction of
# the box's long edge — tight enough to fill the frame, loose enough not to amputate shadows.
_CROP_MARGIN = 0.06
# eBay recommends >=1600px longest side; our client already downscales to <=1600.
_MAX_EDGE = 1600


def _remove_background(image_bytes: bytes) -> Image.Image | None:
    """rembg → RGBA cutout, or None when disabled/unavailable/failed."""
    if not settings.background_removal_enabled:
        return None
    try:
        from rembg import remove  # heavy import (onnxruntime) — deliberately lazy
    except Exception:  # noqa: BLE001 - see below; pragma: no cover (envs without rembg)
        # Deliberately blind: this import fails in more ways than ImportError (a broken
        # onnxruntime build, a missing native lib, a CUDA stub). Any of them must degrade
        # to the Pillow-only path, never 500 a scan.
        logger.warning("rembg unavailable; falling back to Pillow-only cleanup")
        return None
    try:
        result = remove(image_bytes)
        return Image.open(io.BytesIO(result)).convert("RGBA")
    except Exception:
        logger.exception("background removal failed; falling back to Pillow-only cleanup")
        return None


def _crop_to_subject(cutout: Image.Image) -> Image.Image:
    alpha = cutout.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:  # fully transparent — treat as removal failure upstream
        return cutout
    left, top, right, bottom = bbox
    margin = int(max(right - left, bottom - top) * _CROP_MARGIN)
    left = max(0, left - margin)
    top = max(0, top - margin)
    right = min(cutout.width, right + margin)
    bottom = min(cutout.height, bottom + margin)
    return cutout.crop((left, top, right, bottom))


def _shrink(image: Image.Image) -> Image.Image:
    if max(image.size) <= _MAX_EDGE:
        return image
    image.thumbnail((_MAX_EDGE, _MAX_EDGE), Image.LANCZOS)
    return image


def _levels(image: Image.Image) -> Image.Image:
    """Gentle levels: clip 1% shadows/highlights — brightens typical indoor phone shots
    without the lying-about-condition look of aggressive filters.

    `preserve_tone=True` derives ONE mapping from luminance instead of stretching each RGB
    channel against its own endpoints. Per-channel is what "auto levels" usually means, but
    it is wrong here: a saturated garment on a neutral ground drives each channel's endpoints
    differently, so the correction pushes a complementary cast into the background (a red
    shirt turned the backdrop teal) and shifts the garment's own hue — and `color` is an item
    specific this app records and lists on.
    """
    return ImageOps.autocontrast(image, cutoff=1, preserve_tone=True)


def clean_photo(image_bytes: bytes) -> bytes:
    """Original bytes → cleaned PNG bytes. Never raises on bad model output — worst case
    is a levels-only pass of the original.

    Order matters: levels are applied to the ORIGINAL photo, before any background
    replacement. Applying them afterwards reads the histogram of a synthetic composite —
    the garment plus a field of pure white — in which the garment is by definition the
    darkest content, so the 1% clip lands on the garment itself and maps it toward black.
    On a flat, evenly lit tee that was total: every colourway, including a light heather
    grey, came out pure black. Correcting the capture's exposure and then compositing keeps
    the white ground white and leaves the garment where the camera saw it.
    """
    corrected = _levels(Image.open(io.BytesIO(image_bytes)).convert("RGB"))

    # rembg segments the exposure-corrected photo; re-encoded losslessly so the model sees
    # exactly what we will composite from.
    corrected_bytes = io.BytesIO()
    corrected.save(corrected_bytes, format="PNG")
    cutout = _remove_background(corrected_bytes.getvalue())

    if cutout is not None and cutout.getchannel("A").getbbox() is not None:
        subject = _crop_to_subject(cutout)
        canvas = Image.new("RGB", subject.size, (255, 255, 255))
        canvas.paste(subject, mask=subject.getchannel("A"))
        cleaned = canvas
    else:
        cleaned = corrected

    cleaned = _shrink(cleaned)

    out = io.BytesIO()
    cleaned.save(out, format="PNG")
    return out.getvalue()

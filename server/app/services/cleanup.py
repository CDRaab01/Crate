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
    except Exception:  # pragma: no cover — exercised only in envs without rembg
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


def clean_photo(image_bytes: bytes) -> bytes:
    """Original bytes → cleaned PNG bytes. Never raises on bad model output — worst case
    is an autocontrast-only pass of the original."""
    cutout = _remove_background(image_bytes)

    if cutout is not None and cutout.getchannel("A").getbbox() is not None:
        subject = _crop_to_subject(cutout)
        canvas = Image.new("RGB", subject.size, (255, 255, 255))
        canvas.paste(subject, mask=subject.getchannel("A"))
        cleaned = canvas
    else:
        cleaned = Image.open(io.BytesIO(image_bytes)).convert("RGB")

    cleaned = _shrink(cleaned)
    # Gentle levels: clip 1% shadows/highlights — brightens typical indoor phone shots
    # without the lying-about-condition look of aggressive filters.
    cleaned = ImageOps.autocontrast(cleaned, cutoff=1)

    out = io.BytesIO()
    cleaned.save(out, format="PNG")
    return out.getvalue()

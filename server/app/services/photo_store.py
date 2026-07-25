"""Item-photo storage: binaries on the photos volume, paths in the DB.

Layout: {photos_dir}/{item_id}/original_{n}.jpg + cleaned_{n}.png. Filenames are
server-generated (never client-supplied) so a crafted upload name can't traverse paths.
"""

import uuid
from pathlib import Path

from app.config import settings

ALLOWED_CONTENT_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


def item_dir(item_id: uuid.UUID) -> Path:
    d = Path(settings.photos_dir) / str(item_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_original(item_id: uuid.UUID, order: int, data: bytes, content_type: str) -> str:
    ext = ALLOWED_CONTENT_TYPES[content_type]
    path = item_dir(item_id) / f"original_{order}{ext}"
    path.write_bytes(data)
    return str(path)


def cleaned_path_for(item_id: uuid.UUID, order: int) -> str:
    # Cleaned output is always PNG: the white-replacement composite needs a lossless target
    # and eBay accepts PNG uploads.
    return str(item_dir(item_id) / f"cleaned_{order}.png")


def read_bytes(path: str) -> bytes:
    return Path(path).read_bytes()

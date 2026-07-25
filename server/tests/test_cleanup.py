"""Pillow-path cleanup tests (rembg disabled — CI never downloads U2-Net weights)."""

import io

import pytest
from PIL import Image

from app.config import settings
from app.services.cleanup import clean_photo


@pytest.fixture(autouse=True)
def no_rembg(monkeypatch):
    monkeypatch.setattr(settings, "background_removal_enabled", False)


def _jpeg(size=(400, 300), color=(90, 60, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


def test_clean_photo_outputs_png():
    out = clean_photo(_jpeg())
    img = Image.open(io.BytesIO(out))
    assert img.format == "PNG"
    assert img.size == (400, 300)


def test_clean_photo_caps_long_edge():
    out = clean_photo(_jpeg(size=(3200, 1600)))
    img = Image.open(io.BytesIO(out))
    assert max(img.size) <= 1600

"""Real, decodable sample images for the photo pipeline — garments, products, tags.

Generated with Pillow rather than committed as binaries: no blobs in git, deterministic
across machines, and the code itself documents what each sample is meant to represent.
They are real image files — real encoders, real dimensions, a real subject sitting on a
real background — which is the point. The tests that used `b"\\x89PNG...fakebytes"` never
decoded anything, so nothing exercised cleanup, storage or serving with actual pixels.

Honest about what they are NOT: these are flat synthetic silhouettes, not photographs. They
prove the plumbing (decode → clean → encode → store → serve) and the cleanup *geometry*
(crop-to-subject, white replacement, downscale). They cannot prove perceptual quality or
rembg's segmentation accuracy on a real phone shot — that needs the on-device pass and
`scripts/photo_smoke.py` against real clothing photos.

`python -m tests.fixtures.images <dir>` writes the whole set out to look at.
"""

import io
import random

from PIL import Image, ImageDraw, ImageFilter

# Roughly a phone photo's aspect, small enough to keep tests fast.
DEFAULT_SIZE = (900, 1200)

# Sample colorways, named as a tag would print them.
NAVY = (32, 42, 68)
HEATHER_GREY = (150, 152, 158)
FADED_RED = (168, 58, 52)
DENIM = (74, 96, 130)
STUDIO_BACKDROP = (238, 238, 240)  # the light seamless a phone shot on a sheet approximates


def _texturize(image: Image.Image, seed: int = 7) -> Image.Image:
    """Give the sample a photograph's tonal range instead of two flat tones.

    This is not decoration, and getting it wrong makes the tests lie. `cleanup` finishes
    with `ImageOps.autocontrast(cutoff=1)`, which clips the darkest and brightest one
    percent of PIXELS BY COUNT and stretches what remains. On a flat synthetic fill the
    garment itself is the darkest content, so it gets clipped to pure black and any colour
    assertion fails for a reason that would never occur in production. A handful of thin
    crease lines does not help either — they are well under one percent of the frame, so
    they are discarded and the garment becomes the black point again.

    What a real photo has, and what this reproduces, is broad soft shading from one-sided
    lighting plus a blown highlight: the clipped tail is then shadow rather than subject,
    and the garment's mid-tone survives with its hue intact. Seeded, so fixtures stay
    deterministic across machines.
    """
    rng = random.Random(seed)
    w, h = image.size

    # Sensor noise.
    noise = Image.new("L", (w, h))
    noise.putdata([rng.randint(100, 156) for _ in range(w * h)])
    noise = noise.filter(ImageFilter.GaussianBlur(1.0))
    out = Image.blend(image, Image.merge("RGB", (noise, noise, noise)), 0.06)

    # One-sided lighting falloff, brightening toward the lower right.
    shade = Image.new("L", (w, h))
    shade.putdata(
        [int(150 + 105 * ((x / w) * 0.55 + (y / h) * 0.45)) for y in range(h) for x in range(w)]
    )
    shade = shade.filter(ImageFilter.GaussianBlur(min(w, h) // 12))
    out = Image.composite(out, Image.new("RGB", (w, h), (0, 0, 0)), shade)

    # A blown highlight where the light lands — the frame's white point.
    ImageDraw.Draw(out).ellipse(
        [int(w * 0.60), int(h * 0.20), int(w * 0.74), int(h * 0.29)], fill=(253, 253, 255)
    )
    return out


def _encode(image: Image.Image, fmt: str, quality: int = 90) -> bytes:
    buf = io.BytesIO()
    if fmt.upper() == "JPEG":
        image.convert("RGB").save(buf, format="JPEG", quality=quality)
    else:
        image.save(buf, format=fmt.upper())
    return buf.getvalue()


def _shirt_shape(draw: ImageDraw.ImageDraw, box, color) -> None:
    """A body + two sleeves + a collar notch — enough silhouette to crop against."""
    left, top, right, bottom = box
    width = right - left
    height = bottom - top
    shoulder = top + int(height * 0.18)
    body_left = left + int(width * 0.22)
    body_right = right - int(width * 0.22)

    # Sleeves.
    draw.polygon(
        [
            (body_left, shoulder),
            (left, shoulder + int(height * 0.22)),
            (left + int(width * 0.10), shoulder + int(height * 0.34)),
            (body_left, shoulder + int(height * 0.20)),
        ],
        fill=color,
    )
    draw.polygon(
        [
            (body_right, shoulder),
            (right, shoulder + int(height * 0.22)),
            (right - int(width * 0.10), shoulder + int(height * 0.34)),
            (body_right, shoulder + int(height * 0.20)),
        ],
        fill=color,
    )
    # Body.
    draw.rectangle([body_left, shoulder, body_right, bottom], fill=color)
    # Collar notch.
    collar_w = int(width * 0.10)
    centre = (body_left + body_right) // 2
    draw.ellipse(
        [centre - collar_w, shoulder - collar_w // 2, centre + collar_w, shoulder + collar_w],
        fill=STUDIO_BACKDROP,
    )


def garment_photo(
    size: tuple[int, int] = DEFAULT_SIZE,
    color: tuple[int, int, int] = NAVY,
    fmt: str = "JPEG",
    background: tuple[int, int, int] = STUDIO_BACKDROP,
) -> bytes:
    """A shirt laid flat on a light background — the archetypal Crate capture."""
    image = Image.new("RGB", size, background)
    draw = ImageDraw.Draw(image)
    w, h = size
    _shirt_shape(draw, (int(w * 0.12), int(h * 0.14), int(w * 0.88), int(h * 0.82)), color)
    return _encode(_texturize(image), fmt)


def jeans_photo(size: tuple[int, int] = DEFAULT_SIZE, fmt: str = "JPEG") -> bytes:
    """A bottoms silhouette — exercises the same path with a different subject shape."""
    image = Image.new("RGB", size, STUDIO_BACKDROP)
    draw = ImageDraw.Draw(image)
    w, h = size
    draw.rectangle([int(w * 0.32), int(h * 0.16), int(w * 0.68), int(h * 0.38)], fill=DENIM)
    draw.rectangle([int(w * 0.32), int(h * 0.38), int(w * 0.47), int(h * 0.86)], fill=DENIM)
    draw.rectangle([int(w * 0.53), int(h * 0.38), int(w * 0.68), int(h * 0.86)], fill=DENIM)
    return _encode(_texturize(image), fmt)


def tag_photo(size: tuple[int, int] = (800, 800), fmt: str = "JPEG") -> bytes:
    """A care/size tag close-up — the shot that decides whether size and material are
    knowable at all. Text-like marks only; the fixtures do not carry a font."""
    image = Image.new("RGB", size, STUDIO_BACKDROP)
    draw = ImageDraw.Draw(image)
    w, h = size
    draw.rectangle(
        [int(w * 0.22), int(h * 0.24), int(w * 0.78), int(h * 0.76)], fill=(252, 251, 247)
    )
    for i in range(5):
        y = int(h * 0.34) + i * int(h * 0.08)
        draw.rectangle(
            [int(w * 0.30), y, int(w * 0.30 + w * 0.34 * (0.5 + 0.1 * i)), y + 8], fill=(60, 60, 64)
        )
    return _encode(image, fmt)


def product_photo(size: tuple[int, int] = (900, 900), fmt: str = "JPEG") -> bytes:
    """A small general good (a lure-ish object) — the non-apparel path, which must never
    be flagged for missing size or department."""
    image = Image.new("RGB", size, STUDIO_BACKDROP)
    draw = ImageDraw.Draw(image)
    w, h = size
    draw.ellipse([int(w * 0.30), int(h * 0.44), int(w * 0.70), int(h * 0.56)], fill=(190, 140, 55))
    draw.line(
        [int(w * 0.70), int(h * 0.50), int(w * 0.80), int(h * 0.50)], fill=(120, 120, 128), width=6
    )
    return _encode(_texturize(image), fmt)


def garment_cutout(
    size: tuple[int, int] = DEFAULT_SIZE,
    color: tuple[int, int, int] = NAVY,
) -> Image.Image:
    """An RGBA cutout as rembg would return it: opaque subject, transparent surround.

    Returned as a PIL image (not bytes) because it stands in for `_remove_background`'s
    return value — which is how the crop-to-subject and white-composite code gets exercised
    for real without downloading U2-Net weights in CI.
    """
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    w, h = size
    # Deliberately inset, so a correct crop visibly shrinks the frame.
    draw.rectangle(
        [int(w * 0.25), int(h * 0.30), int(w * 0.75), int(h * 0.70)],
        fill=(*color, 255),
    )
    return image


def corrupt_image_bytes() -> bytes:
    """A truncated JPEG: right magic bytes, unreadable payload. Stands in for a capture
    that died mid-upload — the draft must survive with its photos rather than vanish."""
    return garment_photo(size=(400, 400))[:120]


SAMPLES = {
    "shirt_navy": lambda: garment_photo(color=NAVY),
    "shirt_red": lambda: garment_photo(color=FADED_RED),
    "shirt_heather": lambda: garment_photo(color=HEATHER_GREY),
    "jeans": jeans_photo,
    "care_tag": tag_photo,
    "product_lure": product_photo,
}


def write_samples(directory: str) -> list[str]:
    """Write every sample to `directory` as JPEG. Returns the paths written."""
    from pathlib import Path

    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, build in SAMPLES.items():
        path = out / f"{name}.jpg"
        path.write_bytes(build())
        written.append(str(path))
    return written


if __name__ == "__main__":  # pragma: no cover - developer convenience
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "sample_photos"
    for written in write_samples(target):
        print(written)

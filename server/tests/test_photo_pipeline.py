"""End-to-end photo pipeline against REAL images — decode, clean, store, serve.

Every other scan test uploads `b"\\x89PNG\\r\\n\\x1a\\nfakebytes"` with `clean_photo`
monkeypatched to a passthrough, which means nothing in the suite ever decoded a pixel. These
tests push real JPEG/PNG/WebP garment and product photos (tests/fixtures/images.py) through
the actual endpoint and the actual cleanup code, then decode what comes back out.

rembg stays disabled throughout, per the `test_cleanup.py` precedent — CI must never
download U2-Net weights. The background-removal *branch* is still covered for real by
stubbing `_remove_background` with a genuine RGBA cutout, so crop-to-subject and the white
composite run on actual pixels rather than being skipped.

What these cannot prove: perceptual quality, or rembg's segmentation on a real phone shot.
That is `scripts/photo_smoke.py` against real clothing photos plus the on-device pass.
"""

import asyncio
import io

import pytest
from PIL import Image

from app.config import settings
from app.services import cleanup, scan_pipeline
from app.services.ai.identify_prompts import IdentifyDraft
from app.services.cleanup import clean_photo
from tests.fixtures import images


@pytest.fixture(autouse=True)
def photos_tmpdir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "photos_dir", str(tmp_path / "photos"))


@pytest.fixture(autouse=True)
def no_rembg(monkeypatch):
    """CI never downloads U2-Net; the removal branch is covered by stubbing the cutout."""
    monkeypatch.setattr(settings, "background_removal_enabled", False)


def _decode(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


# --- clean_photo on real pixels ---------------------------------------------------------


@pytest.mark.parametrize(
    "name,build",
    [
        ("navy shirt", lambda: images.garment_photo(color=images.NAVY)),
        ("red shirt", lambda: images.garment_photo(color=images.FADED_RED)),
        ("jeans", images.jeans_photo),
        ("care tag", images.tag_photo),
        ("product", images.product_photo),
    ],
)
def test_cleanup_produces_a_decodable_png_for_every_sample(name, build):
    out = clean_photo(build())
    img = _decode(out)
    assert img.format == "PNG", name
    assert img.mode == "RGB", name
    assert min(img.size) > 0, name


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
def test_cleanup_accepts_every_upload_format(fmt):
    """The three content types photo_store allows must all survive a real decode."""
    out = clean_photo(images.garment_photo(fmt=fmt))
    assert _decode(out).format == "PNG"


def test_cleanup_downscales_an_oversized_capture():
    """A camera original blows past eBay's useful resolution; the pipeline caps the long edge."""
    out = clean_photo(images.garment_photo(size=(3000, 4000)))
    assert max(_decode(out).size) <= 1600


def test_cleanup_leaves_an_already_small_photo_at_its_size():
    out = clean_photo(images.garment_photo(size=(900, 1200)))
    assert _decode(out).size == (900, 1200)


@pytest.mark.parametrize(
    "name,colour,dominant",
    [
        ("navy", images.NAVY, 2),
        ("faded red", images.FADED_RED, 0),
        ("denim", images.DENIM, 2),
    ],
)
def test_cleanup_keeps_the_garment_hue(name, colour, dominant):
    """A listing photo that lies about colour is a return, and `color` is an item specific
    this app records. The levels pass must not reorder the channels."""
    img = _decode(clean_photo(images.garment_photo(color=colour))).convert("RGB")
    px = img.getpixel((int(img.width * 0.42), int(img.height * 0.62)))
    assert px.index(max(px)) == dominant, f"{name} garment came back as {px}"


# --- the background-removal branch, on a real cutout ------------------------------------


def test_removal_branch_crops_to_the_subject_and_whitens_the_background(monkeypatch):
    """The rembg path for real, minus the model: a cutout with a transparent surround must
    come back cropped to the subject (+ margin) and composited onto white."""
    size = (900, 1200)
    monkeypatch.setattr(
        cleanup, "_remove_background", lambda data: images.garment_cutout(size=size)
    )

    out = clean_photo(images.garment_photo(size=size))
    img = _decode(out).convert("RGB")

    # The subject occupies the middle 50% x 40%; a correct crop is far smaller than the frame.
    assert img.width < size[0] and img.height < size[1]
    # Corner is background: the composite fills it white rather than leaving it transparent.
    assert img.getpixel((0, 0)) == (255, 255, 255)
    # Centre is still the garment, and still navy.
    r, g, b = img.getpixel((img.width // 2, img.height // 2))
    assert b > r and b > g


def test_fully_transparent_cutout_falls_back_to_the_original(monkeypatch):
    """A removal that erases everything is a failure, not a valid empty photo. The
    documented degrade is a Pillow-only pass — never a blank draft."""
    blank = Image.new("RGBA", (600, 800), (0, 0, 0, 0))
    monkeypatch.setattr(cleanup, "_remove_background", lambda data: blank)

    out = clean_photo(images.garment_photo(size=(600, 800)))
    img = _decode(out)
    assert img.size == (600, 800)
    # The garment is still there, i.e. we fell back rather than compositing nothing.
    r, g, b = img.convert("RGB").getpixel((img.width // 2, int(img.height * 0.55)))
    assert b > r and b > g


def test_removal_failure_still_yields_a_usable_photo(monkeypatch):
    """rembg raising (or being absent) must not cost the capture."""
    monkeypatch.setattr(cleanup, "_remove_background", lambda data: None)
    assert _decode(clean_photo(images.garment_photo())).format == "PNG"


# --- through the endpoint ----------------------------------------------------------------


def _files(payloads: list[tuple[str, bytes, str]]):
    return [("photos", (name, data, ctype)) for name, data, ctype in payloads]


async def _wait_processed(client, item_id, attempts=60):
    for _ in range(attempts):
        r = await client.get(f"/items/{item_id}")
        if r.json()["processed_at"] is not None:
            return r.json()
        await asyncio.sleep(0.05)
    raise AssertionError("draft never finished processing")


@pytest.fixture
def real_vision(monkeypatch):
    """Cleanup runs for real; only the LM Studio call is stubbed (always mocked in CI).
    The draft mirrors what a tagged navy button-up would actually come back as."""

    def _install(draft: IdentifyDraft):
        async def fake_identify(urls, client=None):
            # Guard the contract the pipeline depends on: identification is handed real,
            # decodable, cleaned image data — not the raw upload and not a placeholder.
            assert urls, "identify received no images"
            for url in urls:
                assert url.startswith("data:image/png;base64,")
            return draft

        monkeypatch.setattr(scan_pipeline, "identify_item", fake_identify)

    _install(
        IdentifyDraft(
            title="Patagonia Organic Cotton Button-Up Navy Mens M",
            brand="Patagonia",
            condition="good",
            description="A navy organic-cotton button-up.",
            weight_oz=9.0,
            item_kind="clothing",
            department="mens",
            size="M",
            size_type="regular",
            color="Navy",
            material="100% Organic Cotton",
            style="Button-Up",
            sleeve_length="long",
            confidence="high",
        )
    )
    return _install


async def test_real_garment_photo_scans_into_a_complete_draft(auth_client, real_vision):
    """The whole point, with no eBay anywhere: a real photo in, an archived garment out."""
    r = await auth_client.post(
        "/items/scan", files=_files([("shirt.jpg", images.garment_photo(), "image/jpeg")])
    )
    assert r.status_code == 202, r.text
    item = await _wait_processed(auth_client, r.json()["id"])

    assert item["scan_error"] is None
    assert item["item_kind"] == "clothing"
    assert item["size"] == "M"
    assert item["photos"][0]["cleaned"] is True
    # Measurements are the one thing no photo can supply.
    assert item["missing_hand_only"] == ["measurements"]


@pytest.mark.parametrize(
    "fmt,ctype,ext",
    [("JPEG", "image/jpeg", "jpg"), ("PNG", "image/png", "png"), ("WEBP", "image/webp", "webp")],
)
async def test_every_allowed_upload_format_round_trips(auth_client, real_vision, fmt, ctype, ext):
    r = await auth_client.post(
        "/items/scan", files=_files([(f"shirt.{ext}", images.garment_photo(fmt=fmt), ctype)])
    )
    assert r.status_code == 202, r.text
    item = await _wait_processed(auth_client, r.json()["id"])
    assert item["scan_error"] is None
    assert item["photos"][0]["cleaned"] is True


async def test_batch_capture_cleans_every_angle_in_order(auth_client, real_vision):
    """Multi-angle capture: front, back, tag. All three stored, cleaned, order preserved."""
    r = await auth_client.post(
        "/items/scan",
        files=_files(
            [
                ("front.jpg", images.garment_photo(color=images.NAVY), "image/jpeg"),
                ("back.jpg", images.garment_photo(color=images.NAVY), "image/jpeg"),
                ("tag.jpg", images.tag_photo(), "image/jpeg"),
            ]
        ),
    )
    item = await _wait_processed(auth_client, r.json()["id"])
    assert len(item["photos"]) == 3
    assert [p["order"] for p in item["photos"]] == [0, 1, 2]
    assert all(p["cleaned"] for p in item["photos"])


async def test_served_photo_is_a_real_decodable_image(auth_client, real_vision):
    """The review stack renders these; a served byte stream that Pillow can't open would
    show as a broken thumbnail on the phone and nowhere else."""
    r = await auth_client.post(
        "/items/scan", files=_files([("shirt.jpg", images.garment_photo(), "image/jpeg")])
    )
    item = await _wait_processed(auth_client, r.json()["id"])
    photo_id = item["photos"][0]["id"]

    r = await auth_client.get(f"/items/{item['id']}/photos/{photo_id}/file")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"  # cleaned output is PNG
    served = _decode(r.content)
    assert served.format == "PNG"
    assert max(served.size) <= 1600


async def test_product_photo_is_archived_without_apparel_nagging(auth_client, real_vision):
    """A real non-garment photo: it must archive cleanly and report no clothing gaps."""
    real_vision(
        IdentifyDraft(
            title="Rapala Original Floater F11",
            brand="Rapala",
            model="F11",
            condition="good",
            item_kind="general",
            confidence="high",
        )
    )
    r = await auth_client.post(
        "/items/scan", files=_files([("lure.jpg", images.product_photo(), "image/jpeg")])
    )
    item = await _wait_processed(auth_client, r.json()["id"])
    assert item["item_kind"] == "general"
    assert item["missing_for_listing"] == []
    assert item["missing_hand_only"] == []
    assert item["photos"][0]["cleaned"] is True


async def test_corrupt_photo_does_not_destroy_the_capture(auth_client, real_vision):
    """A capture that died mid-upload still reaches the server. The draft and its bytes must
    survive with an honest scan_error — losing the row would lose the only record that the
    item was ever photographed."""
    r = await auth_client.post(
        "/items/scan", files=_files([("broken.jpg", images.corrupt_image_bytes(), "image/jpeg")])
    )
    assert r.status_code == 202, r.text
    item = await _wait_processed(auth_client, r.json()["id"])

    assert item["scan_error"] == "scan_failed"
    assert len(item["photos"]) == 1
    assert item["photos"][0]["cleaned"] is False
    # The original bytes are still retrievable, so the photo can be re-processed by hand.
    r = await auth_client.get(f"/items/{item['id']}/photos/{item['photos'][0]['id']}/file")
    assert r.status_code == 200


async def test_oversized_capture_is_downscaled_on_the_way_in(auth_client, real_vision):
    """The client downscales to <=1600px, but a gallery pick or a third-party client can
    still send a camera original; the server must not store or serve it full size."""
    big = images.garment_photo(size=(2400, 3200))
    r = await auth_client.post("/items/scan", files=_files([("big.jpg", big, "image/jpeg")]))
    item = await _wait_processed(auth_client, r.json()["id"])

    r = await auth_client.get(f"/items/{item['id']}/photos/{item['photos'][0]['id']}/file")
    assert max(_decode(r.content).size) <= 1600


async def test_archive_completion_flow_with_a_real_photo(auth_client, real_vision):
    """The full archive-first loop: photograph a garment whose tag was never shot, see
    exactly what is missing, fill it in with the shirt in hand, and watch the gaps close."""
    real_vision(
        IdentifyDraft(
            title="Navy Button-Up Shirt",
            brand="Patagonia",
            condition="good",
            item_kind="clothing",
            department="mens",
            color="Navy",
            style="Button-Up",
            size=None,  # no legible tag in the photos
            size_type=None,
            material=None,
            confidence="medium",
        )
    )
    r = await auth_client.post(
        "/items/scan", files=_files([("shirt.jpg", images.garment_photo(), "image/jpeg")])
    )
    item = await _wait_processed(auth_client, r.json()["id"])

    assert set(item["missing_hand_only"]) == {"size", "size_type", "material", "measurements"}

    r = await auth_client.patch(
        f"/items/{item['id']}",
        json={
            "size": "M",
            "size_type": "Regular",
            "material": "100% Organic Cotton",
            "measurements_in": {"chest": 21, "length": 29},
            "storage_location": "Bin 3",
        },
    )
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["missing_hand_only"] == []
    assert done["missing_for_listing"] == []
    assert done["storage_location"] == "Bin 3"
    # And the photos are still there, cleaned, after the edit.
    assert done["photos"][0]["cleaned"] is True


# --- levels: order of operations ---------------------------------------------------------
# Regression guards for a real defect found while writing these tests. The levels pass used
# to run AFTER background replacement, i.e. on a composite of the garment plus a field of
# pure white. In that image the garment is by definition the darkest content, so the 1%
# shadow clip landed on the garment itself and mapped it toward black — on a flat, evenly
# lit tee, every colourway including a light heather grey came out pure (0, 0, 0). The
# per-channel stretch also pushed a complementary cast into the background (a red shirt
# turned the backdrop teal). Levels now run on the original capture, with preserve_tone.


@pytest.mark.parametrize(
    "name,colour",
    [
        ("navy", images.NAVY),
        ("faded red", images.FADED_RED),
        ("denim", images.DENIM),
        ("heather grey", images.HEATHER_GREY),
    ],
)
def test_white_replacement_never_blackens_the_garment(monkeypatch, name, colour):
    """The regression that mattered most: a garment must survive the white composite."""
    cutout = images.garment_cutout(size=(600, 800), color=colour)
    monkeypatch.setattr(cleanup, "_remove_background", lambda data: cutout)

    img = _decode(clean_photo(images.garment_photo(size=(600, 800), color=colour))).convert("RGB")
    px = img.getpixel((img.width // 2, img.height // 2))
    assert sum(px) > 60, f"{name} garment was crushed to {px} by the white composite"
    # And it is still recognisably the colour that was photographed.
    assert px.index(max(px)) == colour.index(max(colour)), f"{name} shifted hue to {px}"


def test_white_replacement_leaves_the_background_pure_white(monkeypatch):
    """No colour cast on the ground. eBay wants a white background; a teal one is not it."""
    cutout = images.garment_cutout(size=(600, 800), color=images.FADED_RED)
    monkeypatch.setattr(cleanup, "_remove_background", lambda data: cutout)

    img = _decode(clean_photo(images.garment_photo(size=(600, 800), color=images.FADED_RED)))
    img = img.convert("RGB")
    for corner in [(0, 0), (img.width - 1, 0), (0, img.height - 1)]:
        assert img.getpixel(corner) == (255, 255, 255), f"background cast at {corner}"


def test_levels_still_lift_an_underexposed_capture():
    """The correction must not have been thrown out with the bug — a dim indoor shot should
    still come back brighter than it went in."""
    dim = Image.open(io.BytesIO(images.garment_photo())).convert("RGB")
    dim = dim.point(lambda v: int(v * 0.45))
    buf = io.BytesIO()
    dim.save(buf, format="PNG")

    before = sum(dim.convert("L").getdata()) / (dim.width * dim.height)
    out = _decode(clean_photo(buf.getvalue())).convert("L")
    after = sum(out.getdata()) / (out.width * out.height)
    assert after > before * 1.2, f"levels did not lift the exposure ({before:.1f} -> {after:.1f})"

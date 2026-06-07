import io
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient
from PIL import Image

from app.main import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_jpeg_bytes(width: int = 100, height: int = 100) -> bytes:
    img = Image.new("RGB", (width, height), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _fake_cloudinary_result(folder: str, name: str, kind: str = "image") -> dict:
    ext = "jpg" if kind == "image" else "mp4"
    return {
        "secure_url": f"https://res.cloudinary.com/test/{kind}/upload/{folder}/{name}.{ext}",
        "public_id": f"{folder}/{name}",
    }


_FAKE_MP4 = b"\x00\x00\x00\x18ftyp"


async def _upload(client, file_bytes, content_type, folder, cloudinary_result):
    with patch("cloudinary.uploader.upload", return_value=cloudinary_result):
        r = await client.post(
            "/storage/upload",
            files={"file": ("file", file_bytes, content_type)},
            data={"folder": folder},
        )
    return r


# ---------------------------------------------------------------------------
# Upload — imágenes
# ---------------------------------------------------------------------------

async def test_upload_product_image_success():
    fake = _fake_cloudinary_result("bazaar/products", "abc")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await _upload(c, _make_jpeg_bytes(), "image/jpeg", "bazaar/products", fake)

    assert r.status_code == 200
    assert r.json() == {"url": fake["secure_url"]}


async def test_upload_profile_image_success():
    fake = _fake_cloudinary_result("bazaar/profiles", "usr123")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await _upload(c, _make_jpeg_bytes(), "image/png", "bazaar/profiles", fake)

    assert r.status_code == 200
    assert "url" in r.json()


async def test_upload_profile_too_large():
    import app.services.cloudinary_service as svc

    with patch.object(svc.settings, "MAX_IMAGE_PROFILE_MB", 0):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/storage/upload",
                files={"file": ("avatar.jpg", _make_jpeg_bytes(), "image/jpeg")},
                data={"folder": "bazaar/profiles"},
            )

    assert r.status_code == 400
    assert "supera" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Upload — videos
# ---------------------------------------------------------------------------

async def test_upload_video_success():
    fake = _fake_cloudinary_result("bazaar/videos", "vid001", kind="video")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await _upload(c, _FAKE_MP4, "video/mp4", "bazaar/videos", fake)

    assert r.status_code == 200
    assert r.json() == {"url": fake["secure_url"]}


async def test_upload_image_to_video_folder_rejected():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/storage/upload",
            files={"file": ("photo.jpg", _make_jpeg_bytes(), "image/jpeg")},
            data={"folder": "bazaar/videos"},
        )
    assert r.status_code == 400
    assert "image/jpeg" in r.json()["detail"]
    assert "bazaar/videos" in r.json()["detail"]


async def test_upload_video_to_product_folder_rejected():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/storage/upload",
            files={"file": ("clip.mp4", _FAKE_MP4, "video/mp4")},
            data={"folder": "bazaar/products"},
        )
    assert r.status_code == 400
    assert "video/mp4" in r.json()["detail"]
    assert "bazaar/products" in r.json()["detail"]


async def test_upload_unsupported_format():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/storage/upload",
            files={"file": ("doc.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )
    assert r.status_code == 400
    assert "application/pdf" in r.json()["detail"]


async def test_upload_too_large():
    import app.services.cloudinary_service as svc

    with patch.object(svc.settings, "MAX_IMAGE_PRODUCT_MB", 0):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/storage/upload",
                files={"file": ("photo.jpg", _make_jpeg_bytes(), "image/jpeg")},
                data={"folder": "bazaar/products"},
            )
    assert r.status_code == 400
    assert "supera" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

async def test_delete_image_success():
    fake = _fake_cloudinary_result("bazaar/products", "abc")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        upload_r = await _upload(c, _make_jpeg_bytes(), "image/jpeg", "bazaar/products", fake)
    assert upload_r.status_code == 200
    url = upload_r.json()["url"]

    with patch("cloudinary.uploader.destroy", return_value={"result": "ok"}):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.request("DELETE", "/storage/delete", json={"url": url})

    assert r.status_code == 200
    assert r.json() == {"ok": True}


async def test_delete_video_success():
    fake = _fake_cloudinary_result("bazaar/videos", "vid001", kind="video")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        upload_r = await _upload(c, _FAKE_MP4, "video/mp4", "bazaar/videos", fake)
    assert upload_r.status_code == 200
    url = upload_r.json()["url"]

    with patch("cloudinary.uploader.destroy", return_value={"result": "ok"}) as mock_destroy:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.request("DELETE", "/storage/delete", json={"url": url})

    assert r.status_code == 200
    mock_destroy.assert_called_once_with(fake["public_id"], resource_type="video")


async def test_delete_not_found():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.request(
            "DELETE",
            "/storage/delete",
            json={"url": "https://res.cloudinary.com/test/image/upload/no-existe.jpg"},
        )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------

async def test_livez():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/storage/livez")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_readyz_ok():
    with patch("cloudinary.api.ping", return_value={"status": "ok"}):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/storage/readyz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_readyz_fail():
    with patch("cloudinary.api.ping", side_effect=Exception("connection refused")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/storage/readyz")
    assert r.status_code == 503
    assert r.json()["detail"] == "Cloudinary no disponible"


# ---------------------------------------------------------------------------
# Upload — formatos adicionales válidos
# ---------------------------------------------------------------------------

async def test_upload_webp_success():
    fake = _fake_cloudinary_result("bazaar/products", "webp_img")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await _upload(c, _make_jpeg_bytes(), "image/webp", "bazaar/products", fake)
    assert r.status_code == 200
    assert r.json() == {"url": fake["secure_url"]}


async def test_upload_webm_video_success():
    fake = _fake_cloudinary_result("bazaar/videos", "clip_webm", kind="video")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await _upload(c, _FAKE_MP4, "video/webm", "bazaar/videos", fake)
    assert r.status_code == 200
    assert r.json() == {"url": fake["secure_url"]}


async def test_upload_default_folder():
    """Folder no registrado usa la regla por defecto (imágenes, 10 MB)."""
    fake = _fake_cloudinary_result("bazaar/general", "img_gen")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await _upload(c, _make_jpeg_bytes(), "image/jpeg", "bazaar/general", fake)
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Upload — error de Cloudinary
# ---------------------------------------------------------------------------

async def test_upload_cloudinary_error_returns_500():
    with patch("cloudinary.uploader.upload", side_effect=Exception("timeout")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/storage/upload",
                files={"file": ("photo.jpg", _make_jpeg_bytes(), "image/jpeg")},
                data={"folder": "bazaar/products"},
            )
    assert r.status_code == 500
    assert "timeout" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Delete — casos adicionales
# ---------------------------------------------------------------------------

async def test_delete_cloudinary_error_returns_500():
    fake = _fake_cloudinary_result("bazaar/products", "err_img")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        upload_r = await _upload(c, _make_jpeg_bytes(), "image/jpeg", "bazaar/products", fake)
    url = upload_r.json()["url"]

    with patch("cloudinary.uploader.destroy", return_value={"result": "error"}):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.request("DELETE", "/storage/delete", json={"url": url})
    assert r.status_code == 500


async def test_delete_twice_second_returns_404():
    """Después de borrar, un segundo intento con la misma URL devuelve 404."""
    fake = _fake_cloudinary_result("bazaar/products", "double_del")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        upload_r = await _upload(c, _make_jpeg_bytes(), "image/jpeg", "bazaar/products", fake)
    url = upload_r.json()["url"]

    with patch("cloudinary.uploader.destroy", return_value={"result": "ok"}):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r1 = await c.request("DELETE", "/storage/delete", json={"url": url})
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r2 = await c.request("DELETE", "/storage/delete", json={"url": url})

    assert r1.status_code == 200
    assert r2.status_code == 404


# ---------------------------------------------------------------------------
# Unitarios — _compress
# ---------------------------------------------------------------------------

async def test_compress_resizes_large_image():
    from app.services.cloudinary_service import _compress

    large = Image.new("RGB", (2400, 1800), color=(0, 128, 0))
    buf = io.BytesIO()
    large.save(buf, format="JPEG")

    result = _compress(buf.getvalue(), max_width=1200)

    out = Image.open(io.BytesIO(result))
    assert out.width == 1200
    assert out.height == 900


async def test_compress_keeps_small_image_size():
    from app.services.cloudinary_service import _compress

    small = Image.new("RGB", (400, 300), color=(0, 0, 255))
    buf = io.BytesIO()
    small.save(buf, format="JPEG")

    result = _compress(buf.getvalue(), max_width=1200)

    out = Image.open(io.BytesIO(result))
    assert out.width == 400


async def test_compress_converts_rgba_to_rgb():
    from app.services.cloudinary_service import _compress

    rgba = Image.new("RGBA", (100, 100), color=(255, 0, 0, 128))
    buf = io.BytesIO()
    rgba.save(buf, format="PNG")

    result = _compress(buf.getvalue())

    out = Image.open(io.BytesIO(result))
    assert out.mode == "RGB"


async def test_compress_converts_palette_to_rgb():
    from app.services.cloudinary_service import _compress

    palette = Image.new("P", (100, 100))
    buf = io.BytesIO()
    palette.save(buf, format="PNG")

    result = _compress(buf.getvalue())

    out = Image.open(io.BytesIO(result))
    assert out.mode == "RGB"

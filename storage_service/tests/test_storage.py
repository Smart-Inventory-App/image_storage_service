import io
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient
from PIL import Image

from app.main import app
from app.services.cloudinary_service import _compress


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_jpeg_bytes(width: int = 100, height: int = 100) -> bytes:
    img = Image.new("RGB", (width, height), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _fake_cloudinary_result(folder: str, name: str) -> dict:
    return {
        "secure_url": f"https://res.cloudinary.com/test/image/upload/{folder}/{name}.jpg",
        "public_id": f"{folder}/{name}",
    }


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
    fake = _fake_cloudinary_result("tpp/products", "abc")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await _upload(c, _make_jpeg_bytes(), "image/jpeg", "tpp/products", fake)

    assert r.status_code == 200
    assert r.json() == {"url": fake["secure_url"]}


async def test_upload_unregistered_folder_rejected():
    """Sólo se aceptan las carpetas de FOLDER_RULES: no hay regla por defecto."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/storage/upload",
            files={"file": ("photo.jpg", _make_jpeg_bytes(), "image/jpeg")},
            data={"folder": "tpp/general"},
        )
    assert r.status_code == 400
    assert "tpp/general" in r.json()["detail"]


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
                data={"folder": "tpp/products"},
            )
    assert r.status_code == 400
    assert "supera" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

async def test_delete_image_success():
    fake = _fake_cloudinary_result("tpp/products", "abc")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        upload_r = await _upload(c, _make_jpeg_bytes(), "image/jpeg", "tpp/products", fake)
    assert upload_r.status_code == 200
    url = upload_r.json()["url"]

    with patch("cloudinary.uploader.destroy", return_value={"result": "ok"}):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.request("DELETE", "/storage/delete", json={"url": url})

    assert r.status_code == 200
    assert r.json() == {"ok": True}


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
    fake = _fake_cloudinary_result("tpp/products", "webp_img")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await _upload(c, _make_jpeg_bytes(), "image/webp", "tpp/products", fake)
    assert r.status_code == 200
    assert r.json() == {"url": fake["secure_url"]}


# ---------------------------------------------------------------------------
# Upload — error de Cloudinary
# ---------------------------------------------------------------------------

async def test_upload_cloudinary_error_returns_500():
    with patch("cloudinary.uploader.upload", side_effect=Exception("timeout")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/storage/upload",
                files={"file": ("photo.jpg", _make_jpeg_bytes(), "image/jpeg")},
                data={"folder": "tpp/products"},
            )
    assert r.status_code == 500
    assert "timeout" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Delete — casos adicionales
# ---------------------------------------------------------------------------

async def test_delete_cloudinary_error_returns_500():
    fake = _fake_cloudinary_result("tpp/products", "err_img")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        upload_r = await _upload(c, _make_jpeg_bytes(), "image/jpeg", "tpp/products", fake)
    url = upload_r.json()["url"]

    with patch("cloudinary.uploader.destroy", return_value={"result": "error"}):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.request("DELETE", "/storage/delete", json={"url": url})
    assert r.status_code == 500


async def test_delete_twice_second_returns_404():
    """Después de borrar, un segundo intento con la misma URL devuelve 404."""
    fake = _fake_cloudinary_result("tpp/products", "double_del")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        upload_r = await _upload(c, _make_jpeg_bytes(), "image/jpeg", "tpp/products", fake)
    url = upload_r.json()["url"]

    with patch("cloudinary.uploader.destroy", return_value={"result": "ok"}):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r1 = await c.request("DELETE", "/storage/delete", json={"url": url})
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r2 = await c.request("DELETE", "/storage/delete", json={"url": url})

    assert r1.status_code == 200
    assert r2.status_code == 404


# ---------------------------------------------------------------------------
# Temp — subida efímera para OCR
# ---------------------------------------------------------------------------

async def _upload_temp(client, cloudinary_result):
    with patch("cloudinary.uploader.upload", return_value=cloudinary_result):
        return await client.post(
            "/storage/temp",
            files={"file": ("scan.jpg", _make_jpeg_bytes(), "image/jpeg")},
        )


async def test_upload_temp_returns_url_and_expiry():
    fake = _fake_cloudinary_result("tpp/ocr-temp", "scan1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await _upload_temp(c, fake)

    assert r.status_code == 200
    body = r.json()
    assert body["url"] == fake["secure_url"]
    assert body["ttl_seconds"] > 0
    assert body["expires_at"]


async def test_discard_temp_success():
    fake = _fake_cloudinary_result("tpp/ocr-temp", "scan2")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        url = (await _upload_temp(c, fake)).json()["url"]

    with patch("cloudinary.uploader.destroy", return_value={"result": "ok"}) as destroy:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.request("DELETE", "/storage/temp", json={"url": url})

    assert r.status_code == 200
    assert r.json() == {"ok": True}
    destroy.assert_called_once_with(fake["public_id"], resource_type="image")


async def test_discard_temp_rejects_persistent_image():
    """/temp no puede borrar imágenes de carpetas persistentes."""
    fake = _fake_cloudinary_result("tpp/products", "keep_me")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        url = (await _upload(c, _make_jpeg_bytes(), "image/jpeg", "tpp/products", fake)).json()["url"]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.request("DELETE", "/storage/temp", json={"url": url})

    assert r.status_code == 404


async def test_purge_temp_removes_only_expired():
    import app.routes.storage as storage_routes

    fake = _fake_cloudinary_result("tpp/ocr-temp", "stale")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await _upload_temp(c, fake)

    # TTL 0 ⇒ el recién subido ya está vencido.
    with patch.object(storage_routes.settings, "TEMP_UPLOAD_TTL_SECONDS", 0):
        with patch("cloudinary.uploader.destroy", return_value={"result": "ok"}):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                r = await c.post("/storage/temp/purge")

    assert r.status_code == 200
    assert r.json() == {"purged": 1}


async def test_purge_temp_keeps_fresh_uploads():
    fake = _fake_cloudinary_result("tpp/ocr-temp", "fresh")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await _upload_temp(c, fake)

    with patch("cloudinary.uploader.destroy", return_value={"result": "ok"}) as destroy:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/storage/temp/purge")

    assert r.json() == {"purged": 0}
    destroy.assert_not_called()


async def test_temp_upload_preserves_more_resolution_than_products():
    """La carpeta temporal comprime menos: el OCR necesita detalle."""
    from app.services.cloudinary_service import FOLDER_RULES, TEMP_OCR_FOLDER

    temp_rule = FOLDER_RULES[TEMP_OCR_FOLDER]
    assert temp_rule["max_width"] > 1200
    assert temp_rule["quality"] > 85


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


# ---------------------------------------------------------------------------
# Orientación EXIF
# ---------------------------------------------------------------------------

def _make_jpeg_with_orientation(orientation: int, width: int = 100, height: int = 50) -> bytes:
    img = Image.new("RGB", (width, height), color=(0, 128, 255))
    exif = Image.Exif()
    exif[0x0112] = orientation
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def _size_after_compress(contents: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(_compress(contents))).size


def test_compress_rotates_photos_taken_with_the_phone_on_its_side():
    # orientación 6 y 8: el celular estaba girado 90°; la foto debe quedar de pie (ancho y alto intercambiados)
    assert _size_after_compress(_make_jpeg_with_orientation(6)) == (50, 100)
    assert _size_after_compress(_make_jpeg_with_orientation(8)) == (50, 100)


def test_compress_flips_upside_down_photos_without_swapping_sides():
    assert _size_after_compress(_make_jpeg_with_orientation(3)) == (100, 50)


def test_compress_keeps_photos_that_are_already_upright():
    assert _size_after_compress(_make_jpeg_with_orientation(1)) == (100, 50)
    assert _size_after_compress(_make_jpeg_bytes(100, 50)) == (100, 50)


async def test_upload_sends_the_rotated_image_to_cloudinary():
    fake = _fake_cloudinary_result("tpp/products", "rot")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        with patch("cloudinary.uploader.upload", return_value=fake) as upload:
            r = await c.post(
                "/storage/upload",
                files={"file": ("file", _make_jpeg_with_orientation(6), "image/jpeg")},
                data={"folder": "tpp/products"},
            )

    assert r.status_code == 200
    sent = upload.call_args.args[0]
    assert Image.open(io.BytesIO(sent)).size == (50, 100)

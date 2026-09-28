"""Carpetas y rutas que test_storage.py no ejercita.

Cubre el cambio de prefijo `bazaar/` → `tpp/`: los nombres viejos se siguen
aceptando al subir y los registros viejos se siguen encontrando al descartar y
purgar, pero todo lo nuevo se guarda con el nombre actual.
"""
import io
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import select

from app.main import app
from app.models import MediaFile
from app.services import cloudinary_service


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (50, 50), color=(10, 20, 30)).save(buf, format="JPEG")
    return buf.getvalue()


def _fake(folder: str, name: str) -> dict:
    return {
        "secure_url": f"https://res.cloudinary.com/test/image/upload/{folder}/{name}.jpg",
        "public_id": f"{folder}/{name}",
    }


async def _stored_folders(session_factory) -> list[str]:
    async with session_factory() as session:
        return list((await session.execute(select(MediaFile.folder))).scalars())


async def _seed(session_factory, folder: str, name: str) -> str:
    """Registra un archivo como si lo hubiera subido una versión anterior."""
    fake = _fake(folder, name)
    async with session_factory() as session:
        session.add(MediaFile(url=fake["secure_url"], public_id=fake["public_id"], folder=folder))
        await session.commit()
    return fake["secure_url"]


# ---------------------------------------------------------------------------
# Nombres de carpeta
# ---------------------------------------------------------------------------

def test_resolve_folder_translates_only_legacy_names():
    assert cloudinary_service.resolve_folder("bazaar/products") == "tpp/products"
    assert cloudinary_service.resolve_folder("bazaar/ocr") == "tpp/ocr"
    assert cloudinary_service.resolve_folder("bazaar/ocr-temp") == "tpp/ocr-temp"
    assert cloudinary_service.resolve_folder("tpp/products") == "tpp/products"
    assert cloudinary_service.resolve_folder("otra/carpeta") == "otra/carpeta"


def test_folder_aliases_include_the_legacy_name():
    assert cloudinary_service.folder_aliases("tpp/ocr-temp") == ["tpp/ocr-temp", "bazaar/ocr-temp"]


def test_every_legacy_name_points_to_a_registered_folder():
    for current in cloudinary_service.LEGACY_FOLDERS.values():
        assert current in cloudinary_service.FOLDER_RULES


async def test_default_upload_goes_to_the_products_folder(setup_test_db):
    fake = _fake("tpp/products", "default")
    with patch("cloudinary.uploader.upload", return_value=fake) as upload:
        async with _client() as c:
            r = await c.post("/storage/upload", files={"file": ("p.jpg", _jpeg(), "image/jpeg")})

    assert r.status_code == 200
    assert upload.call_args.kwargs["folder"] == "tpp/products"
    assert await _stored_folders(setup_test_db) == ["tpp/products"]


async def test_legacy_folder_is_accepted_and_saved_under_the_new_name(setup_test_db):
    """Las versiones de la app sin actualizar mandan `bazaar/products`: tienen que seguir funcionando."""
    fake = _fake("tpp/products", "legacy")
    with patch("cloudinary.uploader.upload", return_value=fake) as upload:
        async with _client() as c:
            r = await c.post(
                "/storage/upload",
                files={"file": ("p.jpg", _jpeg(), "image/jpeg")},
                data={"folder": "bazaar/products"},
            )

    assert r.status_code == 200
    assert r.json() == {"url": fake["secure_url"]}
    assert upload.call_args.kwargs["folder"] == "tpp/products"
    assert await _stored_folders(setup_test_db) == ["tpp/products"]


async def test_content_that_is_not_an_image_is_a_client_error():
    """Declarar `image/jpeg` no alcanza: si Pillow no lo puede leer, es un 400."""
    with patch("cloudinary.uploader.upload") as upload:
        async with _client() as c:
            r = await c.post(
                "/storage/upload",
                files={"file": ("p.jpg", b"esto no es una imagen", "image/jpeg")},
            )

    assert r.status_code == 400
    assert "no es una imagen válida" in r.json()["detail"]
    upload.assert_not_called()


# ---------------------------------------------------------------------------
# POST /storage/ocr
# ---------------------------------------------------------------------------

async def test_ocr_upload_success(setup_test_db):
    fake = _fake("tpp/ocr", "ticket")
    with patch("cloudinary.uploader.upload", return_value=fake) as upload:
        async with _client() as c:
            r = await c.post("/storage/ocr", files={"file": ("t.jpg", _jpeg(), "image/jpeg")})

    assert r.status_code == 200
    assert r.json() == {"url": fake["secure_url"]}
    assert upload.call_args.kwargs["folder"] == "tpp/ocr"
    assert await _stored_folders(setup_test_db) == ["tpp/ocr"]


async def test_ocr_upload_rejects_unsupported_format():
    async with _client() as c:
        r = await c.post("/storage/ocr", files={"file": ("t.pdf", b"%PDF-1.4", "application/pdf")})

    assert r.status_code == 400
    assert "application/pdf" in r.json()["detail"]


async def test_ocr_upload_cloudinary_error_returns_500():
    with patch("cloudinary.uploader.upload", side_effect=Exception("timeout")):
        async with _client() as c:
            r = await c.post("/storage/ocr", files={"file": ("t.jpg", _jpeg(), "image/jpeg")})

    assert r.status_code == 500
    assert "timeout" in r.json()["detail"]


# ---------------------------------------------------------------------------
# /storage/temp
# ---------------------------------------------------------------------------

async def test_temp_upload_is_saved_in_the_temp_folder(setup_test_db):
    fake = _fake("tpp/ocr-temp", "scan")
    with patch("cloudinary.uploader.upload", return_value=fake) as upload:
        async with _client() as c:
            r = await c.post("/storage/temp", files={"file": ("s.jpg", _jpeg(), "image/jpeg")})

    assert r.status_code == 200
    assert upload.call_args.kwargs["folder"] == "tpp/ocr-temp"
    assert await _stored_folders(setup_test_db) == ["tpp/ocr-temp"]


async def test_temp_upload_rejects_unsupported_format():
    async with _client() as c:
        r = await c.post("/storage/temp", files={"file": ("s.gif", b"GIF89a", "image/gif")})

    assert r.status_code == 400
    assert "image/gif" in r.json()["detail"]


async def test_temp_upload_cloudinary_error_returns_500():
    with patch("cloudinary.uploader.upload", side_effect=Exception("sin conexión")):
        async with _client() as c:
            r = await c.post("/storage/temp", files={"file": ("s.jpg", _jpeg(), "image/jpeg")})

    assert r.status_code == 500
    assert "sin conexión" in r.json()["detail"]


async def test_discard_temp_not_found():
    async with _client() as c:
        r = await c.request(
            "DELETE", "/storage/temp", json={"url": "https://res.cloudinary.com/test/no-existe.jpg"}
        )

    assert r.status_code == 404


async def test_discard_temp_cloudinary_error_returns_500(setup_test_db):
    url = await _seed(setup_test_db, "tpp/ocr-temp", "falla")

    with patch("cloudinary.uploader.destroy", return_value={"result": "error"}):
        async with _client() as c:
            r = await c.request("DELETE", "/storage/temp", json={"url": url})

    assert r.status_code == 500
    # Si Cloudinary no lo borró, el registro se conserva para poder reintentar.
    assert await _stored_folders(setup_test_db) == ["tpp/ocr-temp"]


async def test_legacy_temp_record_can_still_be_discarded(setup_test_db):
    """Una temporal subida antes del cambio de prefijo se descarta igual."""
    url = await _seed(setup_test_db, "bazaar/ocr-temp", "vieja")

    with patch("cloudinary.uploader.destroy", return_value={"result": "ok"}) as destroy:
        async with _client() as c:
            r = await c.request("DELETE", "/storage/temp", json={"url": url})

    assert r.status_code == 200
    destroy.assert_called_once_with("bazaar/ocr-temp/vieja", resource_type="image")
    assert await _stored_folders(setup_test_db) == []


async def test_purge_includes_legacy_temp_records(setup_test_db):
    import app.routes.storage as storage_routes

    await _seed(setup_test_db, "bazaar/ocr-temp", "huerfana")
    await _seed(setup_test_db, "tpp/products", "persistente")

    with patch.object(storage_routes.settings, "TEMP_UPLOAD_TTL_SECONDS", 0):
        with patch("cloudinary.uploader.destroy", return_value={"result": "ok"}) as destroy:
            async with _client() as c:
                r = await c.post("/storage/temp/purge")

    assert r.json() == {"purged": 1}
    destroy.assert_called_once_with("bazaar/ocr-temp/huerfana", resource_type="image")
    assert await _stored_folders(setup_test_db) == ["tpp/products"]


async def test_purge_keeps_records_cloudinary_could_not_delete(setup_test_db):
    import app.routes.storage as storage_routes

    await _seed(setup_test_db, "tpp/ocr-temp", "trabada")

    with patch.object(storage_routes.settings, "TEMP_UPLOAD_TTL_SECONDS", 0):
        with patch("cloudinary.uploader.destroy", return_value={"result": "error"}):
            async with _client() as c:
                r = await c.post("/storage/temp/purge")

    assert r.status_code == 200
    assert r.json() == {"purged": 0}
    assert await _stored_folders(setup_test_db) == ["tpp/ocr-temp"]


# ---------------------------------------------------------------------------
# delete_file
# ---------------------------------------------------------------------------

def test_delete_file_tolerates_an_already_missing_file():
    """`not found` no es un error: el objetivo de borrar ya se cumplió."""
    with patch("cloudinary.uploader.destroy", return_value={"result": "not found"}) as destroy:
        cloudinary_service.delete_file("tpp/products/ya-no-esta")

    destroy.assert_called_once_with("tpp/products/ya-no-esta", resource_type="image")

"""Piezas de infraestructura que el resto de los tests reemplaza.

conftest.py sustituye la validación del token y la sesión de base para poder
ejercitar las rutas; acá se prueban las implementaciones reales.
"""
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

import app.main as main_module
from app.core.config import settings
from app.core.security import get_current_user
from app.db import get_db


def _credentials(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


# ---------------------------------------------------------------------------
# get_current_user
# ---------------------------------------------------------------------------

def test_valid_token_returns_its_payload():
    token = jwt.encode({"sub": "user-1", "email": "a@b.com"}, settings.JWT_SECRET, algorithm="HS256")

    payload = get_current_user(_credentials(token))

    assert payload["sub"] == "user-1"
    assert payload["email"] == "a@b.com"


def test_token_without_sub_is_rejected():
    token = jwt.encode({"email": "a@b.com"}, settings.JWT_SECRET, algorithm="HS256")

    with pytest.raises(HTTPException) as exc:
        get_current_user(_credentials(token))

    assert exc.value.status_code == 401
    assert exc.value.detail == "Token inválido"


def test_token_signed_with_another_secret_is_rejected():
    token = jwt.encode({"sub": "user-1"}, "otro-secreto", algorithm="HS256")

    with pytest.raises(HTTPException) as exc:
        get_current_user(_credentials(token))

    assert exc.value.status_code == 401
    assert exc.value.detail == "Token inválido o expirado"


def test_malformed_token_is_rejected():
    with pytest.raises(HTTPException) as exc:
        get_current_user(_credentials("no-es-un-jwt"))

    assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# get_db y arranque
# ---------------------------------------------------------------------------

async def test_get_db_yields_a_session():
    gen = get_db()
    session = await gen.__anext__()

    assert isinstance(session, AsyncSession)

    await gen.aclose()


async def test_startup_creates_the_media_files_table(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    # El lifespan usa el engine del módulo: se reemplaza para no tocar storage.db.
    monkeypatch.setattr(main_module, "engine", engine)

    async with main_module.lifespan(main_module.app):
        async with engine.connect() as conn:
            tables = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())

    await engine.dispose()
    assert "media_files" in tables

import os

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

os.environ.setdefault("CLOUDINARY_CLOUD_NAME", "test_cloud")
os.environ.setdefault("CLOUDINARY_API_KEY", "test_key")
os.environ.setdefault("CLOUDINARY_API_SECRET", "test_secret")
os.environ.setdefault("JWT_SECRET", "test-secret")

from app.core.security import get_current_user  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.main import app
from app.models import MediaFile  # noqa: F401

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(autouse=True)
async def setup_test_db():
    engine = create_async_engine(TEST_DATABASE_URL)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    # La validación del JWT se testea en el servicio Auth; acá se inyecta un
    # usuario ya autenticado para poder ejercitar las rutas protegidas.
    app.dependency_overrides[get_current_user] = lambda: {"sub": "test-user"}
    yield session_factory
    app.dependency_overrides.clear()
    await engine.dispose()

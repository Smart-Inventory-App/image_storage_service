from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import Base, engine
from app.models import MediaFile  # noqa: F401 — registra el modelo en Base.metadata
from app.routes.storage import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title="Storage Service", version="1.0.0", lifespan=lifespan)
app.include_router(router, prefix="/storage")

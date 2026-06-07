import logging

import cloudinary.api
from fastapi import APIRouter, Depends, Form, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import MediaFile
from app.services import cloudinary_service

logger = logging.getLogger(__name__)

router = APIRouter()


class DeleteRequest(BaseModel):
    url: str


@router.post("/upload")
async def upload(
    file: UploadFile = File(...),
    folder: str = Form(default="bazaar/general"),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await cloudinary_service.upload_file(file, folder)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Error al subir archivo: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error al subir archivo: {exc}")

    media = MediaFile(
        url=result["url"],
        public_id=result["public_id"],
        resource_type=result["resource_type"],
        folder=folder,
    )
    db.add(media)
    await db.commit()

    return {"url": result["url"]}


@router.delete("/delete")
async def delete(body: DeleteRequest, db: AsyncSession = Depends(get_db)):
    row = await db.execute(select(MediaFile).where(MediaFile.url == body.url))
    media = row.scalar_one_or_none()

    if media is None:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")

    try:
        cloudinary_service.delete_file(media.public_id, resource_type=media.resource_type)
    except RuntimeError as exc:
        logger.error("Error al eliminar archivo: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error al eliminar archivo: {exc}")

    await db.delete(media)
    await db.commit()

    return {"ok": True}


@router.get("/livez")
async def livez():
    return {"status": "ok"}


@router.get("/readyz")
async def readyz():
    try:
        cloudinary.api.ping()
        return {"status": "ok"}
    except Exception as exc:
        logger.error("Cloudinary no disponible: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=503,
            detail="Cloudinary no disponible",
        )

import logging
from datetime import datetime, timedelta, timezone

import cloudinary.api
from fastapi import APIRouter, Depends, Form, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import get_current_user
from app.db import get_db
from app.models import MediaFile
from app.services import cloudinary_service
from app.services.cloudinary_service import TEMP_OCR_FOLDER

logger = logging.getLogger(__name__)

router = APIRouter()


class DeleteRequest(BaseModel):
    url: str


async def _discard(url: str, db: AsyncSession, folder: str | None = None) -> None:
    """Borra el archivo de Cloudinary y su registro interno.

    Si se pasa `folder`, sólo se aceptan URLs de esa carpeta: evita que un
    endpoint acotado (p. ej. /temp) pueda eliminar imágenes persistentes.
    """
    query = select(MediaFile).where(MediaFile.url == url)
    if folder is not None:
        query = query.where(MediaFile.folder == folder)

    row = await db.execute(query)
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


@router.post("/upload")
async def upload(
    file: UploadFile = File(...),
    folder: str = Form(default="tpp/products"),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
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


@router.post("/ocr")
async def upload_ocr(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    try:
        result = await cloudinary_service.upload_file(file, "tpp/ocr")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Error al subir imagen OCR: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error al subir imagen OCR: {exc}")

    media = MediaFile(
        url=result["url"],
        public_id=result["public_id"],
        resource_type=result["resource_type"],
        folder="tpp/ocr",
    )
    db.add(media)
    await db.commit()

    return {"url": result["url"]}


@router.post("/temp")
async def upload_temp(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """Sube una imagen efímera para que el ocr_service le aplique sus filtros.

    El consumidor debe llamar a `DELETE /storage/temp` al terminar. Si no lo
    hace (caída, timeout), `POST /storage/temp/purge` la elimina al expirar.
    """
    try:
        result = await cloudinary_service.upload_file(file, TEMP_OCR_FOLDER)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Error al subir imagen temporal: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error al subir imagen temporal: {exc}")

    media = MediaFile(
        url=result["url"],
        public_id=result["public_id"],
        resource_type=result["resource_type"],
        folder=TEMP_OCR_FOLDER,
    )
    db.add(media)
    await db.commit()
    await db.refresh(media)

    ttl = settings.TEMP_UPLOAD_TTL_SECONDS
    return {
        "url": media.url,
        "expires_at": (media.created_at + timedelta(seconds=ttl)).isoformat(),
        "ttl_seconds": ttl,
    }


@router.delete("/temp")
async def discard_temp(
    body: DeleteRequest,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """Descarta una imagen temporal una vez procesada por el OCR."""
    await _discard(body.url, db, folder=TEMP_OCR_FOLDER)
    return {"ok": True}


@router.post("/temp/purge")
async def purge_temp(
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """Elimina las imágenes temporales vencidas que nadie descartó."""
    # `created_at` viene de `func.now()` (UTC naive): se compara en el mismo formato.
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now_utc - timedelta(seconds=settings.TEMP_UPLOAD_TTL_SECONDS)

    rows = await db.execute(
        select(MediaFile).where(
            MediaFile.folder == TEMP_OCR_FOLDER,
            MediaFile.created_at < cutoff,
        )
    )

    purged = 0
    for media in rows.scalars().all():
        try:
            cloudinary_service.delete_file(media.public_id, resource_type=media.resource_type)
        except RuntimeError as exc:
            logger.warning("No se pudo purgar %s: %s", media.public_id, exc)
            continue
        await db.delete(media)
        purged += 1

    await db.commit()

    logger.info("Purga de temporales: %d archivo(s) eliminado(s)", purged)
    return {"purged": purged}


@router.delete("/delete")
async def delete(
    body: DeleteRequest,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    await _discard(body.url, db)
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
        raise HTTPException(status_code=503, detail="Cloudinary no disponible")

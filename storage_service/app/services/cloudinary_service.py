import io
import logging

import cloudinary
import cloudinary.uploader
from fastapi import UploadFile
from PIL import Image

from app.core.config import settings

logger = logging.getLogger(__name__)

cloudinary.config(
    cloud_name=settings.CLOUDINARY_CLOUD_NAME,
    api_key=settings.CLOUDINARY_API_KEY,
    api_secret=settings.CLOUDINARY_API_SECRET,
)

IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}

# Carpeta de trabajo del OCR: las imágenes viven acá sólo mientras el
# ocr_service las procesa y se descartan al terminar (ver /storage/temp).
TEMP_OCR_FOLDER = "bazaar/ocr-temp"

FOLDER_RULES: dict[str, dict] = {
    "bazaar/products": {
        "allowed_types": IMAGE_TYPES,
        "max_mb_key": "MAX_IMAGE_PRODUCT_MB",
        "resource_type": "image",
        "label": "imágenes de producto",
    },
    "bazaar/ocr": {
        "allowed_types": IMAGE_TYPES,
        "max_mb_key": "MAX_IMAGE_OCR_MB",
        "resource_type": "image",
        "label": "imágenes para OCR",
    },
    TEMP_OCR_FOLDER: {
        "allowed_types": IMAGE_TYPES,
        "max_mb_key": "MAX_IMAGE_OCR_MB",
        "resource_type": "image",
        "label": "imágenes temporales para OCR",
        # El OCR aplica su propio pipeline de filtros sobre esta imagen: se
        # preserva más resolución y calidad que en las carpetas persistentes,
        # porque comprimir de más degrada el reconocimiento de caracteres.
        "max_width": 2000,
        "quality": 95,
    },
}

DEFAULT_MAX_WIDTH = 1200
DEFAULT_QUALITY = 85


def _get_rule(folder: str) -> dict:
    rule = FOLDER_RULES.get(folder)
    if rule is None:
        valid = ", ".join(sorted(FOLDER_RULES))
        raise ValueError(f"Carpeta '{folder}' no permitida. Carpetas válidas: {valid}")
    return {**rule, "max_mb": getattr(settings, rule["max_mb_key"])}


async def upload_file(file: UploadFile, folder: str) -> dict:
    rule = _get_rule(folder)

    if file.content_type not in rule["allowed_types"]:
        accepted = ", ".join(sorted(rule["allowed_types"]))
        raise ValueError(
            f"Formato '{file.content_type}' no permitido para {rule['label']}. "
            f"Formatos aceptados: {accepted}"
        )

    contents = await file.read()

    max_bytes = rule["max_mb"] * 1024 * 1024
    if len(contents) > max_bytes:
        raise ValueError(
            f"El archivo supera el límite de {rule['max_mb']} MB "
            f"para {rule['label']} (carpeta '{folder}')"
        )

    data = _compress(
        contents,
        max_width=rule.get("max_width", DEFAULT_MAX_WIDTH),
        quality=rule.get("quality", DEFAULT_QUALITY),
    )

    result = cloudinary.uploader.upload(data, folder=folder, resource_type="image")

    url = result["secure_url"]
    public_id = result["public_id"]

    logger.info("Archivo subido: public_id=%s url=%s", public_id, url)

    return {"url": url, "public_id": public_id, "resource_type": "image"}


def delete_file(public_id: str, resource_type: str = "image") -> None:
    result = cloudinary.uploader.destroy(public_id, resource_type=resource_type)

    if result.get("result") not in ("ok", "not found"):
        raise RuntimeError(
            f"No se pudo eliminar '{public_id}' "
            f"(resource_type={resource_type}): {result}"
        )

    logger.info("Archivo eliminado: public_id=%s resultado=%s", public_id, result.get("result"))


def _compress(
    contents: bytes,
    max_width: int = DEFAULT_MAX_WIDTH,
    quality: int = DEFAULT_QUALITY,
) -> bytes:
    image = Image.open(io.BytesIO(contents))

    if image.width > max_width:
        ratio = max_width / image.width
        new_height = int(image.height * ratio)
        image = image.resize((max_width, new_height), Image.LANCZOS)

    if image.mode in ("RGBA", "P"):
        image = image.convert("RGB")

    output = io.BytesIO()
    image.save(output, format="JPEG", quality=quality, optimize=True)
    return output.getvalue()

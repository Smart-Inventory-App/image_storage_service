# image_storage_service — Smart Inventory

[![codecov](https://codecov.io/gh/bazaar-tpg/external_storage_service/graph/badge.svg?token=MW6HMDN0F9)](https://codecov.io/gh/bazaar-tpg/external_storage_service)

Microservicio de almacenamiento de imágenes. Sube y elimina archivos en Cloudinary, y persiste la relación `url → public_id` en SQLite para que los servicios consumidores solo operen con URLs públicas.

---

## Stack

- Python 3.11 + FastAPI
- Cloudinary (almacenamiento externo)
- Pillow (compresión de imágenes antes de subir)
- SQLAlchemy async + SQLite (aiosqlite)
- JWT HS256 — valida tokens del servicio Auth

---

## Endpoints

### `POST /storage/upload`

Sube una imagen de producto a Cloudinary.

**Auth:** `Authorization: Bearer <token>`  
**Body:** `multipart/form-data`

| Campo | Tipo | Requerido | Default |
|-------|------|-----------|---------|
| `file` | archivo | sí | — |
| `folder` | string | no | `bazaar/products` |

**Respuesta 200:**
```json
{ "url": "https://res.cloudinary.com/..." }
```

**Errores:**
- `400` — formato no soportado o archivo demasiado grande
- `401` — token inválido o ausente
- `500` — error al comunicarse con Cloudinary

---

### `POST /storage/ocr`

Sube una imagen para procesamiento OCR (escaneo de productos).

**Auth:** `Authorization: Bearer <token>`  
**Body:** `multipart/form-data` — campo `file`

**Respuesta 200:**
```json
{ "url": "https://res.cloudinary.com/..." }
```

---

### `DELETE /storage/delete`

Elimina un archivo de Cloudinary y borra su registro interno.

**Auth:** `Authorization: Bearer <token>`  
**Body:** `application/json`

```json
{ "url": "https://res.cloudinary.com/..." }
```

**Respuesta 200:** `{ "ok": true }`

**Errores:**
- `401` — token inválido o ausente
- `404` — URL no registrada en la base de datos
- `500` — error al comunicarse con Cloudinary

---

### `GET /storage/livez`

Liveness probe. Sin dependencias externas.

**Respuesta 200:** `{ "status": "ok" }`

---

### `GET /storage/readyz`

Readiness probe. Hace ping a Cloudinary.

**Respuesta 200:** `{ "status": "ok" }`  
**Respuesta 503:** `{ "status": "error", "detail": "Cloudinary no disponible" }`

---

## Límites por tipo de imagen

| Carpeta | Límite |
|---------|--------|
| `bazaar/products` | 10 MB |
| `bazaar/ocr` | 10 MB |

Las imágenes se comprimen automáticamente (máx. 1200 px de ancho, JPEG quality 85) antes de subirse a Cloudinary.

---

## Configuración

Crear `.env` a partir de `.env.example`:

```env
CLOUDINARY_CLOUD_NAME=
CLOUDINARY_API_KEY=
CLOUDINARY_API_SECRET=

# JWT (mismo secret que el servicio Auth)
JWT_SECRET=change-this-secret-in-production
JWT_ALGORITHM=HS256

# Límites en MB
MAX_IMAGE_PRODUCT_MB=10
MAX_IMAGE_OCR_MB=10

# DB interna
DATABASE_URL=sqlite+aiosqlite:///./storage.db

# Servicios autorizados (* = cualquiera con token válido)
ALLOWED_SERVICES=*
```

---

## Setup local

```bash
cd storage_service

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

uvicorn app.main:app --reload --port 8004
```

Swagger disponible en `http://localhost:8004/docs`.

---

## Docker

```bash
docker-compose up -d
```

El servicio queda disponible en `http://localhost:8004`.

---

## Tests

```bash
cd storage_service
pytest tests/ -v
```

Los tests usan base de datos en memoria y mockean Cloudinary — no requieren credenciales.

---

## Estructura

```
image_storage_service/
├── storage_service/
│   ├── app/
│   │   ├── core/
│   │   │   ├── config.py           # Settings (pydantic-settings)
│   │   │   └── security.py         # Validación JWT
│   │   ├── routes/
│   │   │   └── storage.py          # /upload, /ocr, /delete, /livez, /readyz
│   │   ├── services/
│   │   │   └── cloudinary_service.py  # Upload/delete en Cloudinary + compresión
│   │   ├── db.py                   # Sesión async SQLAlchemy
│   │   ├── models.py               # MediaFile (url, public_id, resource_type)
│   │   └── main.py
│   └── tests/
├── docker-compose.yml
└── .env.example
```

---

## Flujo de integración

```
App_backend
  │  POST /storage/upload  (file + folder, Bearer token)
  ▼
image_storage_service  ──►  Cloudinary
  │  { "url": "https://res.cloudinary.com/..." }
  ▼
App_backend  guarda imagen_url en la tabla products
```

### Ejemplo desde otro servicio (Python)

```python
import httpx

async def upload_product_image(file_bytes: bytes, filename: str, token: str) -> str:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "http://storage_service:8004/storage/upload",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": (filename, file_bytes, "image/jpeg")},
            data={"folder": "bazaar/products"},
            timeout=30.0,
        )
        r.raise_for_status()
        return r.json()["url"]

async def delete_product_image(url: str, token: str) -> None:
    async with httpx.AsyncClient() as client:
        r = await client.delete(
            "http://storage_service:8004/storage/delete",
            headers={"Authorization": f"Bearer {token}"},
            json={"url": url},
            timeout=10.0,
        )
        r.raise_for_status()
```

> Los servicios consumidores solo guardan la **URL**. El `public_id` de Cloudinary es un detalle interno de este servicio.

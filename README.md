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

### `POST /storage/temp`

Sube una imagen **efímera** para que `ocr_service` le aplique sus filtros y la descarte al terminar. A diferencia de `/storage/ocr`, esta imagen no está pensada para conservarse: la foto que el usuario saca para escanear un producto no debe quedar almacenada.

Se comprime menos que las carpetas persistentes (hasta 2000 px de ancho, JPEG quality 95): reducir de más degrada el reconocimiento de caracteres.

**Auth:** `Authorization: Bearer <token>`  
**Body:** `multipart/form-data` — campo `file`

**Respuesta 200:**
```json
{
  "url": "https://res.cloudinary.com/.../bazaar/ocr-temp/abc.jpg",
  "expires_at": "2026-07-29T20:29:03",
  "ttl_seconds": 900
}
```

El consumidor **debe** llamar a `DELETE /storage/temp` al terminar. `expires_at` indica hasta cuándo la imagen sobrevive si no lo hace.

---

### `DELETE /storage/temp`

Descarta una imagen temporal ya procesada.

**Auth:** `Authorization: Bearer <token>`  
**Body:** `application/json` — `{ "url": "https://res.cloudinary.com/..." }`

**Respuesta 200:** `{ "ok": true }`

**Errores:**
- `401` — token inválido o ausente
- `404` — la URL no existe **o no pertenece a la carpeta temporal** (este endpoint no puede eliminar
  imágenes persistentes)

---

### `POST /storage/temp/purge`

Red de seguridad: elimina las imágenes temporales vencidas que nadie descartó (por ejemplo si el worker del OCR se cayó a mitad del procesamiento). Pensado para un cron o para llamarlo desde el backoffice.

**Auth:** `Authorization: Bearer <token>`

**Respuesta 200:** `{ "purged": 3 }`

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

| Carpeta | Endpoint | Límite | Compresión | Persistencia |
|---------|----------|--------|------------|--------------|
| `bazaar/products` | `/storage/upload` | 10 MB | 1200 px · q85 | permanente |
| `bazaar/ocr` | `/storage/ocr` | 10 MB | 1200 px · q85 | permanente |
| `bazaar/ocr-temp` | `/storage/temp` | 10 MB | 2000 px · q95 | efímera (TTL 15 min) |

Las imágenes se comprimen automáticamente antes de subirse a Cloudinary. La carpeta temporal preserva más resolución y calidad porque el OCR aplica su propio pipeline de filtros sobre ella.

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

# Vida útil de las imágenes de /storage/temp (segundos)
TEMP_UPLOAD_TTL_SECONDS=900

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
│   │   │   └── storage.py          # /upload, /ocr, /temp, /delete, /livez, /readyz
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

### Flujo Temporal (Especifico para el OCR)

La imagen que se escanea no se conserva: existe sólo mientras el OCR la procesa.

```
ocr_service
  │  1) POST /storage/temp  (file, Bearer token)
  ▼
image_storage_service  ──►  Cloudinary (bazaar/ocr-temp)
  │  { "url": ..., "expires_at": ... }
  ▼
ocr_service  descarga la URL, aplica sus filtros (OpenCV) y reconoce el texto
  │  2) DELETE /storage/temp  ← al terminar, salga bien o mal
  ▼
image_storage_service  borra el archivo en Cloudinary y su registro interno

  Si el paso 2 nunca llega (worker caído), POST /storage/temp/purge
  elimina las temporales vencidas.
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

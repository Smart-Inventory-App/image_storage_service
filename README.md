# storage_service

Microservicio de Bazaar encargado de subir y eliminar archivos multimedia en Cloudinary. Persiste la relación `url → public_id` en una base de datos SQLite local, de modo que los servicios consumidores solo necesitan guardar y operar con la URL pública.

# Coverage: 
[![codecov](https://codecov.io/gh/bazaar-tpg/external_storage_service/graph/badge.svg?token=MW6HMDN0F9)](https://codecov.io/gh/bazaar-tpg/external_storage_service)

---

## Stack

- Python 3.11 + FastAPI
- Cloudinary (almacenamiento externo)
- Pillow (compresión de imágenes)
- SQLAlchemy async + SQLite
- Docker

---

## Reglas por tipo de media

| Carpeta (`folder`) | Tipos aceptados | Límite |
|---|---|---|
| `bazaar/profiles` | JPEG, PNG, WebP | 5 MB |
| `bazaar/products` | JPEG, PNG, WebP | 10 MB |
| `bazaar/videos` | MP4, WebM | 50 MB |

Las imágenes se comprimen automáticamente (máx. 1200 px de ancho, JPEG quality 85) antes de subirse. Los videos se suben sin modificar. Cualquier otro formato es rechazado con un error descriptivo.

---

## Endpoints

### `POST /storage/upload`

Sube un archivo a Cloudinary y persiste la URL internamente.

**Body:** `multipart/form-data`

| Campo | Tipo | Requerido | Default |
|---|---|---|---|
| `file` | archivo | sí | — |
| `folder` | string | no | `bazaar/general` |

**Respuesta 200:**
```json
{ "url": "https://res.cloudinary.com/..." }
```

**Errores:**
- `400` — formato no soportado, tipo incompatible con la carpeta, o archivo demasiado grande
- `500` — error al comunicarse con Cloudinary

---

### `DELETE /storage/delete`

Elimina un archivo de Cloudinary y borra el registro interno. Recibe la URL pública — el servicio resuelve el `public_id` internamente.

**Body:** `application/json`

| Campo | Tipo | Requerido |
|---|---|---|
| `url` | string | sí |

**Respuesta 200:**
```json
{ "ok": true }
```

**Errores:**
- `404` — URL no encontrada en la base de datos
- `500` — error al comunicarse con Cloudinary

---

### `GET /storage/livez`

Liveness probe. Sin llamadas externas.

**Respuesta 200:** `{ "status": "ok" }`

---

### `GET /storage/readyz`

Readiness probe. Hace ping a Cloudinary.

**Respuesta 200:** `{ "status": "ok" }`
**Respuesta 503:** `{ "status": "error", "detail": "Cloudinary no disponible" }`

---

## Configuración

Crear `.env` a partir de `.env.example`:

```env
CLOUDINARY_CLOUD_NAME=
CLOUDINARY_API_KEY=
CLOUDINARY_API_SECRET=
DATABASE_URL=sqlite+aiosqlite:///./storage.db
MAX_IMAGE_PROFILE_MB=5
MAX_IMAGE_PRODUCT_MB=10
MAX_VIDEO_MB=50
```

> Para producción reemplazar `DATABASE_URL` con una conexión PostgreSQL:
> `postgresql+asyncpg://user:pass@host/dbname`

---

## Correr en local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

uvicorn app.main:app --reload --port 8000
```

Documentación interactiva disponible en `http://localhost:8000/docs`.

---

## Tests

```bash
pytest tests/ -v
```

Los tests usan una base de datos en memoria y mockean Cloudinary — no requieren credenciales ni conexión.

---

## Docker

```bash
docker build -t storage_service .
docker run --env-file .env -p 8004:8000 storage_service
```

---

## Flujo de integración

```
Cliente
  │  POST /products (con imagen)
  ▼
product_service
  │  POST /storage/upload  (file + folder)
  ▼
storage_service  ──►  Cloudinary
  │  { "url": "https://res.cloudinary.com/..." }
  ▼
product_service  guarda la URL en su BD
  │  responde al cliente
  ▼
Cliente
```

### Ejemplo desde otro servicio (Python)

```python
import httpx

async def upload_product_image(file_bytes: bytes, filename: str) -> str:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "http://storage_service:8000/storage/upload",
            files={"file": (filename, file_bytes, "image/jpeg")},
            data={"folder": "bazaar/products"},
            timeout=30.0,
        )
        r.raise_for_status()
        return r.json()["url"]  # guardar esta URL en la BD del servicio

async def delete_product_image(url: str) -> None:
    async with httpx.AsyncClient() as client:
        r = await client.request(
            "DELETE",
            "http://storage_service:8000/storage/delete",
            json={"url": url},
            timeout=10.0,
        )
        r.raise_for_status()
```

> Los servicios consumidores solo guardan la **URL**. El `public_id` de Cloudinary es un detalle interno de `storage_service`.

---

## docker-compose (agregar al compose raíz)

```yaml
storage_service:
  build: ./storage_service
  ports:
    - "8004:8000"
  env_file:
    - ./storage_service/.env
  networks:
    - bazaar-network
```

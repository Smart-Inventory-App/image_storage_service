from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    CLOUDINARY_CLOUD_NAME: str
    CLOUDINARY_API_KEY: str
    CLOUDINARY_API_SECRET: str
    ALLOWED_SERVICES: str = "*"
    DATABASE_URL: str = "sqlite+aiosqlite:///./storage.db"

    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    MAX_IMAGE_PRODUCT_MB: int = 10
    MAX_IMAGE_OCR_MB: int = 10
    TEMP_UPLOAD_TTL_SECONDS: int = 900


settings = Settings()

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    CLOUDINARY_CLOUD_NAME: str
    CLOUDINARY_API_KEY: str
    CLOUDINARY_API_SECRET: str
    ALLOWED_SERVICES: str = "*"  
    DATABASE_URL: str = "sqlite+aiosqlite:///./storage.db"
    MAX_IMAGE_PRODUCT_MB: int = 10
    MAX_IMAGE_OCR_MB: int = 10


settings = Settings()

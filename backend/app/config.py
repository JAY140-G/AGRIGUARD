from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]

class Settings(BaseSettings):
    database_url: str = 'sqlite:///'+str(ROOT/'.data/agriscan.db')
    redis_url: str = ''
    storage_dir: str = str(ROOT/'.data/images')
    storage_backend: str = 'local'
    s3_bucket: str = ''
    s3_endpoint: str | None = None
    environment: str = 'development'
    cookie_secure: bool = False
    allowed_origins: str = 'http://localhost:5173,http://127.0.0.1:5173'
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

settings = Settings()

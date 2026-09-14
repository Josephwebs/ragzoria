from functools import lru_cache
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
PROJECT_ROOT = Path(__file__).resolve().parents[3]

class Settings(BaseSettings):
    ollama_model: str = "llama3:latest"
    embedding_model: str = "bge-m3"
    ollama_base_url: str = "http://localhost:11434"
    ollama_timeout: int = 120
    data_dir: Path = PROJECT_ROOT / "data"
    faiss_persist_dir: Path = PROJECT_ROOT / "backend/storage/faiss_simple"
    top_k: int = Field(default=2, ge=1, le=10)
    chunk_size: int = 350
    chunk_overlap: int = 50
    rag_debug: bool = False
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

@lru_cache
def get_settings():
    return Settings()

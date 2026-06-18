from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # LLM providers
    anthropic_api_key: str
    openai_api_key: str

    # Supabase
    supabase_url: str
    supabase_service_key: str

    # App
    app_env: str = "development"
    app_port: int = 8000
    log_level: str = "INFO"

    # RAG
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    rag_top_k: int = 3
    rag_min_similarity: float = 0.75
    chunk_size: int = 300
    chunk_overlap: int = 50

    # Models
    classify_model: str = "claude-haiku-4-5-20251001"
    reply_model: str = "claude-haiku-4-5-20251001"
    vision_model: str = "gpt-4o"
    fallback_model: str = "gpt-4o-mini"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    """Cached settings — loaded once at startup, reused everywhere."""
    return Settings()

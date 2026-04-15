from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from typing import Literal


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")
    
    # API Keys
    openai_api_key: str
    tavily_api_key: str
    
    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    qdrant_collection_name: str = "crag_documents"
    
    # OpenAI Models
    embedding_model: str = "text-embedding-3-small"
    llm_model: str = "gpt-4o-mini"
    embedding_dimensions: int = 1536
    
    # CRAG Settings
    crag_relevance_threshold: float = 0.7
    crag_ambiguous_threshold: float = 0.5
    
    # Retrieval
    top_k_results: int = 5

    # Hybrid Search Settings
    hybrid_search_enabled: bool = True
    sparse_vector_enabled: bool = True
    rrf_k: int = 60  # RRF fusion parameter

    # Reranking Settings
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    reranker_initial_top_k: int = 3
    reranking_enabled_by_default: bool = False

    # Reranking Backend Selection
    reranker_backend: Literal["local", "voyage"] = "local"
    voyage_api_key: str | None = None
    voyage_model: str = "rerank-2.5"

    # Upload
    upload_dir: str = "uploads"
    max_file_size: int = 50 * 1024 * 1024  # 50MB


@lru_cache
def get_settings() -> Settings:
    return Settings()

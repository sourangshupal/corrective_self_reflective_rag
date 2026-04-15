from pydantic import BaseModel, Field
from typing import Literal, Optional
from datetime import datetime


# ============= Request Models =============

class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    mode: Literal["standard", "crag"] = "standard"
    search_mode: Literal["dense", "sparse", "hybrid"] = Field(
        default="hybrid",
        description="Search mode: dense (semantic), sparse (keyword), or hybrid (RRF fusion)"
    )
    top_k: int = Field(default=5, ge=1, le=20)
    enable_reranking: bool = Field(
        default=False,
        description="Use cross-encoder reranking for improved precision"
    )


# ============= Response Models =============

class UploadResponse(BaseModel):
    file_id: str
    filename: str
    file_type: str
    chunks_created: int
    status: str
    message: str


# ============= Chunk Models =============

class ChunkMetadata(BaseModel):
    chunk_id: str
    source_file: str
    file_type: str
    page_number: Optional[int] = None
    chunk_index: int
    total_chunks: int
    doc_item_type: Optional[str] = None
    parent_heading: Optional[str] = None
    hierarchy_level: Optional[int] = None
    chunk_method: str = "hybrid"
    token_count: int
    char_count: int
    content_preview: str
    keywords: list[str] = []
    created_at: datetime
    processed_at: datetime


class RetrievedChunk(BaseModel):
    content: str
    metadata: ChunkMetadata
    score: float


# ============= CRAG Models =============

class CRAGEvaluation(BaseModel):
    relevance_score: float
    relevance_label: Literal["relevant", "ambiguous", "irrelevant"]
    confidence: float
    evaluation_method: str = "llm_grader"
    needs_web_search: bool
    evaluated_at: datetime


class CRAGResult(BaseModel):
    used_web_search: bool
    evaluation: CRAGEvaluation
    retrieved_chunks: list[RetrievedChunk]
    web_results: Optional[list[dict]] = None


# ============= Query Response =============

class QueryResponse(BaseModel):
    query: str
    answer: str
    mode: str
    search_mode: Literal["dense", "sparse", "hybrid"]
    sources: list[RetrievedChunk]
    crag_details: Optional[CRAGResult] = None
    response_time_ms: float
    reranking_used: bool = False
    initial_retrieval_count: Optional[int] = None

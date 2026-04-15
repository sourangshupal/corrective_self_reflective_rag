from app.services.vector_store import VectorStore
from app.services.embedding_service import EmbeddingService
from app.models import RetrievedChunk, ChunkMetadata
from app.config import get_settings
from loguru import logger


class RetrievalService:
    def __init__(self):
        self.settings = get_settings()
        self.vector_store = VectorStore()
        self.embedding_service = EmbeddingService()

    def retrieve(
        self,
        query: str,
        top_k: int = None,
        search_mode: str = "hybrid"
    ) -> list[RetrievedChunk]:
        """
        Retrieve relevant chunks for a query.

        Args:
            query: User's query
            top_k: Number of chunks to retrieve
            search_mode: Search mode - "dense", "sparse", or "hybrid"

        Returns:
            List of retrieved chunks
        """

        if top_k is None:
            top_k = self.settings.top_k_results

        query_vector = self.embedding_service.embed_text(query)

        results = self.vector_store.search(
            query_vector=query_vector,
            query_text=query,
            top_k=top_k,
            mode=search_mode
        )

        retrieved_chunks = self._convert_to_chunks(results)
        logger.info(f"Retrieved {len(retrieved_chunks)} chunks for query (mode: {search_mode})")

        return retrieved_chunks

    def _convert_to_chunks(self, results: list[dict]) -> list[RetrievedChunk]:
        """Convert vector store results to RetrievedChunk models"""
        chunks = []
        for result in results:
            chunk = RetrievedChunk(
                content=result["content"],
                metadata=ChunkMetadata(**result["metadata"]),
                score=result["score"]
            )
            chunks.append(chunk)
        return chunks


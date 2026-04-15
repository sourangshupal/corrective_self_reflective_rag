from fastapi import APIRouter, HTTPException
from app.models import QueryRequest, QueryResponse
from app.core.retrieval import RetrievalService
from app.services.crag import CRAGService
from app.services.llm_service import LLMService
from app.services.reranking import RerankingService
from app.config import get_settings
from loguru import logger
import time

router = APIRouter(prefix="/query", tags=["query"])

settings = get_settings()
retrieval_service = RetrievalService()
crag_service = CRAGService()
llm_service = LLMService()
reranking_service = RerankingService()


@router.post("/", response_model=QueryResponse)
async def query_documents(request: QueryRequest):
    """Query documents with different RAG modes"""

    start_time = time.time()

    initial_retrieval_count = None

    try:
        # Determine initial top_k based on reranking flag
        initial_top_k = request.top_k
        if request.enable_reranking:
            initial_top_k = settings.reranker_initial_top_k

        # Stage 1: Retrieve
        retrieved_chunks = retrieval_service.retrieve(
            query=request.query,
            top_k=initial_top_k,
            search_mode=request.search_mode
        )

        initial_retrieval_count = len(retrieved_chunks)

        if not retrieved_chunks:
            raise HTTPException(
                status_code=404,
                detail="No relevant documents found. Please upload documents first."
            )

        # Stage 2: Rerank (if enabled)
        if request.enable_reranking:
            retrieved_chunks = reranking_service.rerank(
                query=request.query,
                retrieved_chunks=retrieved_chunks,
                top_k=request.top_k
            )

        answer = None
        crag_details = None

        # Execute based on mode
        if request.mode == "standard":
            # Standard RAG
            context = "\n\n".join([chunk.content for chunk in retrieved_chunks])
            prompt = f"Query: {request.query}\n\nContext:\n{context}\n\nAnswer:"
            answer = llm_service.generate(prompt)

        elif request.mode == "crag":
            # Corrective RAG
            crag_result = crag_service.execute_crag(request.query, retrieved_chunks)
            answer = crag_service.generate_answer_with_crag(request.query, crag_result)
            crag_details = crag_result

        response_time = (time.time() - start_time) * 1000

        return QueryResponse(
            query=request.query,
            answer=answer,
            mode=request.mode,
            search_mode=request.search_mode,
            sources=retrieved_chunks,
            crag_details=crag_details,
            response_time_ms=response_time,
            reranking_used=request.enable_reranking,
            initial_retrieval_count=initial_retrieval_count
        )
        
    except Exception as e:
        logger.error(f"Query error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/compare")
async def compare_modes(query: str, top_k: int = 5):
    """Compare all three RAG modes side-by-side"""
    
    results = {}
    
    for mode in ["standard", "crag"]:
        try:
            request = QueryRequest(query=query, mode=mode, top_k=top_k)
            result = await query_documents(request)
            results[mode] = result.model_dump()
        except Exception as e:
            results[mode] = {"error": str(e)}
    
    return {
        "query": query,
        "comparison": results
    }

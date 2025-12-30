"""Query endpoint for searching knowledge base"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from stache_ai.rag.pipeline import get_pipeline

logger = logging.getLogger(__name__)

router = APIRouter()


class QueryRequest(BaseModel):
    """Request model for query endpoint"""
    query: str
    top_k: int = 20
    synthesize: bool = True  # If False, return search results without LLM
    namespace: str | None = None
    rerank: bool = True  # Rerank results for better relevance and deduplication
    model: str | None = None  # Override default LLM model for synthesis
    filter: dict[str, Any] | None = None  # Metadata filter (e.g., {"source": "meeting notes"})


@router.post("/query")
async def query_knowledge(request: QueryRequest):
    """
    Query your knowledge base with natural language

    - synthesize=True: Returns AI-synthesized answer from relevant chunks
    - synthesize=False: Returns raw search results (faster, no LLM cost)
    - namespace: Optional namespace to search within
    - model: Optional model ID to use for synthesis (e.g., us.anthropic.claude-3-5-sonnet-20241022-v2:0)
    - filter: Optional metadata filter (e.g., {"source": "meeting notes"})
    """
    try:
        pipeline = get_pipeline()

        result = await pipeline.query(
            question=request.query,
            top_k=request.top_k,
            synthesize=request.synthesize,
            namespace=request.namespace,
            rerank=request.rerank,
            model=request.model,
            filter=request.filter
        )

        return result
    except Exception as e:
        logger.error(f"Query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

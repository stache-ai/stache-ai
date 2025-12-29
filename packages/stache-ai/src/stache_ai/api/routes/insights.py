"""Insights endpoints for creating and searching user notes"""

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from stache_ai.models.insight import InsightCreate
from stache_ai.rag.pipeline import get_pipeline

logger = logging.getLogger(__name__)

router = APIRouter()


class InsightSearchRequest(BaseModel):
    """Request model for searching insights"""
    query: str = Field(..., min_length=1, description="Search query")
    namespace: str = Field(..., description="Namespace to search within")
    top_k: int = Field(10, ge=1, le=100, description="Maximum results to return")


class InsightSearchResult(BaseModel):
    """Individual search result"""
    id: str = Field(..., description="Insight ID")
    content: str = Field(..., description="Insight content")
    similarity_score: float = Field(..., description="Similarity score (0-1)")
    tags: list[str] | None = Field(None, description="Associated tags")


class InsightSearchResponse(BaseModel):
    """Response model for search results"""
    results: list[InsightSearchResult] = Field(..., description="Search results")
    total: int = Field(..., description="Total results found")


@router.post("/insights", response_model=dict)
async def create_insight(request: InsightCreate):
    """
    Create a new insight (user note with semantic search capability)

    The insight will be indexed and immediately searchable.
    Optional tags help with categorization and discovery.
    """
    try:
        pipeline = get_pipeline()

        result = pipeline.create_insight(
            content=request.content,
            namespace=request.namespace,
            tags=request.tags
        )

        return {
            "success": True,
            "message": "Insight created successfully",
            **result
        }
    except Exception as e:
        logger.error(f"Failed to create insight: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create insight: {str(e)}"
        )


@router.get("/insights/search", response_model=InsightSearchResponse)
async def search_insights(
    query: str = Query(..., min_length=1, description="Search query"),
    namespace: str = Query(..., description="Namespace to search within"),
    top_k: int = Query(10, ge=1, le=100, description="Maximum results to return")
):
    """
    Search insights using semantic search

    Returns the most relevant insights based on semantic similarity to the query.
    Results are scoped to the specified namespace.
    """
    try:
        pipeline = get_pipeline()

        results = pipeline.search_insights(
            query=query,
            namespace=namespace,
            top_k=top_k
        )

        # Transform results into the expected format
        formatted_results = []
        for item in results.get("insights", []):
            formatted_results.append(InsightSearchResult(
                id=item.get("id", ""),
                content=item.get("text", ""),
                similarity_score=item.get("score", 0.0),
                tags=item.get("metadata", {}).get("tags", None)
            ))

        return InsightSearchResponse(
            results=formatted_results,
            total=len(formatted_results)
        )
    except Exception as e:
        logger.error(f"Failed to search insights: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to search insights: {str(e)}"
        )


@router.delete("/insights/{insight_id}")
async def delete_insight(
    insight_id: str,
    namespace: str = Query(..., description="Namespace containing the insight")
):
    """
    Delete an insight by ID

    Removes the insight from the knowledge base permanently.
    The namespace must match the insight's namespace for security.
    """
    try:
        pipeline = get_pipeline()

        result = pipeline.delete_insight(
            insight_id=insight_id,
            namespace=namespace
        )

        return {
            "success": True,
            "message": f"Insight {insight_id} deleted successfully",
            **result
        }
    except Exception as e:
        logger.error(f"Failed to delete insight {insight_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete insight: {str(e)}"
        )

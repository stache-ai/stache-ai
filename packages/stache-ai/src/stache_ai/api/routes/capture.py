"""Capture endpoint for quick note-taking"""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from stache_ai.rag.pipeline import get_pipeline

logger = logging.getLogger(__name__)

router = APIRouter()


class CaptureRequest(BaseModel):
    """Request model for capture endpoint"""
    text: str
    metadata: dict | None = None
    chunking_strategy: str = "recursive"
    namespace: str | None = None
    prepend_metadata: list[str] | None = None  # Metadata keys to prepend to chunks
    suggest_organization: bool = Field(
        False,
        description="Use AI to suggest filename and namespace based on content"
    )
    apply_suggestions: bool = Field(
        False,
        description="Automatically apply suggested filename and namespace (requires suggest_organization=true)"
    )


@router.post("/capture")
async def capture_thought(request: CaptureRequest):
    """
    Capture a quick thought or note

    This endpoint is optimized for quick note-taking:
    - Small text snippets (thoughts, ideas, notes)
    - Automatically chunked and indexed
    - Immediately searchable
    - Optional namespace for multi-user/multi-project isolation
    - Optional AI-powered organization suggestions
    """
    try:
        pipeline = get_pipeline()

        # Prepare metadata with organization flags if requested
        metadata = request.metadata or {}
        if request.suggest_organization:
            metadata["_suggest_organization"] = True
        if request.apply_suggestions:
            metadata["_apply_suggestions"] = True

        result = await pipeline.ingest_text(
            text=request.text,
            metadata=metadata,
            chunking_strategy=request.chunking_strategy,
            namespace=request.namespace,
            prepend_metadata=request.prepend_metadata
        )

        return {
            "success": True,
            "message": "Thought captured successfully",
            **result
        }
    except Exception as e:
        logger.error(f"Capture failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

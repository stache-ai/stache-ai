"""Capture endpoint for quick note-taking.

Thin shim over the unified IngestionService so /api/capture and /api/ingest
share one ingestion code path (down-payment on collapsing the sync paths).
The legacy response shape is preserved for the existing frontend.
"""

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from stache_ai.api import auth
from stache_ai.config import settings
from stache_ai.identity import ForbiddenError
from stache_ai.ingestion import JobStatus
from stache_ai.ingestion.factory import get_ingestion_service
from stache_ai.sanitize import strip_reserved_metadata

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
async def capture_thought(request: CaptureRequest, http_request: Request):
    """
    Capture a quick thought or note

    This endpoint is optimized for quick note-taking:
    - Small text snippets (thoughts, ideas, notes)
    - Automatically chunked and indexed
    - Immediately searchable
    - Optional namespace for multi-user/multi-project isolation
    - Optional AI-powered organization suggestions
    """
    principal = auth.principal(http_request)
    namespace = request.namespace or settings.default_namespace
    # S1 enforcement (before the broad try so a denial is a 403, not a 500).
    auth.authorize(http_request, "capture", {"namespace": namespace})

    try:
        # Carry organization flags + prepend list as metadata for the pipeline.
        metadata = strip_reserved_metadata(request.metadata)
        if request.suggest_organization:
            metadata["_suggest_organization"] = True
        if request.apply_suggestions:
            metadata["_apply_suggestions"] = True
        if request.prepend_metadata:
            metadata["_prepend_metadata"] = request.prepend_metadata

        service = get_ingestion_service()
        job = await service.submit(
            namespace=namespace,
            content_type="text",
            requested_by=principal,
            source="web",
            metadata=metadata,
            text=request.text,
            chunking_strategy=request.chunking_strategy,
            wait=True,
            wait_timeout=settings.ingest_wait_default_timeout,
        )

        if job.status == JobStatus.FAILED:
            logger.error(f"Capture failed: {job.error_detail}")
            raise HTTPException(status_code=500, detail="Internal server error")

        action = "skipped" if job.status == JobStatus.SKIPPED else "ingested_new"
        return {
            "success": True,
            "message": "Thought captured successfully",
            "doc_id": job.doc_id,
            "chunks_created": job.chunks_created,
            "namespace": job.namespace,
            "action": action,
            "job_id": job.job_id,
            "status": job.status.value,
        }
    except HTTPException:
        raise
    except ForbiddenError:
        raise
    except Exception as e:
        logger.error(f"Capture failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

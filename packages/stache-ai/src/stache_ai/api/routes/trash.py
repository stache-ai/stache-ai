"""Trash and restore API endpoints."""
from typing import Any
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from stache_ai.api import auth
from stache_ai.identity import ForbiddenError
from stache_ai.middleware.context import RequestContext
from stache_ai.rag.pipeline import get_pipeline

router = APIRouter()


class RestoreRequest(BaseModel):
    doc_id: str
    namespace: str = "default"
    deleted_at_ms: int = Field(..., description="Timestamp from trash entry")


class PermanentDeleteRequest(BaseModel):
    doc_id: str
    namespace: str = "default"
    deleted_at_ms: int = Field(..., description="Timestamp from trash entry")
    filename: str | None = Field(None, description="Filename from trash entry (for correct trash PK)")


@router.get("/", response_model=dict[str, Any])
async def list_trash_documents(
    http_request: Request,
    namespace: str | None = None,
    limit: int = 50,
    next_key: str | None = None,
) -> dict[str, Any]:
    """List documents in trash (30-day retention)."""
    # S1 enforcement
    auth.authorize(http_request, "read_document",
                   {"namespace": namespace} if namespace else None)

    pipeline = get_pipeline()

    if not pipeline.document_index_provider:
        raise HTTPException(status_code=501, detail="Document index not available")

    try:
        context = RequestContext.from_fastapi_request(http_request, namespace or "")
        result = pipeline.list_trash(
            namespace=namespace,
            limit=limit,
            next_key=next_key,
            context=context,
        )
        return result
    except ForbiddenError:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list trash: {e}")


@router.post("/restore", response_model=dict[str, Any])
async def restore_document(
    request: RestoreRequest,
    http_request: Request,
) -> dict[str, Any]:
    """Restore document from trash."""
    # S1 enforcement
    auth.authorize(http_request, "restore_document", {"namespace": request.namespace})

    pipeline = get_pipeline()

    if not pipeline.document_index_provider:
        raise HTTPException(status_code=501, detail="Document index not available")

    try:
        context = RequestContext.from_fastapi_request(http_request, request.namespace)
        # Pipeline restores the index entry and reactivates vector status
        result = pipeline.restore_document(
            doc_id=request.doc_id,
            namespace=request.namespace,
            deleted_at_ms=request.deleted_at_ms,
            context=context,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to restore: {e}")


@router.post("/permanent", response_model=dict[str, Any])
async def permanently_delete_document(
    request: PermanentDeleteRequest,
    http_request: Request,
) -> dict[str, Any]:
    """Permanently delete document from trash (irreversible)."""
    # S1 enforcement
    auth.authorize(http_request, "purge_trash", {"namespace": request.namespace})

    pipeline = get_pipeline()

    if not pipeline.document_index_provider:
        raise HTTPException(status_code=501, detail="Document index not available")

    try:
        context = RequestContext.from_fastapi_request(http_request, request.namespace)
        result = pipeline.purge_trash_entry(
            doc_id=request.doc_id,
            namespace=request.namespace,
            deleted_at_ms=request.deleted_at_ms,
            deleted_by="api",
            filename=request.filename,  # Use trash entry filename for correct PK
            context=context,
        )

        return {
            "status": "cleanup_pending",
            "doc_id": result["doc_id"],
            "namespace": result["namespace"],
            "chunk_count": result["chunk_count"],
            "cleanup_job_id": result["cleanup_job_id"],
            "message": "Vector cleanup job created. Deletion will complete shortly.",
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete: {e}")

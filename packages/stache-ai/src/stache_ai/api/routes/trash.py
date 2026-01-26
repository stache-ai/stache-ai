"""Trash and restore API endpoints."""
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

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


@router.get("/", response_model=dict[str, Any])
async def list_trash_documents(
    namespace: str | None = None,
    limit: int = 50,
    next_key: str | None = None,
) -> dict[str, Any]:
    """List documents in trash (30-day retention)."""
    pipeline = get_pipeline()

    if not pipeline.document_index_provider:
        raise HTTPException(status_code=501, detail="Document index not available")

    try:
        result = pipeline.document_index_provider.list_trash(
            namespace=namespace,
            limit=limit,
            next_key=next_key,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list trash: {e}")


@router.post("/restore", response_model=dict[str, Any])
async def restore_document(
    request: RestoreRequest,
) -> dict[str, Any]:
    """Restore document from trash."""
    pipeline = get_pipeline()

    if not pipeline.document_index_provider:
        raise HTTPException(status_code=501, detail="Document index not available")

    try:
        result = pipeline.document_index_provider.restore_document(
            doc_id=request.doc_id,
            namespace=request.namespace,
            deleted_at_ms=request.deleted_at_ms,
        )

        # Restore vector status to active
        chunk_ids = result.get("chunk_ids", [])
        if chunk_ids and hasattr(pipeline.vectordb_provider, "update_status"):
            try:
                pipeline.vectordb_provider.update_status(chunk_ids, request.namespace, "active")
            except Exception as e:
                # Log but don't fail - document is already restored
                import logging
                logging.getLogger(__name__).warning(f"Failed to restore vector status: {e}")

        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to restore: {e}")


@router.post("/permanent", response_model=dict[str, Any])
async def permanently_delete_document(
    request: PermanentDeleteRequest,
) -> dict[str, Any]:
    """Permanently delete document from trash (irreversible)."""
    pipeline = get_pipeline()

    if not pipeline.document_index_provider:
        raise HTTPException(status_code=501, detail="Document index not available")

    try:
        result = pipeline.document_index_provider.permanently_delete_document(
            doc_id=request.doc_id,
            namespace=request.namespace,
            deleted_at_ms=request.deleted_at_ms,
            deleted_by="api",
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete: {e}")

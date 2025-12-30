"""Pending queue endpoints for reviewing OCR'd documents before upload"""

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from stache_ai.config import settings
from stache_ai.loaders import load_document
from stache_ai.rag.pipeline import get_pipeline

logger = logging.getLogger(__name__)

router = APIRouter()


class PendingItem(BaseModel):
    """Pending item metadata"""
    id: str
    original_filename: str
    suggested_filename: str
    suggested_namespace: str
    extracted_text: str
    full_text_length: int
    created_at: str


class ApproveRequest(BaseModel):
    """Request to approve a pending item"""
    filename: str
    namespace: str
    metadata: dict | None = None
    chunking_strategy: str = "recursive"
    prepend_metadata: list[str] | None = None


def get_queue_dir() -> Path:
    """Get the queue directory path"""
    return Path(settings.queue_dir)


@router.get("/pending")
async def list_pending() -> list[PendingItem]:
    """List all pending items in the queue"""
    queue_dir = get_queue_dir()

    if not queue_dir.exists():
        return []

    items = []
    for json_file in queue_dir.glob("*.json"):
        try:
            with open(json_file) as f:
                data = json.load(f)
                items.append(PendingItem(**data))
        except Exception as e:
            logger.warning(f"Failed to read {json_file}: {e}")
            continue

    # Sort by created_at descending (newest first)
    items.sort(key=lambda x: x.created_at, reverse=True)
    return items


@router.get("/pending/{item_id}")
async def get_pending(item_id: str) -> PendingItem:
    """Get a specific pending item"""
    queue_dir = get_queue_dir()
    json_path = queue_dir / f"{item_id}.json"

    if not json_path.exists():
        raise HTTPException(status_code=404, detail="Pending item not found")

    with open(json_path) as f:
        data = json.load(f)

    return PendingItem(**data)


@router.get("/pending/{item_id}/thumbnail")
async def get_thumbnail(item_id: str):
    """Get the thumbnail image for a pending item"""
    queue_dir = get_queue_dir()
    thumb_path = queue_dir / f"{item_id}.jpg"

    if not thumb_path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found")

    return FileResponse(thumb_path, media_type="image/jpeg")


@router.get("/pending/{item_id}/pdf")
async def get_pdf(item_id: str):
    """Get the PDF file for a pending item"""
    queue_dir = get_queue_dir()
    pdf_path = queue_dir / f"{item_id}.pdf"

    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF not found")

    return FileResponse(pdf_path, media_type="application/pdf")


@router.post("/pending/{item_id}/approve")
async def approve_pending(item_id: str, request: ApproveRequest):
    """
    Approve a pending item and upload to stache

    This ingests the document with the provided metadata and removes it from the queue.
    """
    queue_dir = get_queue_dir()
    json_path = queue_dir / f"{item_id}.json"
    pdf_path = queue_dir / f"{item_id}.pdf"
    thumb_path = queue_dir / f"{item_id}.jpg"

    if not json_path.exists() or not pdf_path.exists():
        raise HTTPException(status_code=404, detail="Pending item not found")

    try:
        # Load the PDF document
        text = load_document(str(pdf_path), f"{request.filename}.pdf")

        # Prepare metadata
        metadata = request.metadata or {}
        metadata["filename"] = f"{request.filename}.pdf"

        # Ingest into pipeline
        pipeline = get_pipeline()
        result = await pipeline.ingest_text(
            text=text,
            metadata=metadata,
            chunking_strategy=request.chunking_strategy,
            namespace=request.namespace,
            prepend_metadata=request.prepend_metadata
        )

        logger.info(f"Approved and ingested: {request.filename} -> {request.namespace}")

        # Move PDF to processed directory (optional - for archiving)
        processed_dir = Path(settings.queue_dir).parent / "processed" / request.namespace.replace("/", "_")
        processed_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        archive_name = f"{request.filename}_{timestamp}.pdf"
        shutil.move(str(pdf_path), str(processed_dir / archive_name))

        # Clean up queue files
        json_path.unlink()
        if thumb_path.exists():
            thumb_path.unlink()

        return {
            "success": True,
            "filename": request.filename,
            "namespace": request.namespace,
            **result
        }

    except Exception as e:
        logger.error(f"Failed to approve {item_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/pending/{item_id}")
async def delete_pending(item_id: str):
    """
    Delete a pending item without uploading

    This removes the item from the queue entirely.
    """
    queue_dir = get_queue_dir()
    json_path = queue_dir / f"{item_id}.json"
    pdf_path = queue_dir / f"{item_id}.pdf"
    thumb_path = queue_dir / f"{item_id}.jpg"

    if not json_path.exists():
        raise HTTPException(status_code=404, detail="Pending item not found")

    # Remove all files
    deleted = []
    for path in [json_path, pdf_path, thumb_path]:
        if path.exists():
            path.unlink()
            deleted.append(path.name)

    logger.info(f"Deleted pending item: {item_id}")

    return {
        "success": True,
        "deleted": deleted
    }

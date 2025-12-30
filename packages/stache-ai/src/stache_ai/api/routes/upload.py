"""Upload endpoint for importing documents"""

import logging
import os
import tempfile

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from stache_ai.rag.pipeline import get_pipeline

logger = logging.getLogger(__name__)

router = APIRouter()


class BatchUploadResult(BaseModel):
    """Result for a single file in batch upload"""
    filename: str
    success: bool
    error: str | None = None
    chunks_created: int | None = None
    doc_id: str | None = None


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    chunking_strategy: str = Form("auto"),
    metadata: dict | None = Form(None),
    namespace: str | None = Form(None),
    prepend_metadata: str | None = Form(None)
):
    """
    Upload and ingest a document with automatic format detection.

    Supported formats:
    - Text: .txt, .md
    - Documents: .pdf, .docx, .pptx, .xlsx
    - Ebooks: .epub
    - Transcripts: .vtt, .srt

    Chunking strategy:
    - "auto" (default): Automatically selects best strategy based on file type
      - DOCX/PDF/PPTX/XLSX/EPUB -> hierarchical (preserves headings)
      - MD/Markdown -> markdown
      - VTT/SRT -> transcript
      - TXT -> recursive
    - "hierarchical": Uses Docling for structure-aware chunking
    - "recursive", "markdown", "semantic", "character", "transcript": Explicit strategies

    Optional namespace for multi-user/multi-project isolation

    prepend_metadata: Comma-separated list of metadata keys to prepend to chunks.
                      This embeds metadata into the vector for better semantic search.
                      Example: "speaker,topic" with metadata {"speaker": "Dr. Anderson", "topic": "Faith"}
                      will prepend "Speaker: Dr. Anderson\nTopic: Faith\n\n" to each chunk.
    """
    try:
        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as temp_file:
            content = await file.read()
            temp_file.write(content)
            temp_path = temp_file.name

        try:
            # Parse prepend_metadata if provided
            prepend_keys = None
            if prepend_metadata:
                prepend_keys = [k.strip() for k in prepend_metadata.split(",") if k.strip()]

            # Use file-based ingestion (supports hierarchical chunking)
            pipeline = get_pipeline()
            result = await pipeline.ingest_file(
                file_path=temp_path,
                metadata={**(metadata or {}), "filename": file.filename},
                chunking_strategy=chunking_strategy,
                namespace=namespace,
                prepend_metadata=prepend_keys
            )

            return {
                "success": True,
                "filename": file.filename,
                **result
            }
        finally:
            # Clean up temp file
            os.unlink(temp_path)

    except Exception as e:
        logger.error(f"Upload failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload/batch")
async def batch_upload_documents(
    files: list[UploadFile] = File(...),
    chunking_strategy: str = Form("auto"),
    namespace: str | None = Form(None),
    metadata: str | None = Form(None),
    prepend_metadata: str | None = Form(None),
    skip_errors: bool = Form(True)
):
    """
    Upload multiple documents at once with automatic format detection.

    Args:
        files: List of files to upload
        chunking_strategy: Chunking strategy. Use "auto" to select based on file type.
                          - "auto" (default): Auto-selects per file
                          - "hierarchical": Structure-aware (DOCX/PDF/PPTX)
                          - "recursive", "markdown", "transcript", etc.
        namespace: Target namespace for all files
        metadata: JSON string of metadata to apply to all files
        prepend_metadata: Comma-separated metadata keys to prepend
        skip_errors: If True, continue on errors; if False, stop on first error

    Returns:
        Results for each file with success/failure status
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    # Parse metadata JSON if provided
    import json
    meta_dict = {}
    if metadata:
        try:
            meta_dict = json.loads(metadata)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid metadata JSON")

    # Parse prepend_metadata if provided
    prepend_keys = None
    if prepend_metadata:
        prepend_keys = [k.strip() for k in prepend_metadata.split(",") if k.strip()]

    pipeline = get_pipeline()
    results: list[BatchUploadResult] = []
    total_chunks = 0

    for file in files:
        temp_path = None
        try:
            # Save uploaded file temporarily
            suffix = os.path.splitext(file.filename)[1] if file.filename else ""
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                content = await file.read()
                temp_file.write(content)
                temp_path = temp_file.name

            # Use file-based ingestion with auto strategy selection
            file_metadata = {**meta_dict, "filename": file.filename}
            result = await pipeline.ingest_file(
                file_path=temp_path,
                metadata=file_metadata,
                chunking_strategy=chunking_strategy,
                namespace=namespace,
                prepend_metadata=prepend_keys
            )

            results.append(BatchUploadResult(
                filename=file.filename,
                success=True,
                chunks_created=result["chunks_created"],
                doc_id=result["doc_id"]
            ))
            total_chunks += result["chunks_created"]

            logger.info(f"Batch upload: {file.filename} - {result['chunks_created']} chunks (strategy: {result.get('chunking_strategy', 'unknown')})")

        except Exception as e:
            logger.error(f"Batch upload failed for {file.filename}: {e}")
            results.append(BatchUploadResult(
                filename=file.filename,
                success=False,
                error=str(e)
            ))

            if not skip_errors:
                # Return partial results on first error
                return {
                    "success": False,
                    "message": f"Stopped on error: {e}",
                    "results": [r.model_dump() for r in results],
                    "total_files": len(results),
                    "successful": sum(1 for r in results if r.success),
                    "failed": sum(1 for r in results if not r.success),
                    "total_chunks": total_chunks,
                    "namespace": namespace
                }

        finally:
            # Clean up temp file
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)

    successful = sum(1 for r in results if r.success)
    failed = sum(1 for r in results if not r.success)

    return {
        "success": failed == 0,
        "message": f"Uploaded {successful}/{len(files)} files successfully",
        "results": [r.model_dump() for r in results],
        "total_files": len(files),
        "successful": successful,
        "failed": failed,
        "total_chunks": total_chunks,
        "namespace": namespace
    }

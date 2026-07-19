"""Document management endpoints"""

import logging
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field

from stache_ai.api import auth
from stache_ai.identity import ForbiddenError, LimitExceededError
from stache_ai.middleware.context import RequestContext
from stache_ai.rag.pipeline import get_pipeline

logger = logging.getLogger(__name__)

router = APIRouter()


def _presign_download_enabled() -> bool:
    """Whether the configured blob store can presign original downloads.

    A per-request constant: the download endpoint and ``has_original`` both key
    off the ``presign_download`` capability the active blob store advertises
    (the inline/null tiers advertise none, so originals are never downloadable).
    """
    try:
        from stache_ai.ingestion.factory import get_ingestion_service
        return "presign_download" in get_ingestion_service().blobstore.capabilities
    except ForbiddenError:
        raise
    except LimitExceededError:
        raise
    except Exception:
        return False


def _reconstructed_text(chunks: list[dict], pipeline, context) -> str:
    """Best clean reconstruction of a document's text from its chunks.

    Prefers the full text stored at ingest (``text_blob_key`` on the record):
    joining the chunks would DUPLICATE every ``chunk_overlap`` region and inject
    ``\\n\\n`` breaks. Falls back to the chunk join only when there is no stored
    text (older documents, direct-pipeline ingests, or an inline blob tier), and
    on any fetch failure -- never a 500.
    """
    join = "\n\n".join(c.get("text", "") for c in chunks)
    # The stored text blob is the WHOLE document; serving it is only faithful for
    # a full-document fetch. A subset request (fewer chunks) or a multi-doc
    # request must use the join, which returns exactly the chunks asked for --
    # otherwise a subset would balloon to the whole doc and a multi-doc request
    # would silently collapse to one doc's full text.
    doc_ids = {c.get("doc_id") for c in chunks}
    if len(doc_ids) != 1 or None in doc_ids:
        return join
    doc_id = next(iter(doc_ids))
    namespace = next(
        (c.get("namespace") for c in chunks if c.get("doc_id") == doc_id), "default")
    try:
        doc = pipeline.get_document_record(doc_id, namespace, context=context)
        text_key = (doc or {}).get("text_blob_key")
        if not text_key:
            return join
        # Faithful full-document fetch only: the requested chunks must be exactly
        # the document's chunks. Otherwise fall back to the join.
        chunk_count = (doc or {}).get("chunk_count")
        if chunk_count is None or len(chunks) != chunk_count:
            return join
        from stache_ai.ingestion.factory import get_ingestion_service
        data, _ = get_ingestion_service().blobstore.get(text_key)
        return data.decode("utf-8")
    except ForbiddenError:
        raise
    except LimitExceededError:
        raise
    except Exception:
        logger.warning(
            "Clean reconstructed_text unavailable for %s; falling back to the "
            "chunk join", doc_id, exc_info=True)
        return join


@router.get("/documents")
async def list_documents(
    http_request: Request,
    namespace: str | None = Query(None, description="Optional namespace filter"),
    extension: str | None = Query(None, description="Filter by file extension (e.g., 'pdf', 'txt')"),
    orphaned: bool = Query(False, description="Show only chunks without doc_id (legacy data)"),
    use_summaries: bool = Query(True, description="Use fast summary-based listing (set False for legacy scan)"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of documents to return"),
    next_key: str | None = Query(None, description="Pagination token from previous response")
):
    """
    List all unique documents in the knowledge base.

    Now uses the document index provider for efficient listing with pagination support.
    Falls back to summary-based listing for backward compatibility.

    Returns doc_id, filename, created_at, chunk count, namespace, and headings.

    Optional filters:
    - namespace: Filter by namespace
    - extension: Filter by file extension (e.g., 'pdf', 'txt', 'md')
    - orphaned: If true, show chunks that don't have a doc_id (pre-UUID data)
    - use_summaries: If true (default), use fast summary-based listing
    - limit: Maximum documents per page (default 100, max 1000)
    - next_key: Pagination token from previous response for loading more results
    """
    # S1 enforcement (before the broad try so a denial is a 403, not a 500).
    # "read_document" deliberately unifies the document/trash/namespace-document
    # read surfaces: they are all same-scope reads of stored content, so a
    # policy author grants one read op rather than a verb per listing route.
    auth.authorize(http_request, "read_document",
                   {"namespace": namespace} if namespace else None)

    try:
        pipeline = get_pipeline()
        vectordb = pipeline.vectordb_provider
        context = RequestContext.from_fastapi_request(http_request, namespace or "")

        # Handle orphaned chunks separately (requires full scan, Qdrant only)
        if orphaned:
            return await _list_orphaned_chunks(vectordb, namespace, context)

        # Try to use document index provider for listing (provider-agnostic)
        if pipeline.document_index_provider and use_summaries:
            try:
                # Parse next_key if provided (pagination)
                last_evaluated_key = None
                if next_key:
                    import json
                    try:
                        last_evaluated_key = json.loads(next_key)
                    except (json.JSONDecodeError, ValueError):
                        logger.warning(f"Invalid next_key format: {next_key}")

                # Query document index via the pipeline (context-aware)
                result = pipeline.list_documents(
                    namespace=namespace,
                    limit=limit,
                    last_evaluated_key=last_evaluated_key,
                    context=context
                )

                documents = result.get("documents", [])

                # Apply extension filter if provided
                if extension:
                    ext_filter = extension.lower().lstrip('.')
                    documents = [
                        doc for doc in documents
                        if doc.get("filename") and doc["filename"].lower().endswith(f'.{ext_filter}')
                    ]

                # Flag which documents have a downloadable retained original.
                presign_enabled = _presign_download_enabled()
                for doc in documents:
                    doc["has_original"] = bool(presign_enabled and doc.get("blob_key"))

                # Prepare response with same format as before
                response = {
                    "documents": documents,
                    "count": len(documents),
                    "source": "document_index"
                }

                # Add pagination token if available
                if result.get("next_key"):
                    import json
                    response["next_key"] = json.dumps(result["next_key"])

                return response

            except ForbiddenError:
                raise
            except LimitExceededError:
                raise
            except Exception as e:
                logger.warning(f"Document index provider error, falling back to summary search: {e}")
                # Fall through to summary-based listing

        # Use summary-based listing (provider-agnostic, backward compatible)
        if use_summaries:
            # Build filter for document summaries
            filter_dict = {"_type": "document_summary"}
            if namespace:
                filter_dict["namespace"] = namespace

            # Normalize extension filter
            ext_filter = None
            if extension:
                ext_filter = extension.lower().lstrip('.')

            # Use provider-agnostic list_by_filter
            vectors = vectordb.list_by_filter(
                filter=filter_dict,
                fields=["doc_id", "filename", "namespace", "chunk_count", "created_at", "headings"],
                limit=10000,
                context=context
            )

            documents = []
            for vector in vectors:
                filename = vector.get("filename")

                # Apply extension filter
                if ext_filter and filename:
                    if not filename.lower().endswith(f'.{ext_filter}'):
                        continue
                elif ext_filter and not filename:
                    continue

                # Handle headings - might be a string or list depending on provider
                headings = vector.get("headings", [])
                if isinstance(headings, str):
                    try:
                        import json
                        headings = json.loads(headings)
                    except (json.JSONDecodeError, TypeError):
                        headings = []

                documents.append({
                    "doc_id": vector.get("doc_id"),
                    "filename": filename,
                    "namespace": vector.get("namespace", "default"),
                    "chunk_count": vector.get("chunk_count"),
                    "created_at": vector.get("created_at"),
                    "headings": headings,
                    # Summary records carry no blob_key, so an original is never
                    # downloadable from this legacy listing path.
                    "has_original": False,
                })

            # Sort by created_at (newest first)
            documents.sort(key=lambda x: x.get("created_at") or "", reverse=True)

            # Apply limit for consistent behavior with pagination
            documents = documents[:limit]

            return {
                "documents": documents,
                "count": len(documents),
                "source": "summaries"
            }

        # Legacy scan-based listing (fallback, uses document index for all providers)
        return await _list_documents_legacy(pipeline, namespace, extension, context)

    except HTTPException:
        raise
    except ForbiddenError:
        raise
    except LimitExceededError:
        raise
    except Exception as e:
        logger.error(f"Failed to list documents: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


async def _list_orphaned_chunks(vectordb, namespace: str | None, context: RequestContext):
    """List chunks without doc_id (legacy data)"""
    if "metadata_scan" not in vectordb.capabilities:
        raise HTTPException(
            status_code=501,
            detail="This operation is only available for Qdrant. "
                   "Orphaned chunks are legacy data from pre-UUID migrations. "
                   "New S3 Vectors deployments don't have orphaned chunks."
        )

    records = vectordb.scan_by_metadata(
        fields=["doc_id", "filename", "namespace", "_type"],
        namespace=namespace,
        context=context
    )

    orphaned_chunks = {}
    for record in records:
        # Skip summary records
        if record.get("_type") == "document_summary":
            continue

        doc_id = record.get("doc_id")
        if doc_id:
            continue

        filename = record.get("filename")
        key = filename or f"orphan_{record['id']}"
        if key not in orphaned_chunks:
            orphaned_chunks[key] = {
                "doc_id": None,
                "filename": filename,
                "namespace": record.get("namespace", "default"),
                "chunk_count": 0,
                "point_ids": [],
                "created_at": None
            }
        orphaned_chunks[key]["chunk_count"] += 1
        orphaned_chunks[key]["point_ids"].append(str(record["id"]))

    return {
        "orphaned_chunks": list(orphaned_chunks.values()),
        "count": len(orphaned_chunks)
    }


async def _list_documents_legacy(pipeline, namespace: str | None, extension: str | None, context: RequestContext):
    """Legacy document listing without summaries

    Now uses document index provider (available for all providers).
    Falls back to full document scan via document index instead of Qdrant-specific scan.
    """
    try:
        # Check if document index is enabled
        if not pipeline.document_index_provider:
            raise HTTPException(
                status_code=501,
                detail="Document index is not enabled. Set ENABLE_DOCUMENT_INDEX=true to use this endpoint."
            )

        # Use document index provider (via pipeline) to list all documents
        result = pipeline.list_documents(
            namespace=namespace,
            limit=10000,  # Legacy scan without pagination
            context=context
        )

        documents = result.get("documents", [])

        # Apply extension filter if provided
        if extension:
            ext_filter = extension.lower().lstrip('.')
            documents = [
                doc for doc in documents
                if doc.get("filename") and doc["filename"].lower().endswith(f'.{ext_filter}')
            ]

        # Sort by created_at (newest first)
        documents.sort(key=lambda x: x.get("created_at") or "", reverse=True)

        return {
            "documents": documents,
            "count": len(documents),
            "source": "legacy_index_scan"
        }

    except ForbiddenError:
        raise
    except LimitExceededError:
        raise
    except Exception as e:
        logger.error(f"Legacy document listing failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/documents/discover")
async def discover_documents(
    http_request: Request,
    query: str = Query(..., description="Semantic search query to find relevant documents"),
    namespace: str | None = Query(None, description="Optional namespace filter (supports wildcards like 'mba/*')"),
    top_k: int = Query(10, ge=1, le=50, description="Number of documents to return")
):
    """
    Semantic discovery of documents.

    Uses vector search over document summaries to find documents matching a topic,
    concept, or natural language query. This is useful for:
    - Finding documents about a specific topic ("documents about leadership")
    - Discovering related documents ("notes on valuation methods")
    - Exploring what's in the knowledge base ("chapters on conflict resolution")

    Returns documents ranked by semantic similarity to the query.
    """
    # S1 enforcement (before the broad try so a denial is a 403, not a 500).
    auth.authorize(http_request, "read_document",
                   {"namespace": namespace} if namespace else None)

    try:
        pipeline = get_pipeline()
        context = RequestContext.from_fastapi_request(http_request, namespace or "")

        # Semantic discovery via the pipeline (embed query + search summaries)
        results = pipeline.discover_documents(
            query=query,
            top_k=top_k,
            namespace=namespace,
            context=context
        )

        # Format response
        documents = []
        for hit in results:
            metadata = hit.get("metadata", {})
            documents.append({
                "doc_id": metadata.get("doc_id"),
                "filename": metadata.get("filename"),
                "namespace": hit.get("namespace", "default"),
                "headings": metadata.get("headings", []),
                "chunk_count": metadata.get("chunk_count"),
                "created_at": metadata.get("created_at"),
                "score": hit.get("score"),
                "summary_preview": hit.get("text", "")[:300]  # First 300 chars of summary
            })

        return {
            "query": query,
            "documents": documents,
            "count": len(documents)
        }

    except ForbiddenError:
        raise
    except LimitExceededError:
        raise
    except Exception as e:
        logger.error(f"Failed to discover documents: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# NOTE: Static routes must come before parameterized routes
@router.get("/documents/chunks")
async def get_chunks_by_ids(
    http_request: Request,
    point_ids: str = Query(..., description="Comma-separated list of point IDs")
):
    """
    Retrieve chunk text content by point IDs.

    Useful for inspecting orphaned chunks that don't have doc_id.
    Pass the point_ids from the orphaned chunks response.

    Example: /api/documents/chunks?point_ids=abc123,def456,ghi789
    """
    # S1 enforcement (namespace unknown until the chunks are loaded).
    auth.authorize(http_request, "read_document")

    ids = [pid.strip() for pid in point_ids.split(",") if pid.strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="point_ids cannot be empty")

    try:
        pipeline = get_pipeline()
        context = RequestContext.from_fastapi_request(http_request, "")

        # Use provider-agnostic chunk retrieval via the pipeline
        chunks = pipeline.get_document_chunks(ids, context=context)

        # Sort by chunk_index if available
        chunks.sort(key=lambda x: x.get("chunk_index", 0))

        return {
            "chunks": [
                {
                    "point_id": c.get("id"),
                    "text": c.get("text", ""),
                    "filename": c.get("filename"),
                    "namespace": c.get("namespace", "default"),
                    "chunk_index": c.get("chunk_index"),
                    "doc_id": c.get("doc_id"),
                    "created_at": c.get("created_at")
                }
                for c in chunks
            ],
            "count": len(chunks),
            "reconstructed_text": _reconstructed_text(chunks, pipeline, context),
        }
    except ForbiddenError:
        raise
    except LimitExceededError:
        raise
    except Exception as e:
        logger.error(f"Failed to get chunks by IDs: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/documents/orphaned")
async def delete_orphaned_chunks(
    http_request: Request,
    filename: str | None = Query(None, description="Delete orphaned chunks for specific filename"),
    all_orphaned: bool = Query(False, description="Delete ALL orphaned chunks (use with caution)")
):
    """Delete orphaned chunks (chunks without doc_id)

    Note: Currently Qdrant-only. Orphaned chunks are legacy data.
    """
    # S1 enforcement (orphaned chunks predate namespaces; none is known here).
    auth.authorize(http_request, "delete_document")

    if not filename and not all_orphaned:
        raise HTTPException(
            status_code=400,
            detail="Must specify either 'filename' or 'all_orphaned=true'"
        )

    try:
        pipeline = get_pipeline()
        vectordb = pipeline.vectordb_provider
        context = RequestContext.from_fastapi_request(http_request, "")

        # Provider check
        if "metadata_scan" not in vectordb.capabilities:
            raise HTTPException(
                status_code=501,
                detail="This operation is only available for Qdrant. "
                       "Orphaned chunks are legacy data from pre-UUID migrations. "
                       "New S3 Vectors deployments don't have orphaned chunks."
            )

        # Find orphaned chunks by scanning and filtering in Python
        # (Qdrant's IsNull condition isn't reliable for missing fields)
        records = vectordb.scan_by_metadata(
            fields=["doc_id", "filename"],
            context=context
        )

        orphan_ids = []
        for record in records:
            doc_id = record.get("doc_id")
            record_filename = record.get("filename")

            # Check if orphaned (no doc_id)
            if doc_id is None:
                # If filtering by filename, check it matches
                if filename and record_filename != filename:
                    continue
                orphan_ids.append(record["id"])

        if not orphan_ids:
            return {
                "success": True,
                "chunks_deleted": 0,
                "message": "No orphaned chunks found"
            }

        # Delete via the provider method (no raw client access)
        vectordb.delete(orphan_ids, context=context)

        logger.info(f"Deleted {len(orphan_ids)} orphaned chunks" + (f" for filename: {filename}" if filename else ""))

        return {
            "success": True,
            "chunks_deleted": len(orphan_ids),
            "filename": filename
        }
    except HTTPException:
        raise
    except ForbiddenError:
        raise
    except LimitExceededError:
        raise
    except Exception as e:
        logger.error(f"Failed to delete orphaned chunks: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/documents/id/{doc_id}")
async def get_document(
    http_request: Request,
    doc_id: str = Path(..., description="Document ID (UUID)"),
    namespace: str = "default"
):
    """Get document by ID - now works with all providers via document index

    Returns document metadata including filename, namespace, chunk count,
    creation date, summary, and document structure.

    Requires Phase 2 document index (enabled by default via ENABLE_DOCUMENT_INDEX).
    Works for both Qdrant and S3 Vectors providers.
    """
    # S1 enforcement (before the broad try so a denial is a 403, not a 500).
    auth.authorize(http_request, "read_document", {"namespace": namespace})

    try:
        pipeline = get_pipeline()

        # Check if document index is enabled
        if not pipeline.document_index_provider:
            raise HTTPException(
                status_code=501,
                detail="Document index is not enabled. Set ENABLE_DOCUMENT_INDEX=true to use this endpoint."
            )

        # Use document index (via pipeline) to retrieve document metadata
        context = RequestContext.from_fastapi_request(http_request, namespace)
        doc = pipeline.get_document_record(doc_id, namespace, context=context)

        if not doc:
            raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

        # Get summary from top-level or fall back to metadata.ai_summary
        metadata = doc.get("metadata", {})
        summary = doc.get("summary") or metadata.get("ai_summary")

        return {
            "doc_id": doc.get("doc_id"),
            "filename": doc.get("filename"),
            "namespace": doc.get("namespace"),
            "chunk_count": doc.get("chunk_count"),
            "created_at": doc.get("created_at"),
            "summary": summary,
            "headings": doc.get("headings", []),
            "metadata": metadata
        }
    except HTTPException:
        raise
    except ForbiddenError:
        raise
    except LimitExceededError:
        raise
    except Exception as e:
        logger.error(f"Failed to get document: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/documents/{doc_id}/original")
async def download_document_original(
    http_request: Request,
    doc_id: str = Path(..., description="Document ID (UUID)"),
    namespace: str = "default",
    format: str = Query(
        "original",
        description="'original' (default) presigns the retained original file; "
                    "'text' presigns the clean extracted/plain text blob."),
):
    """Return a short-lived presigned URL to download a document's original file.

    Requires the retained original to still exist (the record carries a
    ``blob_key``) and the active blob store to support presigned downloads.
    Returns 404 when either is absent (old document, pasted text, or an inline
    tier that cannot presign). The bytes are never streamed through the app.

    With ``?format=text`` the clean extracted/plain text blob (``text_blob_key``)
    is presigned instead -- the same text served as reconstructed_text, without
    the duplicated chunk-overlap regions a chunk join would produce. Returns 404
    when the document has no stored text blob.
    """
    # S1 enforcement: same read op the other document routes authorize on.
    auth.authorize(http_request, "read_document", {"namespace": namespace})

    try:
        pipeline = get_pipeline()

        if not pipeline.document_index_provider:
            raise HTTPException(
                status_code=501,
                detail="Document index is not enabled. Set ENABLE_DOCUMENT_INDEX=true to use this endpoint."
            )

        context = RequestContext.from_fastapi_request(http_request, namespace)
        doc = pipeline.get_document_record(doc_id, namespace, context=context)
        if not doc:
            raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

        if format == "text":
            blob_key = doc.get("text_blob_key")
            download_filename = (doc.get("filename") or "document") + ".txt"
            missing_detail = "No extracted text available for this document"
        else:
            blob_key = doc.get("blob_key")
            download_filename = doc.get("filename")
            missing_detail = "No original file available for this document"

        if not blob_key:
            raise HTTPException(status_code=404, detail=missing_detail)

        from stache_ai.config import settings
        from stache_ai.ingestion.factory import get_ingestion_service

        blobstore = get_ingestion_service().blobstore
        url = blobstore.presign_get(
            blob_key,
            expiry=settings.ingest_blob_download_expiry,
            download_filename=download_filename,
        )
        if not url:
            raise HTTPException(status_code=404, detail=missing_detail)

        return {"url": url}
    except HTTPException:
        raise
    except ForbiddenError:
        raise
    except LimitExceededError:
        raise
    except Exception as e:
        logger.error(f"Failed to presign original download for {doc_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/documents/id/{doc_id}")
async def delete_document_by_id(
    http_request: Request,
    doc_id: str = Path(..., description="Document ID (UUID) to delete"),
    namespace: str = "default",
    permanent: bool = Query(False, description="If true, permanently delete. Otherwise, soft delete to trash.")
) -> dict[str, Any]:
    """
    Delete document (soft delete - moves to trash by default).

    Default: Soft delete (move to trash) with 30-day retention.
    Query param ?permanent=true for immediate permanent delete.
    """
    # S1 enforcement (before the broad try so a denial is a 403, not a 500).
    auth.authorize(http_request, "delete_document", {"namespace": namespace})

    try:
        pipeline = get_pipeline()

        if not pipeline.document_index_provider:
            raise HTTPException(status_code=501, detail="Document index not available")

        context = RequestContext.from_fastapi_request(http_request, namespace)

        if permanent:
            # Permanent delete - unified pipeline hard-delete (vectors, index,
            # delete observers). Raises ValueError -> 404 if not found.
            result = await pipeline.permanently_delete_document(doc_id, namespace, context=context)

            return {
                "status": "deleted",
                "doc_id": doc_id,
                "namespace": namespace,
                "chunks_deleted": result["chunks_deleted"],
                "message": "Document permanently deleted."
            }
        else:
            # Soft delete - move to trash (pipeline also marks vectors "deleting")
            result = pipeline.soft_delete_document(
                doc_id=doc_id,
                namespace=namespace,
                deleted_by="api",
                delete_reason="user_initiated",
                context=context,
            )

            return {
                "status": "deleted",
                "doc_id": result["doc_id"],
                "namespace": result["namespace"],
                "deleted_at": result["deleted_at"],
                "deleted_at_ms": result["deleted_at_ms"],
                "purge_after": result["purge_after"],
                "message": "Document moved to trash. Can be restored within 30 days.",
            }
    except HTTPException:
        raise
    except ForbiddenError:
        raise
    except LimitExceededError:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to delete document: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/documents")
async def delete_document_by_filename(
    http_request: Request,
    filename: str = Query(..., description="Filename to delete"),
    namespace: str = Query(..., description="Namespace containing the document")
):
    """
    Delete all chunks associated with a filename in a namespace.

    This allows re-ingesting a file without duplicates.
    Uses document index to find document by filename, then deletes vectors
    from vector database and entry from document index in atomic operation.
    """
    # S1 enforcement (before the broad try so a denial is a 403, not a 500).
    auth.authorize(http_request, "delete_document", {"namespace": namespace})

    try:
        pipeline = get_pipeline()
        context = RequestContext.from_fastapi_request(http_request, namespace)

        # Unified pipeline delete (document index lookup with fallback to
        # metadata-match delete). Raises ValueError -> 404 if not found.
        result = await pipeline.delete_documents_by_filename(
            filename=filename,
            namespace=namespace,
            context=context,
        )

        return {
            "success": True,
            "filename": filename,
            "namespace": namespace,
            "chunks_deleted": result["chunks_deleted"]
        }
    except HTTPException:
        raise
    except ForbiddenError:
        raise
    except LimitExceededError:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except NotImplementedError:
        raise HTTPException(
            status_code=501,
            detail="delete_by_metadata not implemented for current vector DB provider"
        )
    except Exception as e:
        logger.error(f"Failed to delete document: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


class DocumentUpdateRequest(BaseModel):
    """Request body for document metadata updates"""
    namespace: str | None = Field(None, description="New namespace (migrates document)")
    filename: str | None = Field(None, description="New filename")
    metadata: dict[str, Any] | None = Field(None, description="Custom metadata (replaces existing)")
    headings: list[str] | None = Field(None, description="Document headings (replaces existing)")


@router.patch("/documents/{doc_id}")
async def update_document_metadata(
    http_request: Request,
    doc_id: str = Path(..., description="Document UUID to update"),
    current_namespace: str = Query("default", description="Current namespace"),
    body: DocumentUpdateRequest = Body(...)
):
    """
    Update document metadata (namespace, filename, custom metadata, headings)

    This performs a dual-write to both DynamoDB document index and S3 Vectors.
    Updates metadata for the document record and all associated chunk vectors.

    **Supported Updates:**
    - `namespace`: Migrate document to new namespace
    - `filename`: Rename document
    - `metadata`: Replace custom metadata dict
    - `headings`: Replace document headings list

    **Limitations:**
    - Cannot update: doc_id, chunk_ids, created_at, chunk_count
    - Summary updates: Use POST /api/generate-summaries endpoint

    **Examples:**
    ```
    # Rename document
    PATCH /api/documents/{doc_id}?current_namespace=default
    {"filename": "new-name.pdf"}

    # Migrate to new namespace
    PATCH /api/documents/{doc_id}?current_namespace=old
    {"namespace": "new"}

    # Update custom metadata
    PATCH /api/documents/{doc_id}?current_namespace=default
    {"metadata": {"author": "John Doe", "tags": ["important"]}}
    ```
    """
    # S1 enforcement: authorize the document's CURRENT namespace (the source).
    auth.authorize(http_request, "update_document", {"namespace": current_namespace})
    # A namespace change relocates the document, i.e. writes content INTO the
    # destination namespace, so it must ALSO clear the canonical content-write
    # op ("ingest") for that destination - otherwise a caller could move a doc
    # into a namespace they may not write to by authorizing only the source
    # (AUTHZ F1). The resource dict carries the destination so a plugged
    # authorizer can scope on it.
    if body.namespace is not None and body.namespace != current_namespace:
        auth.authorize(http_request, "ingest", {"namespace": body.namespace})

    # Build updates dict from request body
    updates = {}
    if body.namespace is not None:
        updates["namespace"] = body.namespace
    if body.filename is not None:
        updates["filename"] = body.filename
    if body.metadata is not None:
        from stache_ai.sanitize import strip_reserved_metadata
        updates["metadata"] = strip_reserved_metadata(body.metadata)
    if body.headings is not None:
        updates["headings"] = body.headings

    # Validate before entering try block to ensure 400 status code
    if not updates:
        raise HTTPException(
            status_code=400,
            detail="At least one field must be provided (namespace, filename, metadata, headings)"
        )

    try:
        pipeline = get_pipeline()
        context = RequestContext.from_fastapi_request(http_request, current_namespace)

        # Perform dual-write update
        result = pipeline.update_document(doc_id, current_namespace, updates, context=context)

        return {
            "success": result["success"],
            "doc_id": result["doc_id"],
            "namespace": result["namespace"],
            "updated_chunks": result["updated_chunks"],
            "message": f"Updated document {doc_id} ({result['updated_chunks']} chunks)"
        }

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError:
        raise
    except LimitExceededError:
        raise
    except Exception as e:
        logger.error(f"Failed to update document {doc_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/documents/migrate-summaries")
async def migrate_document_summaries(
    http_request: Request,
    namespace: str | None = Query(None, description="Only migrate documents in this namespace"),
    dry_run: bool = Query(False, description="Show what would be migrated without making changes")
):
    """
    Create document summary records for existing documents.

    Note: Currently Qdrant-only due to requiring full collection scan.
    S3 Vectors users: summaries are created automatically during ingestion.
    """
    # S1 enforcement (before the broad try so a denial is a 403, not a 500).
    auth.authorize(http_request, "regenerate_summary",
                   {"namespace": namespace} if namespace else None)

    from collections import defaultdict
    from datetime import datetime, timezone

    try:
        pipeline = get_pipeline()
        vectordb = pipeline.vectordb_provider
        context = RequestContext.from_fastapi_request(http_request, namespace or "")

        # Provider check
        if "metadata_scan" not in vectordb.capabilities:
            raise HTTPException(
                status_code=501,
                detail="Summary migration is only needed for Qdrant deployments with legacy data. "
                       "S3 Vectors users: summaries are created automatically during document ingestion. "
                       "No migration needed."
            )

        # First, collect all existing summary doc_ids
        existing_summaries = set()
        for record in vectordb.scan_by_metadata(
            filter={"_type": "document_summary"},
            fields=["doc_id"],
            context=context
        ):
            doc_id = record.get("doc_id")
            if doc_id:
                existing_summaries.add(doc_id)

        # Now scan all chunks and group by doc_id
        documents = defaultdict(lambda: {
            "chunks": [],
            "filename": None,
            "namespace": None,
            "created_at": None,
            "headings": []
        })

        for record in vectordb.scan_by_metadata(
            fields=["doc_id", "filename", "namespace", "text", "created_at", "headings", "_type"],
            namespace=namespace,
            context=context
        ):
            if record.get("_type") == "document_summary":
                continue

            doc_id = record.get("doc_id")
            if not doc_id or doc_id in existing_summaries:
                continue

            doc = documents[doc_id]
            doc["chunks"].append(record.get("text", ""))
            doc["filename"] = doc["filename"] or record.get("filename")
            doc["namespace"] = doc["namespace"] or record.get("namespace", "default")
            doc["created_at"] = doc["created_at"] or record.get("created_at")

            chunk_headings = record.get("headings", [])
            if chunk_headings:
                for h in chunk_headings:
                    if h and h not in doc["headings"]:
                        doc["headings"].append(h)

        if not documents:
            return {
                "success": True,
                "message": "No migration needed - all documents have summaries",
                "existing_summaries": len(existing_summaries),
                "migrated": 0
            }

        if dry_run:
            return {
                "success": True,
                "dry_run": True,
                "existing_summaries": len(existing_summaries),
                "would_migrate": len(documents),
                "documents": [
                    {"doc_id": doc_id, "filename": doc["filename"], "chunks": len(doc["chunks"])}
                    for doc_id, doc in list(documents.items())[:50]
                ]
            }

        # Create summaries
        created = 0
        errors = []

        for doc_id, doc in documents.items():
            try:
                summary_parts = [
                    f"Document: {doc['filename'] or 'Unknown'}",
                    f"Namespace: {doc['namespace']}"
                ]

                if doc["headings"]:
                    summary_parts.append(f"Headings: {', '.join(doc['headings'][:20])}")

                content_preview = ""
                char_count = 0
                for chunk in doc["chunks"]:
                    remaining = 1500 - char_count
                    if remaining <= 0:
                        break
                    content_preview += chunk[:remaining] + " "
                    char_count += len(chunk[:remaining])

                if content_preview.strip():
                    summary_parts.append("")
                    summary_parts.append(content_preview.strip())

                summary_text = "\n".join(summary_parts)
                summary_metadata = {
                    "_type": "document_summary",
                    "doc_id": doc_id,
                    "filename": doc["filename"],
                    "namespace": doc["namespace"],
                    "headings": doc["headings"][:50],
                    "chunk_count": len(doc["chunks"]),
                    "created_at": doc["created_at"] or datetime.now(timezone.utc).isoformat(),
                }

                pipeline.regenerate_document_summary(
                    summary_text=summary_text,
                    metadata=summary_metadata,
                    namespace=doc["namespace"],
                    context=context
                )

                created += 1

            except ForbiddenError:
                raise
            except LimitExceededError:
                raise
            except Exception as e:
                errors.append({"doc_id": doc_id, "error": str(e)})
                logger.error(f"Failed to create summary for {doc_id}: {e}")

        logger.info(f"Migration complete: created {created} summaries, {len(errors)} errors")

        return {
            "success": len(errors) == 0,
            "existing_summaries": len(existing_summaries),
            "migrated": created,
            "errors": errors[:10] if errors else []
        }

    except HTTPException:
        raise
    except ForbiddenError:
        raise
    except LimitExceededError:
        raise
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

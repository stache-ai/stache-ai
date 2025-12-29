"""Document management endpoints"""

import logging

from fastapi import APIRouter, HTTPException, Path, Query

from stache_ai.rag.pipeline import get_pipeline

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/documents")
async def list_documents(
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
    try:
        pipeline = get_pipeline()
        vectordb = pipeline.vectordb_provider

        # Handle orphaned chunks separately (requires full scan, Qdrant only)
        if orphaned:
            return await _list_orphaned_chunks(vectordb, namespace)

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

                # Query document index
                result = pipeline.document_index_provider.list_documents(
                    namespace=namespace,
                    limit=limit,
                    last_evaluated_key=last_evaluated_key
                )

                documents = result.get("documents", [])

                # Apply extension filter if provided
                if extension:
                    ext_filter = extension.lower().lstrip('.')
                    documents = [
                        doc for doc in documents
                        if doc.get("filename") and doc["filename"].lower().endswith(f'.{ext_filter}')
                    ]

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
                limit=10000
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
                    "headings": headings
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
        return await _list_documents_legacy(pipeline, namespace, extension)

    except Exception as e:
        logger.error(f"Failed to list documents: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _list_orphaned_chunks(vectordb, namespace: str | None):
    """List chunks without doc_id (legacy data)"""
    if "metadata_scan" not in vectordb.capabilities:
        raise HTTPException(
            status_code=501,
            detail="This operation is only available for Qdrant. "
                   "Orphaned chunks are legacy data from pre-UUID migrations. "
                   "New S3 Vectors deployments don't have orphaned chunks."
        )

    from qdrant_client.models import FieldCondition, Filter, MatchValue

    scroll_filter = None
    if namespace:
        scroll_filter = Filter(
            must=[FieldCondition(key="namespace", match=MatchValue(value=namespace))]
        )

    orphaned_chunks = {}
    offset = None

    while True:
        points, offset = vectordb.client.scroll(
            collection_name=vectordb.collection_name,
            scroll_filter=scroll_filter,
            limit=1000,
            offset=offset,
            with_payload=["doc_id", "filename", "namespace", "_type"],
            with_vectors=False
        )

        for point in points:
            # Skip summary records
            if point.payload.get("_type") == "document_summary":
                continue

            doc_id = point.payload.get("doc_id")
            if doc_id:
                continue

            filename = point.payload.get("filename")
            key = filename or f"orphan_{point.id}"
            if key not in orphaned_chunks:
                orphaned_chunks[key] = {
                    "doc_id": None,
                    "filename": filename,
                    "namespace": point.payload.get("namespace", "default"),
                    "chunk_count": 0,
                    "point_ids": [],
                    "created_at": None
                }
            orphaned_chunks[key]["chunk_count"] += 1
            orphaned_chunks[key]["point_ids"].append(str(point.id))

        if offset is None:
            break

    return {
        "orphaned_chunks": list(orphaned_chunks.values()),
        "count": len(orphaned_chunks)
    }


async def _list_documents_legacy(pipeline, namespace: str | None, extension: str | None):
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

        # Use document index provider to list all documents
        result = pipeline.document_index_provider.list_documents(
            namespace=namespace,
            limit=10000  # Legacy scan without pagination
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

    except Exception as e:
        logger.error(f"Legacy document listing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents/discover")
async def discover_documents(
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
    try:
        pipeline = get_pipeline()
        vectordb = pipeline.vectordb_provider

        # Generate embedding for query
        query_embedding = pipeline.embedding_provider.embed(query)

        # Use summaries provider for semantic discovery
        results = pipeline.summaries_provider.search_summaries(
            query_vector=query_embedding,
            top_k=top_k,
            namespace=namespace
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

    except Exception as e:
        logger.error(f"Failed to discover documents: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# NOTE: Static routes must come before parameterized routes
@router.get("/documents/chunks")
async def get_chunks_by_ids(
    point_ids: str = Query(..., description="Comma-separated list of point IDs")
):
    """
    Retrieve chunk text content by point IDs.

    Useful for inspecting orphaned chunks that don't have doc_id.
    Pass the point_ids from the orphaned chunks response.

    Example: /api/documents/chunks?point_ids=abc123,def456,ghi789
    """
    ids = [pid.strip() for pid in point_ids.split(",") if pid.strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="point_ids cannot be empty")

    try:
        pipeline = get_pipeline()
        vectordb = pipeline.vectordb_provider

        # Use provider-agnostic get_by_ids
        chunks = vectordb.get_by_ids(ids=ids)

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
            "reconstructed_text": "\n\n".join(c.get("text", "") for c in chunks)
        }
    except Exception as e:
        logger.error(f"Failed to get chunks by IDs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/documents/orphaned")
async def delete_orphaned_chunks(
    filename: str | None = Query(None, description="Delete orphaned chunks for specific filename"),
    all_orphaned: bool = Query(False, description="Delete ALL orphaned chunks (use with caution)")
):
    """Delete orphaned chunks (chunks without doc_id)

    Note: Currently Qdrant-only. Orphaned chunks are legacy data.
    """
    if not filename and not all_orphaned:
        raise HTTPException(
            status_code=400,
            detail="Must specify either 'filename' or 'all_orphaned=true'"
        )

    try:
        pipeline = get_pipeline()
        vectordb = pipeline.vectordb_provider

        # Provider check
        if "metadata_scan" not in vectordb.capabilities:
            raise HTTPException(
                status_code=501,
                detail="This operation is only available for Qdrant. "
                       "Orphaned chunks are legacy data from pre-UUID migrations. "
                       "New S3 Vectors deployments don't have orphaned chunks."
            )


        # Find orphaned chunks by scrolling and filtering in Python
        # (Qdrant's IsNull condition isn't reliable for missing fields)
        orphan_ids = []
        offset = None

        while True:
            points, offset = vectordb.client.scroll(
                collection_name=vectordb.collection_name,
                limit=1000,
                offset=offset,
                with_payload=["doc_id", "filename"],
                with_vectors=False
            )

            for point in points:
                doc_id = point.payload.get("doc_id")
                point_filename = point.payload.get("filename")

                # Check if orphaned (no doc_id)
                if doc_id is None:
                    # If filtering by filename, check it matches
                    if filename and point_filename != filename:
                        continue
                    orphan_ids.append(point.id)

            if offset is None:
                break

        if not orphan_ids:
            return {
                "success": True,
                "chunks_deleted": 0,
                "message": "No orphaned chunks found"
            }

        # Delete
        vectordb.client.delete(
            collection_name=vectordb.collection_name,
            points_selector=orphan_ids
        )

        logger.info(f"Deleted {len(orphan_ids)} orphaned chunks" + (f" for filename: {filename}" if filename else ""))

        return {
            "success": True,
            "chunks_deleted": len(orphan_ids),
            "filename": filename
        }
    except Exception as e:
        logger.error(f"Failed to delete orphaned chunks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents/id/{doc_id}")
async def get_document(
    doc_id: str = Path(..., description="Document ID (UUID)"),
    namespace: str = "default"
):
    """Get document by ID - now works with all providers via document index

    Returns document metadata including filename, namespace, chunk count,
    creation date, summary, and document structure.

    Requires Phase 2 document index (enabled by default via ENABLE_DOCUMENT_INDEX).
    Works for both Qdrant and S3 Vectors providers.
    """
    try:
        pipeline = get_pipeline()

        # Check if document index is enabled
        if not pipeline.document_index_provider:
            raise HTTPException(
                status_code=501,
                detail="Document index is not enabled. Set ENABLE_DOCUMENT_INDEX=true to use this endpoint."
            )

        # Use document index to retrieve document metadata
        doc = pipeline.document_index_provider.get_document(doc_id, namespace)

        if not doc:
            raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

        return {
            "doc_id": doc.get("doc_id"),
            "filename": doc.get("filename"),
            "namespace": doc.get("namespace"),
            "chunk_count": doc.get("chunk_count"),
            "created_at": doc.get("created_at"),
            "summary": doc.get("summary"),
            "headings": doc.get("headings", []),
            "metadata": doc.get("metadata", {})
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get document: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/documents/id/{doc_id}")
async def delete_document_by_id(
    doc_id: str = Path(..., description="Document ID (UUID) to delete"),
    namespace: str = "default"
):
    """
    Delete all chunks and summary record associated with a doc_id.

    Uses document index for efficient chunk ID lookup, then deletes vectors
    from vector database and entry from document index in atomic operation.
    """
    try:
        pipeline = get_pipeline()

        # Use document index if available (preferred method)
        if pipeline.document_index_provider:
            # Get chunk IDs from document index
            chunk_ids = pipeline.document_index_provider.get_chunk_ids(doc_id, namespace)

            if not chunk_ids:
                raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

            # Delete from vector database first (atomic operation pattern)
            vectordb = pipeline.vectordb_provider
            vectordb.delete(chunk_ids, namespace=namespace)

            # Delete from document index
            pipeline.document_index_provider.delete_document(doc_id, namespace)

            logger.info(f"Deleted document {doc_id} ({len(chunk_ids)} chunks) from {namespace}")

            return {
                "success": True,
                "doc_id": doc_id,
                "namespace": namespace,
                "chunks_deleted": len(chunk_ids)
            }

        # Fallback: Use legacy vector DB deletion (for backwards compatibility)
        vectordb = pipeline.vectordb_provider
        result = vectordb.delete_by_metadata(
            field="doc_id",
            value=doc_id
        )

        # Also explicitly delete the summary record by its ID
        summary_id = f"summary_{doc_id}"
        try:
            vectordb.delete(ids=[summary_id])
        except Exception:
            pass  # Summary may not exist for older documents

        if result["deleted"] == 0:
            raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

        logger.info(f"Deleted {result['deleted']} chunks + summary for doc_id: {doc_id}")

        return {
            "success": True,
            "doc_id": doc_id,
            "namespace": namespace,
            "chunks_deleted": result["deleted"]
        }
    except HTTPException:
        raise
    except NotImplementedError:
        raise HTTPException(
            status_code=501,
            detail="delete_by_metadata not implemented for current vector DB provider"
        )
    except Exception as e:
        logger.error(f"Failed to delete document: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/documents")
async def delete_document_by_filename(
    filename: str = Query(..., description="Filename to delete"),
    namespace: str | None = Query(None, description="Optional namespace filter")
):
    """
    Delete all chunks associated with a filename.

    This allows re-ingesting a file without duplicates.
    Uses document index to find document by filename, then deletes vectors
    from vector database and entry from document index in atomic operation.
    """
    try:
        pipeline = get_pipeline()

        # Use document index if available (preferred method)
        if pipeline.document_index_provider and namespace:
            # Check if document exists by filename in the namespace
            doc_exists = pipeline.document_index_provider.document_exists(filename, namespace)

            if not doc_exists:
                raise HTTPException(status_code=404, detail=f"Document not found: {filename}")

            # Query document index by filename using GSI2
            # We need to get the document first to find its doc_id
            result = pipeline.document_index_provider.list_documents(namespace=namespace, limit=1000)
            docs = result.get('documents', [])

            # Find the document with matching filename
            target_doc = None
            for doc in docs:
                if doc.get('filename') == filename:
                    target_doc = doc
                    break

            if not target_doc:
                raise HTTPException(status_code=404, detail=f"Document not found: {filename}")

            doc_id = target_doc.get('doc_id')
            chunk_ids = target_doc.get('chunk_ids', [])

            if not chunk_ids:
                raise HTTPException(status_code=404, detail=f"Document has no chunks: {filename}")

            # Delete from vector database first (atomic operation pattern)
            vectordb = pipeline.vectordb_provider
            vectordb.delete(chunk_ids, namespace=namespace)

            # Delete from document index
            pipeline.document_index_provider.delete_document(doc_id, namespace)

            logger.info(f"Deleted document {filename} ({len(chunk_ids)} chunks) from {namespace}")

            return {
                "success": True,
                "filename": filename,
                "namespace": namespace,
                "chunks_deleted": len(chunk_ids)
            }

        # Fallback: Use documents provider for deletion (for backwards compatibility)
        result = pipeline.documents_provider.delete_by_metadata(
            field="filename",
            value=filename,
            namespace=namespace
        )

        logger.info(f"Deleted {result['deleted']} chunks for filename: {filename}")

        return {
            "success": True,
            "filename": filename,
            "namespace": namespace,
            "chunks_deleted": result["deleted"]
        }
    except HTTPException:
        raise
    except NotImplementedError:
        raise HTTPException(
            status_code=501,
            detail="delete_by_metadata not implemented for current vector DB provider"
        )
    except Exception as e:
        logger.error(f"Failed to delete document: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/documents/migrate-summaries")
async def migrate_document_summaries(
    namespace: str | None = Query(None, description="Only migrate documents in this namespace"),
    dry_run: bool = Query(False, description="Show what would be migrated without making changes")
):
    """
    Create document summary records for existing documents.

    Note: Currently Qdrant-only due to requiring full collection scan.
    S3 Vectors users: summaries are created automatically during ingestion.
    """
    from collections import defaultdict
    from datetime import datetime, timezone

    try:
        pipeline = get_pipeline()
        vectordb = pipeline.vectordb_provider

        # Provider check
        if "metadata_scan" not in vectordb.capabilities:
            raise HTTPException(
                status_code=501,
                detail="Summary migration is only needed for Qdrant deployments with legacy data. "
                       "S3 Vectors users: summaries are created automatically during document ingestion. "
                       "No migration needed."
            )

        from qdrant_client.models import FieldCondition, Filter, MatchValue

        # First, collect all existing summary doc_ids
        existing_summaries = set()
        offset = None

        while True:
            points, offset = vectordb.client.scroll(
                collection_name=vectordb.collection_name,
                scroll_filter=Filter(
                    must=[FieldCondition(key="_type", match=MatchValue(value="document_summary"))]
                ),
                limit=1000,
                offset=offset,
                with_payload=["doc_id"],
                with_vectors=False
            )

            for point in points:
                doc_id = point.payload.get("doc_id")
                if doc_id:
                    existing_summaries.add(doc_id)

            if offset is None:
                break

        # Now scan all chunks and group by doc_id
        documents = defaultdict(lambda: {
            "chunks": [],
            "filename": None,
            "namespace": None,
            "created_at": None,
            "headings": []
        })

        scroll_filter = None
        if namespace:
            scroll_filter = Filter(
                must=[FieldCondition(key="namespace", match=MatchValue(value=namespace))]
            )

        offset = None

        while True:
            points, offset = vectordb.client.scroll(
                collection_name=vectordb.collection_name,
                scroll_filter=scroll_filter,
                limit=1000,
                offset=offset,
                with_payload=["doc_id", "filename", "namespace", "text", "created_at", "headings", "_type"],
                with_vectors=False
            )

            for point in points:
                if point.payload.get("_type") == "document_summary":
                    continue

                doc_id = point.payload.get("doc_id")
                if not doc_id or doc_id in existing_summaries:
                    continue

                doc = documents[doc_id]
                doc["chunks"].append(point.payload.get("text", ""))
                doc["filename"] = doc["filename"] or point.payload.get("filename")
                doc["namespace"] = doc["namespace"] or point.payload.get("namespace", "default")
                doc["created_at"] = doc["created_at"] or point.payload.get("created_at")

                chunk_headings = point.payload.get("headings", [])
                if chunk_headings:
                    for h in chunk_headings:
                        if h and h not in doc["headings"]:
                            doc["headings"].append(h)

            if offset is None:
                break

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
                summary_embedding = pipeline.embedding_provider.embed(summary_text)

                import uuid
                summary_id = str(uuid.uuid4())
                summary_metadata = {
                    "_type": "document_summary",
                    "doc_id": doc_id,
                    "filename": doc["filename"],
                    "namespace": doc["namespace"],
                    "headings": doc["headings"][:50],
                    "chunk_count": len(doc["chunks"]),
                    "created_at": doc["created_at"] or datetime.now(timezone.utc).isoformat(),
                }

                vectordb.insert(
                    vectors=[summary_embedding],
                    texts=[summary_text],
                    metadatas=[summary_metadata],
                    ids=[summary_id],
                    namespace=doc["namespace"]
                )

                created += 1

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

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

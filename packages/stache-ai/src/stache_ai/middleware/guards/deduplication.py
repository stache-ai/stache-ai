"""Deduplication guard for hash-based duplicate detection."""
from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from stache_ai.middleware.base import IngestGuard, GuardResult
from stache_ai.utils.hashing import compute_hash_async

if TYPE_CHECKING:
    from stache_ai.middleware.context import RequestContext

logger = logging.getLogger(__name__)


class DeduplicationGuard(IngestGuard):
    """Guard that blocks duplicate content ingestion.

    Handles REINGEST_VERSION case: if content hash differs at same path,
    triggers soft delete of old version before allowing new ingestion.

    Priority: 50 (runs early, before expensive operations)
    """

    priority = 50
    on_error = "allow"  # Don't block on dedup failure

    async def validate(
        self,
        content: str,
        metadata: dict[str, Any],
        context: "RequestContext"
    ) -> GuardResult:
        """Check for duplicate content via hash lookup."""
        import time

        document_index = context.custom.get("document_index")
        vectordb = context.custom.get("vectordb")  # NEW: for soft delete
        config = context.custom.get("config")

        if not config or not config.dedup_enabled:
            return GuardResult(action="allow")

        if not document_index:
            logger.warning("Dedup enabled but document_index not available")
            return GuardResult(action="allow")

        start_time = time.perf_counter()

        # Step 1: Compute content hash
        content_hash = await compute_hash_async(content)
        hash_time = time.perf_counter() - start_time

        # Step 2: Check for existing document using GSI2 (source_path or filename)
        filename = metadata.get("filename", "text")
        source_path = metadata.get("source_path")

        existing = document_index.get_document_by_source_path(
            namespace=context.namespace,
            source_path=source_path,
            filename=filename,
        )

        lookup_time = time.perf_counter() - start_time - hash_time

        if existing:
            # Hash match at same identifier → SKIP
            if existing["content_hash"] == content_hash:
                logger.info(
                    "Duplicate content detected - blocking ingestion",
                    extra={
                        "guard": "DeduplicationGuard",
                        "action": "reject",
                        "content_hash": content_hash[:16],
                        "namespace": context.namespace,
                        "existing_doc_id": existing["doc_id"],
                        "hash_compute_ms": int(hash_time * 1000),
                        "lookup_ms": int(lookup_time * 1000),
                    }
                )

                return GuardResult(
                    action="reject",
                    reason=f"duplicate content (hash: {content_hash[:16]}...)",
                    metadata={
                        "existing_doc_id": existing["doc_id"],
                        "content_hash": content_hash,
                    }
                )

            # Different hash at same identifier → REINGEST_VERSION
            # (Only happens for SOURCE-based identifiers with source_path)
            logger.info(
                "Content updated at same path - triggering REINGEST_VERSION",
                extra={
                    "guard": "DeduplicationGuard",
                    "action": "allow_reingest",
                    "old_hash": existing["content_hash"][:16],
                    "new_hash": content_hash[:16],
                    "namespace": context.namespace,
                    "previous_doc_id": existing["doc_id"],
                }
            )

            # Soft delete old version (best-effort)
            deleted_at_ms = None
            if document_index and vectordb:
                try:
                    # Soft delete old document
                    old_doc = document_index.soft_delete_document(
                        doc_id=existing["doc_id"],
                        namespace=context.namespace,
                        delete_reason="reingest_version"
                    )
                    deleted_at_ms = old_doc.get("deleted_at_ms")

                    # Update vector status to deleting (best-effort)
                    if old_doc.get("chunk_ids"):
                        await vectordb.update_status(
                            ids=old_doc["chunk_ids"],
                            namespace=context.namespace,
                            status="deleting",
                        )

                    logger.info(
                        "Old version soft-deleted for REINGEST_VERSION",
                        extra={
                            "previous_doc_id": existing["doc_id"],
                            "chunks_marked_deleting": len(old_doc.get("chunk_ids", [])),
                            "deleted_at_ms": deleted_at_ms,
                        }
                    )
                except Exception as e:
                    # Log error but don't block ingestion
                    logger.error(
                        f"Failed to soft delete old version: {e}",
                        extra={"previous_doc_id": existing["doc_id"]}
                    )

            # Allow new version to ingest
            return GuardResult(
                action="allow",
                metadata={
                    "content_hash": content_hash,
                    "_reingest_version": True,
                    "_previous_doc_id": existing["doc_id"],
                    "_deleted_at_ms": deleted_at_ms,  # Needed for error recovery
                }
            )

        # No duplicate - allow ingestion and attach hash
        return GuardResult(
            action="allow",
            metadata={"content_hash": content_hash}
        )

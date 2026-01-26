"""Error recovery for REINGEST_VERSION failures."""
from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from stache_ai.middleware.base import ErrorProcessor, ErrorResult

if TYPE_CHECKING:
    from stache_ai.middleware.context import RequestContext

logger = logging.getLogger(__name__)


class ReingestRecoveryProcessor(ErrorProcessor):
    """Restore old document if REINGEST_VERSION fails.

    When a REINGEST_VERSION operation fails after soft-deleting the old
    version, this processor restores the old document to prevent data loss.

    Flow:
    1. Guard detects hash mismatch, soft-deletes old doc
    2. New ingestion fails (enrichment error, vector insert failure, etc.)
    3. This processor restores old doc from trash
    4. Original exception re-raised (request still fails)

    Result: Old version restored to active state, user sees clear error,
    no partial duplicates or orphaned trash entries.
    """

    priority = 100  # Run early (higher priority)

    async def on_error(
        self,
        exception: Exception,
        context: "RequestContext",
        partial_state: dict[str, Any],
    ) -> ErrorResult:
        """Restore old document if REINGEST_VERSION failed."""
        metadata = partial_state.get("metadata", {})
        previous_doc_id = metadata.get("_previous_doc_id")
        deleted_at_ms = metadata.get("_deleted_at_ms")

        if not previous_doc_id:
            # Not a REINGEST_VERSION operation, nothing to restore
            return ErrorResult(handled=False)

        # Get providers from context
        document_index = context.custom.get("document_index")
        if not document_index:
            logger.error(
                "Cannot restore old version: document_index_provider not available",
                extra={"previous_doc_id": previous_doc_id}
            )
            return ErrorResult(handled=False)

        try:
            logger.warning(
                "REINGEST_VERSION failed, attempting to restore old version",
                extra={
                    "previous_doc_id": previous_doc_id,
                    "namespace": context.namespace,
                    "error": str(exception),
                }
            )

            # Restore old document from trash (single attempt, no retry)
            restored = document_index.restore_document(
                doc_id=previous_doc_id,
                namespace=context.namespace,
                deleted_at_ms=deleted_at_ms,
                restored_by="system_auto_recovery",
            )

            # Restore vector status from "deleting" back to "active"
            vectordb = context.custom.get("vectordb")
            chunk_ids = restored.get("chunk_ids", [])

            if vectordb and chunk_ids:
                try:
                    await vectordb.update_status(
                        ids=chunk_ids,
                        namespace=context.namespace,
                        status="active",
                    )
                    logger.info(
                        "Vector status restored to active",
                        extra={
                            "previous_doc_id": previous_doc_id,
                            "chunks_updated": len(chunk_ids),
                        }
                    )
                except Exception as vector_error:
                    # Log warning but don't fail recovery
                    logger.warning(
                        f"Failed to restore vector status: {vector_error}",
                        extra={"previous_doc_id": previous_doc_id}
                    )

            logger.info(
                "Old version restored after REINGEST_VERSION failure",
                extra={
                    "previous_doc_id": previous_doc_id,
                    "chunks_restored": restored.get("chunk_count", 0),
                }
            )

            return ErrorResult(
                handled=True,
                metadata={
                    "restored_doc_id": previous_doc_id,
                    "chunks_restored": restored.get("chunk_count", 0),
                }
            )

        except Exception as e:
            # Log error but don't block other error processors
            logger.error(
                f"Failed to restore old version: {e}",
                extra={"previous_doc_id": previous_doc_id}
            )
            return ErrorResult(handled=False)

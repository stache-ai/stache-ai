"""Scheduled job to purge expired trash entries (replaces DynamoDB TTL)."""
import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


async def purge_expired_trash(
    pipeline,
    batch_size: int = 100,
    max_runtime_seconds: int = 300
):
    """
    Find and permanently delete expired trash entries.

    Runs daily to purge trash entries past their purge_after date.
    This replaces DynamoDB TTL for provider-agnostic purging.
    """
    if not pipeline.document_index_provider:
        logger.warning("Document index not available")
        return {"processed": 0, "purged": 0, "failed": 0}

    start_time = datetime.now(timezone.utc)
    stats = {"processed": 0, "purged": 0, "failed": 0}

    # List expired trash entries
    expired = pipeline.document_index_provider.list_expired_trash(limit=batch_size)

    for entry in expired:
        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        if elapsed > max_runtime_seconds:
            logger.warning(f"Purge timeout, processed {stats['processed']}")
            break

        stats["processed"] += 1

        try:
            # Permanently delete (creates cleanup job)
            pipeline.document_index_provider.permanently_delete_document(
                doc_id=entry["doc_id"],
                namespace=entry["namespace"],
                deleted_at_ms=entry["deleted_at_ms"],
                deleted_by="system_auto_purge"
            )
            stats["purged"] += 1

            logger.info(
                "Expired trash entry purged",
                extra={
                    "doc_id": entry["doc_id"],
                    "namespace": entry["namespace"],
                    "purge_after": entry["purge_after"],
                }
            )
        except Exception as e:
            stats["failed"] += 1
            logger.error(
                f"Failed to purge expired trash: {entry['doc_id']}",
                exc_info=True
            )

    logger.info("Trash purge completed", extra=stats)
    return stats


def lambda_handler(event, context):
    """Lambda handler for daily trash purge."""
    from stache_ai.rag.pipeline import get_pipeline

    pipeline = get_pipeline()

    stats = asyncio.run(purge_expired_trash(
        pipeline=pipeline,
        batch_size=100,
        max_runtime_seconds=context.get_remaining_time_in_millis() / 1000 - 10,
    ))

    return {"statusCode": 200, "body": stats}

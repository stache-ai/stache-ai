"""Background worker for permanent document deletion."""
import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


async def process_cleanup_jobs(
    pipeline,
    batch_size: int = 10,
    max_runtime_seconds: int = 300
):
    """Process pending cleanup jobs."""
    if not pipeline.document_index_provider:
        logger.warning("Document index not available")
        return {"processed": 0, "succeeded": 0, "failed": 0}

    start_time = datetime.now(timezone.utc)
    stats = {"processed": 0, "succeeded": 0, "failed": 0}

    jobs = pipeline.document_index_provider.list_cleanup_jobs(limit=batch_size)

    for job in jobs:
        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        if elapsed > max_runtime_seconds:
            logger.warning(f"Cleanup timeout, processed {stats['processed']}")
            break

        stats["processed"] += 1

        try:
            await _process_cleanup_job(pipeline, job)
            stats["succeeded"] += 1
        except Exception as e:
            stats["failed"] += 1
            logger.error(f"Cleanup failed: {job['cleanup_job_id']}", exc_info=True)

            # Mark job as failed (increment retry or move to DLQ)
            pipeline.document_index_provider.mark_cleanup_job_failed(
                cleanup_job_id=job["cleanup_job_id"],
                error=str(e)
            )

    logger.info("Cleanup batch completed", extra=stats)
    return stats


async def _process_cleanup_job(pipeline, job):
    """Process single cleanup job."""
    cleanup_job_id = job["cleanup_job_id"]
    doc_id = job["doc_id"]
    namespace = job["namespace"]
    filename = job["filename"]  # NEW: needed for trash PK
    deleted_at_ms = job["deleted_at_ms"]
    chunk_ids = job["chunk_ids"]

    logger.info(
        f"Starting cleanup for {doc_id}",
        extra={"cleanup_job_id": cleanup_job_id, "chunk_count": len(chunk_ids)}
    )

    # Delete vectors
    deleted_count = await pipeline.documents_provider.delete_by_ids(
        ids=chunk_ids,
        namespace=namespace,
    )

    if deleted_count != len(chunk_ids):
        logger.warning(
            f"Partial deletion: {deleted_count}/{len(chunk_ids)}",
            extra={"cleanup_job_id": cleanup_job_id}
        )

    # Complete permanent delete (mark doc as purged, delete trash entry)
    pipeline.document_index_provider.complete_permanent_delete(
        doc_id=doc_id,
        namespace=namespace,
        deleted_at_ms=deleted_at_ms,
        filename=filename,  # NEW: pass filename for trash PK
    )

    logger.info(
        f"Cleanup completed for {doc_id}",
        extra={"cleanup_job_id": cleanup_job_id, "vectors_deleted": deleted_count}
    )


def lambda_handler(event, context):
    """Lambda handler for scheduled cleanup."""
    from stache_ai.rag.pipeline import get_pipeline

    pipeline = get_pipeline()

    stats = asyncio.run(process_cleanup_jobs(
        pipeline=pipeline,
        batch_size=10,
        max_runtime_seconds=context.remaining_time_in_millis() / 1000 - 10,
    ))

    return {"statusCode": 200, "body": stats}

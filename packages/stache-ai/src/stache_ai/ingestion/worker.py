"""Provider-agnostic ingestion worker.

The single async processing function used by every tier: inline-awaited in the
sync tier now, driven by an SQS Lambda via ``asyncio.run`` in Phase 2. It
delegates straight to the existing pipeline - text via ``ingest_text``, files
by temp-writing the blob and calling ``ingest_file`` (which self-loads via
Docling and auto-chunks by type). No custom loading lives here.
"""

import logging
import os
import tempfile
import traceback
from datetime import datetime, timezone

from .base import JobEvent, JobStatus

logger = logging.getLogger(__name__)

SUPPORTED_TEXT = {"text", "markdown"}

# Transport-only metadata keys that must never reach enrichers / the vector store.
_TRANSPORT_KEYS = {"_text", "_chunking", "_prepend_metadata"}


def make_worker(jobstore, blobstore, notifier, pipeline):
    def _now():
        return datetime.now(timezone.utc).isoformat()

    async def process(job_id: str) -> None:
        job = jobstore.get(job_id)
        if job is None:
            logger.warning(f"[ingest] job {job_id} not found; nothing to process")
            return
        jobstore.update(job_id, status=JobStatus.PROCESSING, updated_at=_now())
        notifier.publish(JobEvent(job_id, JobStatus.PROCESSING, job.requested_by, job.namespace))
        try:
            # Strip transport-only keys before they reach enrichers / vector store.
            md = {k: v for k, v in job.metadata.items() if k not in _TRANSPORT_KEYS}
            prepend = job.metadata.get("_prepend_metadata")
            if job.content_type in SUPPORTED_TEXT and "_text" in job.metadata:
                result = await pipeline.ingest_text(
                    text=job.metadata["_text"],
                    namespace=job.namespace,
                    metadata=md,
                    chunking_strategy=job.metadata.get("_chunking", "recursive"),
                    prepend_metadata=prepend,
                )
            else:
                data, _ = blobstore.get(job.blob_key)            # bytes from BlobStore
                md.setdefault("filename", job.filename)
                suffix = os.path.splitext(job.filename)[1]
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tf:
                    tf.write(data)
                    tf.flush()
                    result = await pipeline.ingest_file(            # loads + chunks internally
                        file_path=tf.name,
                        namespace=job.namespace,
                        metadata=md,
                        prepend_metadata=prepend,
                    )

            # Result keys: `doc_id` and (for text) `action` ("skipped" == dedup hit).
            # ingest_file omits `action`; .get(...) => None => DONE.
            doc_id = result["doc_id"]
            status = JobStatus.SKIPPED if result.get("action") == "skipped" else JobStatus.DONE
            jobstore.update(
                job_id,
                status=status,
                doc_id=doc_id,
                chunks_created=result.get("chunks_created", 0) or 0,
                updated_at=_now(),
                completed_at=_now(),
            )
            notifier.publish(JobEvent(job_id, status, job.requested_by, job.namespace, doc_id))
        except Exception as e:
            jobstore.update(
                job_id,
                status=JobStatus.FAILED,
                error_detail=str(e)[:500],
                updated_at=_now(),
                completed_at=_now(),
            )
            notifier.publish(JobEvent(job_id, JobStatus.FAILED, job.requested_by, job.namespace))
            logger.error(f"[ingest] job {job_id} failed: {e}\n{traceback.format_exc()}")

    return process

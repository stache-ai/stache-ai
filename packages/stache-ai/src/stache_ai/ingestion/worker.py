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

from stache_ai.identity import assert_can_write
from stache_ai.middleware.context import RequestContext

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
        # Idempotent claim: win the QUEUED/UPLOADING -> PROCESSING transition or
        # bail. The async tier delivers the same job more than once (SQS is
        # at-least-once; a blob-backed job fires both a direct enqueue and an S3
        # ObjectCreated event), so a losing duplicate must no-op here instead of
        # re-ingesting.
        if not jobstore.claim(job_id, from_statuses={JobStatus.QUEUED, JobStatus.UPLOADING}):
            logger.info(f"[ingest] job {job_id} already claimed/terminal; skipping duplicate delivery")
            return
        notifier.publish(JobEvent(job_id, JobStatus.PROCESSING, job.requested_by, job.namespace))
        try:
            # Defense-in-depth re-check (S1): the worker consumes from a queue
            # anything can write to; do not trust that intake already checked.
            # The jobstore reconstructs the acting principal (deployment stores
            # may rehydrate claims they stamped at create time) so a plugged
            # authorizer sees the same identity the original caller carried.
            principal = jobstore.principal_for(job)
            assert_can_write(principal, job.namespace)
            # Identity + job travel with the pipeline call so middleware and
            # providers see who this work belongs to (context.custom is the
            # opaque extension surface; the core attaches no meaning to it).
            context = RequestContext(
                request_id=job.job_id,
                timestamp=datetime.now(timezone.utc),
                namespace=job.namespace,
                user_id=job.requested_by,
                source="worker",
                custom={"ingest_job": job, "principal": principal},
            )
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
                    context=context,
                )
            else:
                data, _ = blobstore.get(job.blob_key)            # bytes from BlobStore
                md.setdefault("filename", job.filename)
                # Write under the ORIGINAL filename (not a random tmp*.ext) so ingest_file
                # records the real name and selects the loader by its true extension.
                with tempfile.TemporaryDirectory() as tmpdir:
                    fpath = os.path.join(tmpdir, os.path.basename(job.filename))
                    with open(fpath, "wb") as fh:
                        fh.write(data)
                    result = await pipeline.ingest_file(            # loads + chunks internally
                        file_path=fpath,
                        namespace=job.namespace,
                        metadata=md,
                        # Honor the client's chunking choice (the GUI submits "recursive");
                        # only fall back to file-type auto-selection when unset.
                        chunking_strategy=job.metadata.get("_chunking", "auto"),
                        prepend_metadata=prepend,
                        context=context,
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

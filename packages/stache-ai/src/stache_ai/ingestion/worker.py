"""Provider-agnostic ingestion worker.

The single async processing function used by every tier: inline-awaited in the
sync tier, driven by a queue-consumer entrypoint in async tiers. It
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
from stache_ai.sanitize import is_reserved_metadata_key

from .base import JobEvent, JobStatus, strip_transport

logger = logging.getLogger(__name__)

SUPPORTED_TEXT = {"text", "markdown"}


def make_worker(jobstore, blobstore, notifier, pipeline):
    def _now():
        return datetime.now(timezone.utc).isoformat()

    async def process(job_id: str) -> None:
        job = jobstore.get(job_id)
        if job is None:
            logger.warning(f"[ingest] job {job_id} not found; nothing to process")
            return
        # Idempotent claim: win the QUEUED/UPLOADING -> PROCESSING transition or
        # bail. The async tier delivers the same job more than once (queues are
        # at-least-once; a blob-backed job fires both a direct enqueue and a
        # blob-store object-created event), so a losing duplicate must no-op here
        # instead of re-ingesting.
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
                # ``blobstore`` rides along so the pipeline can persist the full
                # extracted/plain text to the blob store at ingest (the pipeline
                # has the text but no blob-store handle of its own). The clean
                # text is served back by GET chunks (reconstructed_text) and by
                # GET .../original?format=text instead of re-joining chunks, which
                # would duplicate the chunk_overlap regions.
                custom={
                    "ingest_job": job,
                    "principal": principal,
                    "blobstore": blobstore,
                },
            )
            # Strip every reserved key before it reaches enrichers / the vector
            # store - not just the transport keys. Uses the SAME reserved-key
            # predicate as the API sanitizer (sanitize.is_reserved_metadata_key)
            # so "reserved" has one definition: underscore-prefixed keys plus
            # ``content_hash``. Deployment stores stamp server-set state (dedup
            # markers, error-recovery bookkeeping, etc.) under other `_` keys on
            # the JOB record; that state is rehydrated from
            # ``context.custom["ingest_job"]`` above, never from chunk metadata,
            # so none of it belongs here. The worker still reads its own
            # transport keys (_text/_chunking/_prepend_metadata) directly off
            # ``job.metadata`` below; only ``md`` (what flows onward) is filtered.
            md = {k: v for k, v in job.metadata.items() if not is_reserved_metadata_key(k)}
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
                # Drop the inline document body from the persisted record now that
                # processing is done: transport-only keys (notably _text) can be
                # hundreds of KB and would otherwise blow past DynamoDB's 400KB
                # item cap and leak into GET /api/jobs responses. Safe here because
                # the job is terminal (any losing duplicate already no-op'd).
                metadata=strip_transport(job.metadata),
                updated_at=_now(),
                completed_at=_now(),
            )
            notifier.publish(JobEvent(job_id, status, job.requested_by, job.namespace, doc_id))
        except Exception as e:
            jobstore.update(
                job_id,
                status=JobStatus.FAILED,
                error_detail=str(e)[:500],
                metadata=strip_transport(job.metadata),
                updated_at=_now(),
                completed_at=_now(),
            )
            notifier.publish(JobEvent(job_id, JobStatus.FAILED, job.requested_by, job.namespace))
            logger.error(f"[ingest] job {job_id} failed: {e}\n{traceback.format_exc()}")

    return process

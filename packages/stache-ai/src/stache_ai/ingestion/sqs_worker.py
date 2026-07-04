"""SQS-triggered worker Lambda for the async ingestion tier.

Provider-agnostic: drives the Phase 1 worker via ``get_ingestion_service()`` and
``asyncio.run`` per record. Stays boto3-free - all AWS access goes through the
ingestion seams (BlobStore / JobStore). Two record shapes are handled:

  * Direct API path: SQS body is a bare ``job_id`` (the job already exists).
  * Producer path: SQS body is an S3 event (object dropped in the originals
    bucket); a Job is created from the object's ``x-amz-meta-stache-*`` metadata.

Returns partial-batch failures so only failed records redrive (SQS
``ReportBatchItemFailures``).
"""

import asyncio
import json
import logging

from stache_ai.identity import Principal, assert_can_write

from .base import TERMINAL, Job, JobStatus
from .factory import get_ingestion_service

logger = logging.getLogger(__name__)


def lambda_handler(event, context):
    service = get_ingestion_service()
    batch_failures = []
    for record in event.get("Records", []):
        try:
            job_id = _job_id_from_record(record, service)
            if job_id:
                asyncio.run(service.process_job(job_id))
        except Exception as e:
            logger.error(f"[sqs-worker] record failed: {e}")
            batch_failures.append({"itemIdentifier": record.get("messageId")})
    return {"batchItemFailures": batch_failures}


def _job_id_from_record(record, service):
    body = record.get("body", "") or ""
    # Direct API path: body is a bare job_id.
    if body and "{" not in body:
        return body
    # Producer path: S3 event (possibly wrapped by SQS) -> create a Job.
    msg = json.loads(body)
    s3recs = msg.get("Records", [])
    if s3recs and s3recs[0].get("eventSource") == "aws:s3":
        return _ingest_dropped_object(s3recs[0], service)
    return None


def _ingest_dropped_object(rec, service):
    from datetime import datetime, timezone
    import urllib.parse

    from stache_ai.config import settings

    full_key = urllib.parse.unquote_plus(rec["s3"]["object"]["key"])
    prefix = (settings.ingest_blob_s3_prefix or "").strip("/")
    logical = full_key[len(prefix) + 1:] if prefix and full_key.startswith(prefix + "/") else full_key
    job_id = logical.split("/")[0]                 # presign key = "{job_id}/{filename}"

    existing = service.jobstore.get(job_id)
    if existing is not None:
        # Presign path: the client's upload just landed, so hand the pre-created
        # job (status UPLOADING) off to the worker. For any other state the object
        # belongs to a job another trigger already owns - the inline/base64 path
        # writes its retention blob to this same bucket but is driven by a direct
        # enqueue (job is already QUEUED), and a redelivered event must never
        # reset a QUEUED/PROCESSING/terminal job. Defer in those cases.
        if existing.status == JobStatus.UPLOADING:
            service.jobstore.update(
                job_id,
                status=JobStatus.QUEUED,
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
            return job_id
        return None

    # Raw producer drop (Phase 2 path): create a Job from the object's metadata.
    from stache_ai.config import settings as _settings
    if not _settings.ingest_producer_drops_enabled:
        logger.warning(
            f"[ingest] ignoring producer drop {logical}: producer drops are disabled "
            f"(INGEST_PRODUCER_DROPS_ENABLED=false)"
        )
        return None
    return _create_producer_job(rec, service, logical)


def _create_producer_job(rec, service, logical):
    from datetime import datetime, timezone
    import uuid

    from stache_ai.config import settings

    raw = service.blobstore.head(logical)         # x-amz-meta-stache-* mapped by S3BlobStore.head
    # Normalize hyphens to underscores so producers can tag objects with either
    # `stache-content-type` or `stache-content_type` (S3 lowercases header keys
    # and preserves the separator). Without this, `content-type`/`requested-by`
    # silently fall back to defaults (octet-stream / "producer").
    meta = {k.replace("-", "_"): v for k, v in raw.items()}
    now = datetime.now(timezone.utc).isoformat()
    namespace = meta.get("namespace", settings.default_namespace)
    requested_by = meta.get("requested_by", "producer")
    # Authorization hook (S1): object metadata is producer-asserted, not verified
    # identity. The bucket policy is the real boundary for this path; deployments
    # needing verified callers should disable producer drops instead.
    assert_can_write(Principal(user_id=requested_by), namespace)
    logger.info(
        f"[ingest] producer drop accepted: key={logical} namespace={namespace} "
        f"requested_by={requested_by}"
    )
    job = Job(
        job_id=str(uuid.uuid4()),
        status=JobStatus.QUEUED,
        namespace=namespace,
        source="producer",
        filename=meta.get("filename", logical.rsplit("/", 1)[-1]),
        content_type=meta.get("content_type", "application/octet-stream"),
        requested_by=requested_by,
        blob_key=logical,
        metadata={},
        created_at=now,
        updated_at=now,
    )
    service.jobstore.create(job)
    return job.job_id

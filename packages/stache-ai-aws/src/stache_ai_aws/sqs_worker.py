"""SQS-triggered worker Lambda for the async ingestion tier.

Drives the provider-agnostic worker via ``get_ingestion_service()`` and
``asyncio.run`` per record. All storage access goes through the ingestion
seams (BlobStore / JobStore). Two record shapes are handled:

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
from stache_ai.ingestion.base import Job, JobStatus
from stache_ai.ingestion.factory import get_ingestion_service

from .settings import AwsIngestSettings

logger = logging.getLogger(__name__)


def lambda_handler(event, context):
    service = get_ingestion_service()
    batch_failures = []
    for record in event.get("Records", []):
        try:
            for job_id in _job_ids_from_record(record, service):
                asyncio.run(service.process_job(job_id))
        except Exception as e:
            logger.error(f"[sqs-worker] record failed: {e}")
            batch_failures.append({"itemIdentifier": record.get("messageId")})
    return {"batchItemFailures": batch_failures}


def _job_ids_from_record(record, service):
    """Resolve every job id an SQS record maps to.

    A direct API record is a single bare job id; an S3 event body may carry
    multiple ``Records`` (S3 batches notifications), so every ``aws:s3`` record
    is handled. Any exception still fails the whole SQS record via
    batchItemFailures.
    """
    body = record.get("body", "") or ""
    # Direct API path: body is a bare job_id.
    if body and "{" not in body:
        return [body]
    # Producer path: S3 event (possibly wrapped by SQS) -> one job per s3 record.
    msg = json.loads(body)
    job_ids = []
    for s3rec in msg.get("Records", []):
        if s3rec.get("eventSource") == "aws:s3":
            job_id = _ingest_dropped_object(s3rec, service)
            if job_id:
                job_ids.append(job_id)
    return job_ids


def _ingest_dropped_object(rec, service):
    import urllib.parse

    full_key = urllib.parse.unquote_plus(rec["s3"]["object"]["key"])
    prefix = (AwsIngestSettings().ingest_blob_s3_prefix or "").strip("/")
    logical = full_key[len(prefix) + 1:] if prefix and full_key.startswith(prefix + "/") else full_key
    # Invert make_key. Default is the "{job_id}/{filename}" split, so this is
    # byte-identical for stock deployments; a store that prefixes keys overrides
    # both make_key and parse_job_id, so a prefixed presign key still resolves.
    job_id = service.blobstore.parse_job_id(logical)

    existing = service.jobstore.get(job_id)
    if existing is not None:
        # Presign path: the client's upload just landed, so hand the pre-created
        # job (status UPLOADING) off to the worker. Claim the UPLOADING -> QUEUED
        # transition atomically: a redelivered S3 event must never reset a
        # PROCESSING/terminal job (the inline/base64 path writes its retention
        # blob to this same bucket but is driven by a direct enqueue). Only the
        # caller that wins the claim returns the job id.
        if service.jobstore.claim(
            job_id, from_statuses={JobStatus.UPLOADING}, to_status=JobStatus.QUEUED
        ):
            return job_id
        return None

    # Raw producer drop (Phase 2 path): create a Job from the object's metadata.
    # Object metadata is producer-asserted, not authenticated identity; the
    # bucket write policy is the only boundary on this path, so it can be
    # disabled entirely for deployments that require verified callers.
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
    import urllib.parse
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
    # The presign intake percent-encodes a non-ASCII filename before pinning it
    # into object metadata; unquote it back to the original here. A plain name
    # (no "%") is unchanged, so producer drops with unquoted names still work.
    filename = (
        urllib.parse.unquote(meta["filename"])
        if "filename" in meta
        else logical.rsplit("/", 1)[-1]
    )
    job = Job(
        job_id=str(uuid.uuid4()),
        status=JobStatus.QUEUED,
        namespace=namespace,
        source="producer",
        filename=filename,
        content_type=meta.get("content_type", "application/octet-stream"),
        requested_by=requested_by,
        blob_key=logical,
        metadata={},
        created_at=now,
        updated_at=now,
    )
    service.jobstore.create(job)
    return job.job_id

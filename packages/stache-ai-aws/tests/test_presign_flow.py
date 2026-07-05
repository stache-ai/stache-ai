"""Presign + async-tier behavior against the real AWS providers (moto):
worker presign linking, idempotent claims, double-trigger dedup, and the
upload/capture API routes on the async backend.
"""

import asyncio
import json
import os
import types
import urllib.parse
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from stache_ai.ingestion.base import Job, JobStatus
from stache_ai.ingestion.factory import IngestionServiceFactory, reset_ingestion_service
import stache_ai.ingestion.factory as factory_mod

from stache_ai_aws import sqs_worker

REGION = "us-east-1"
JOBS_TABLE = "p3-ingest-jobs"
BUCKET = "p3-originals"
QUEUE = "p3-ingest-queue"


@pytest.fixture(autouse=True)
def _aws_credentials(monkeypatch):
    """Presigning requires real (dummy) credentials even under moto. Pin the
    blob prefix so the worker's key mapping is deterministic."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    monkeypatch.setenv("INGEST_BLOB_S3_PREFIX", "originals")


def _provision():
    ddb = boto3.client("dynamodb", region_name=REGION)
    ddb.create_table(
        TableName=JOBS_TABLE,
        BillingMode="PAY_PER_REQUEST",
        KeySchema=[{"AttributeName": "job_id", "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": "job_id", "AttributeType": "S"},
            {"AttributeName": "GSI1PK", "AttributeType": "S"},
            {"AttributeName": "GSI1SK", "AttributeType": "S"},
            {"AttributeName": "GSI2PK", "AttributeType": "S"},
            {"AttributeName": "GSI2SK", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {"IndexName": "GSI1",
             "KeySchema": [{"AttributeName": "GSI1PK", "KeyType": "HASH"},
                           {"AttributeName": "GSI1SK", "KeyType": "RANGE"}],
             "Projection": {"ProjectionType": "ALL"}},
            {"IndexName": "GSI2",
             "KeySchema": [{"AttributeName": "GSI2PK", "KeyType": "HASH"},
                           {"AttributeName": "GSI2SK", "KeyType": "RANGE"}],
             "Projection": {"ProjectionType": "ALL"}},
        ],
    )
    boto3.client("s3", region_name=REGION).create_bucket(Bucket=BUCKET)
    return boto3.client("sqs", region_name=REGION).create_queue(QueueName=QUEUE)["QueueUrl"]


def _config(queue_url):
    return types.SimpleNamespace(
        ingest_queue_provider="sqs",
        ingest_jobstore_provider="dynamodb",
        ingest_blob_provider="s3",
        ingest_intake_provider="s3presign",
        ingest_notifier_provider="null",
        ingest_queue_sqs_url=queue_url,
        ingest_jobstore_dynamodb_table=JOBS_TABLE,
        ingest_blob_s3_bucket=BUCKET,
        ingest_blob_s3_prefix="originals",
        ingest_intake_s3_presign_expiry=3600,
        aws_region=REGION,
    )


def _pipeline():
    p = AsyncMock()
    p.ingest_text.return_value = {"doc_id": "doc-async", "action": "ingested_new", "chunks_created": 4}
    p.ingest_file.return_value = {"doc_id": "doc-file", "chunks_created": 8}
    return p


def _drive(service, body):
    factory_mod._service = service
    try:
        return sqs_worker.lambda_handler(
            {"Records": [{"messageId": "m1", "body": body}]}, None
        )
    finally:
        reset_ingestion_service()


@mock_aws
def test_worker_resumes_presign_job():
    queue_url = _provision()
    pipeline = _pipeline()
    service = IngestionServiceFactory.build(_config(queue_url), pipeline)

    # Pre-create an UPLOADING job via begin_upload, then drop the bytes at the
    # presign key and feed the S3 event.
    job, ticket = asyncio.run(
        service.begin_upload(
            namespace="docs", content_type="text", requested_by="bob",
            filename="f.txt",
        )
    )
    assert job.status == JobStatus.UPLOADING
    boto3.client("s3", region_name=REGION).put_object(
        Bucket=BUCKET, Key=f"originals/{job.blob_key}", Body=b"hello",
    )
    s3_event = {"Records": [{"eventSource": "aws:s3",
                             "s3": {"object": {"key": f"originals/{job.blob_key}"}}}]}
    resp = _drive(service, json.dumps(s3_event))

    assert resp == {"batchItemFailures": []}
    done = service.get_job(job.job_id)
    assert done.status == JobStatus.DONE
    # Presign jobs carry no inline _text, so the worker reads the blob and uses
    # ingest_file (doc-file), proving the upload was linked to the pre-created job.
    assert done.doc_id == "doc-file"
    assert pipeline.ingest_file.await_count == 1
    # No duplicate job created.
    jobs, _ = service.list_jobs(limit=50)
    assert len(jobs) == 1


@mock_aws
def test_presign_required_headers_pin_all_signed_metadata():
    # S3 folds ContentType AND every x-amz-meta-* header into the SigV4
    # signature, so the ticket must ask the client to echo all of them back or
    # the PUT fails SignatureDoesNotMatch (regression: only Content-Type was
    # returned -> every upload 403'd).
    queue_url = _provision()
    service = IngestionServiceFactory.build(_config(queue_url), _pipeline())
    _job, ticket = asyncio.run(service.begin_upload(
        namespace="docs", content_type="application/pdf", requested_by="bob",
        filename="f.pdf",
    ))
    h = ticket.required_headers
    assert h["Content-Type"] == "application/pdf"
    assert h["x-amz-meta-stache-namespace"] == "docs"
    assert h["x-amz-meta-stache-requested_by"] == "bob"
    assert h["x-amz-meta-stache-filename"] == "f.pdf"


@mock_aws
def test_presign_non_ascii_filename_pinned_as_ascii():
    # The pinned x-amz-meta-stache-filename is folded into the SigV4 signature AND
    # echoed back by the browser on the PUT; browsers reject non-ISO-8859-1 header
    # values, so a non-ASCII name (résumé.pdf) must be percent-encoded to pure
    # ASCII. required_headers carries the SAME value that was signed.
    queue_url = _provision()
    service = IngestionServiceFactory.build(_config(queue_url), _pipeline())
    _job, ticket = asyncio.run(service.begin_upload(
        namespace="docs", content_type="application/pdf", requested_by="bob",
        filename="résumé.pdf",
    ))
    fname = ticket.required_headers["x-amz-meta-stache-filename"]
    assert fname.isascii()
    fname.encode("latin-1")   # ISO-8859-1-encodable => browser will not reject it
    assert fname == urllib.parse.quote("résumé.pdf", safe="")
    # An ASCII name stays human-readable (not gratuitously encoded).
    _job2, ticket2 = asyncio.run(service.begin_upload(
        namespace="docs", content_type="application/pdf", requested_by="bob",
        filename="plain report.pdf",
    ))
    assert ticket2.required_headers["x-amz-meta-stache-filename"] == "plain report.pdf"


@mock_aws
def test_presign_key_matches_blob_key_for_pathy_filename():
    # A filename containing "/" must presign the SAME key the worker later reads
    # (both collapse to the basename), else the upload lands at a key nobody reads.
    queue_url = _provision()
    service = IngestionServiceFactory.build(_config(queue_url), _pipeline())
    job, ticket = asyncio.run(service.begin_upload(
        namespace="docs", content_type="application/pdf", requested_by="bob",
        filename="a/b/evil.pdf",
    ))
    assert job.blob_key == f"{job.job_id}/evil.pdf"
    assert f"{job.job_id}/evil.pdf" in ticket.upload_url
    assert "a/b/evil.pdf" not in ticket.upload_url


@mock_aws
def test_worker_unknown_job_creates_producer_job():
    queue_url = _provision()
    pipeline = _pipeline()
    service = IngestionServiceFactory.build(_config(queue_url), pipeline)

    boto3.client("s3", region_name=REGION).put_object(
        Bucket=BUCKET, Key="originals/Z/f.pdf", Body=b"producer bytes",
        Metadata={"stache-namespace": "news", "stache-filename": "f.pdf",
                  "stache-requested_by": "media", "stache-content_type": "text"},
    )
    s3_event = {"Records": [{"eventSource": "aws:s3",
                             "s3": {"object": {"key": "originals/Z/f.pdf"}}}]}
    resp = _drive(service, json.dumps(s3_event))

    assert resp == {"batchItemFailures": []}
    jobs, _ = service.list_jobs(limit=50)
    assert len(jobs) == 1
    assert jobs[0].source == "producer"
    assert jobs[0].status in (JobStatus.DONE, JobStatus.SKIPPED)


@mock_aws
def test_worker_skips_already_terminal_presign_redelivery():
    queue_url = _provision()
    pipeline = _pipeline()
    service = IngestionServiceFactory.build(_config(queue_url), pipeline)

    # Pre-create a job already in DONE.
    now = datetime.now(timezone.utc).isoformat()
    service.jobstore.create(Job(
        job_id="DONEJOB", status=JobStatus.DONE, namespace="docs", source="api",
        filename="f.pdf", content_type="text", requested_by="bob",
        blob_key="DONEJOB/f.pdf", doc_id="already", created_at=now, updated_at=now,
    ))

    rec = {"s3": {"object": {"key": "originals/DONEJOB/f.pdf"}}}
    result = sqs_worker._ingest_dropped_object(rec, service)
    assert result is None
    # Pipeline was never invoked for re-delivery.
    assert pipeline.ingest_text.await_count == 0
    assert pipeline.ingest_file.await_count == 0


@mock_aws
def test_jobstore_claim_is_atomic_single_winner():
    """DynamoJobStore.claim: exactly one caller wins the QUEUED->PROCESSING CAS."""
    _provision()
    store = IngestionServiceFactory.build(_config("unused"), _pipeline()).jobstore
    now = datetime.now(timezone.utc).isoformat()
    store.create(Job(
        job_id="J1", status=JobStatus.QUEUED, namespace="docs", source="api",
        filename="f.txt", content_type="text", requested_by="bob",
        created_at=now, updated_at=now,
    ))
    first = store.claim("J1", from_statuses={JobStatus.QUEUED, JobStatus.UPLOADING})
    second = store.claim("J1", from_statuses={JobStatus.QUEUED, JobStatus.UPLOADING})
    assert first is True and second is False
    assert store.get("J1").status == JobStatus.PROCESSING
    # A claim against a terminal job also loses.
    store.update("J1", status=JobStatus.DONE)
    assert store.claim("J1", from_statuses={JobStatus.QUEUED, JobStatus.UPLOADING}) is False
    # Missing job -> False, never raises.
    assert store.claim("nope", from_statuses={JobStatus.QUEUED}) is False


@mock_aws
def test_base64_double_trigger_ingests_once():
    """The inline base64 path writes its blob to the originals bucket (fires an S3
    event) AND direct-enqueues. Both deliveries target the same job; the claim
    must ensure the pipeline runs exactly once and no duplicate job is created."""
    queue_url = _provision()
    pipeline = _pipeline()
    service = IngestionServiceFactory.build(_config(queue_url), pipeline)

    job = asyncio.run(service.submit(
        namespace="docs", content_type="application/pdf", requested_by="bob",
        filename="f.pdf", data=b"%PDF-1.4 body", chunking_strategy="auto",
    ))
    # The job exists (created before the blob write) and its retention blob landed.
    assert service.get_job(job.job_id).blob_key == f"{job.job_id}/f.pdf"

    # Deliver BOTH triggers: the direct enqueue (bare job_id) and the S3 event.
    _drive(service, job.job_id)
    s3_event = {"Records": [{"eventSource": "aws:s3",
                             "s3": {"object": {"key": f"originals/{job.blob_key}"}}}]}
    _drive(service, json.dumps(s3_event))

    assert pipeline.ingest_file.await_count == 1     # ingested exactly once
    jobs, _ = service.list_jobs(limit=50)
    assert len(jobs) == 1                             # no duplicate/producer job
    assert jobs[0].status == JobStatus.DONE


@mock_aws
def test_producer_metadata_hyphen_keys_populate_job():
    """Producers may tag objects with hyphenated stache-* keys; content_type and
    requested_by must survive (regression: they silently fell back to defaults)."""
    queue_url = _provision()
    service = IngestionServiceFactory.build(_config(queue_url), _pipeline())
    boto3.client("s3", region_name=REGION).put_object(
        Bucket=BUCKET, Key="originals/Z/f.pdf", Body=b"producer bytes",
        Metadata={"stache-namespace": "news", "stache-filename": "f.pdf",
                  "stache-requested-by": "media", "stache-content-type": "application/pdf"},
    )
    s3_event = {"Records": [{"eventSource": "aws:s3",
                             "s3": {"object": {"key": "originals/Z/f.pdf"}}}]}
    _drive(service, json.dumps(s3_event))

    jobs, _ = service.list_jobs(limit=50)
    assert len(jobs) == 1
    assert jobs[0].requested_by == "media"           # not the "producer" default
    assert jobs[0].content_type == "application/pdf"  # not application/octet-stream


# ---------------------------------------------------------------------------
# Routes on the async backend
# ---------------------------------------------------------------------------


@mock_aws
def test_route_ingest_upload_presign_returns_url():
    queue_url = _provision()
    service = IngestionServiceFactory.build(_config(queue_url), _pipeline())
    from stache_ai.api.main import app
    with patch("stache_ai.api.routes.ingest.get_ingestion_service", return_value=service):
        client = TestClient(app)
        resp = client.post("/api/ingest", json={
            "upload": True, "filename": "big.pdf",
            "content_type": "application/pdf", "namespace": "docs",
        })
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "uploading"
    assert body["upload_url"]
    assert body["required_headers"]["Content-Type"] == "application/pdf"


@mock_aws
def test_route_list_jobs_garbage_cursor_returns_400():
    # A malformed pagination cursor must be a client error (400), not a 500 from
    # a base64/json decode blowing up inside the jobstore.
    queue_url = _provision()
    service = IngestionServiceFactory.build(_config(queue_url), _pipeline())
    from stache_ai.api.main import app
    with patch("stache_ai.api.routes.ingest.get_ingestion_service", return_value=service):
        client = TestClient(app)
        resp = client.get("/api/jobs", params={"cursor": "not-valid-base64!!!"})
    assert resp.status_code == 400


@mock_aws
def test_route_capture_wait_mode_on_async_backend():
    """/api/capture blocks server-side (wait-mode) until the worker completes,
    so doc_id/chunks_created come back populated even on the SQS backend."""
    queue_url = _provision()
    pipeline = _pipeline()
    service = IngestionServiceFactory.build(_config(queue_url), pipeline)

    # Drive the worker out-of-band on enqueue so wait-mode sees terminal.
    orig_enqueue = service.queue.enqueue

    async def enqueue_then_process(job_id):
        await orig_enqueue(job_id)
        await service.process_job(job_id)

    service.queue.enqueue = enqueue_then_process

    from stache_ai.api.main import app
    with patch("stache_ai.api.routes.capture.get_ingestion_service", return_value=service):
        client = TestClient(app)
        resp = client.post("/api/capture", json={"text": "captured note", "namespace": "docs"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["doc_id"] == "doc-async"
    assert body["chunks_created"] == 4

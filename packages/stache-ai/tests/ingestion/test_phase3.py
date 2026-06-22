"""Phase 3 tests: wait-mode submit, begin_upload (presign), worker presign
linking, and the upload/wait API routes.

Uses moto + the real AWS providers (entry points) where presign / async are
needed; AsyncMock pipelines + stub seams elsewhere.
"""

import asyncio
import json
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def _aws_credentials():
    """Presigning requires real (dummy) credentials even under moto."""
    keys = {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_SECURITY_TOKEN": "testing",
        "AWS_SESSION_TOKEN": "testing",
        "AWS_DEFAULT_REGION": "us-east-1",
    }
    saved = {k: os.environ.get(k) for k in keys}
    os.environ.update(keys)
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
from fastapi.testclient import TestClient

from stache_ai.config import Settings
from stache_ai.ingestion.base import (
    IntakeTicket,
    Job,
    JobStatus,
)
from stache_ai.ingestion.factory import IngestionService, IngestionServiceFactory

# ---------------------------------------------------------------------------
# Stub seams for direct IngestionService construction
# ---------------------------------------------------------------------------


class _DictJobStore:
    """Minimal in-memory JobStore for unit tests."""

    def __init__(self):
        self.jobs = {}

    def create(self, job):
        self.jobs[job.job_id] = job

    def update(self, job_id, **fields):
        job = self.jobs[job_id]
        for k, v in fields.items():
            setattr(job, k, v)
        return job

    def get(self, job_id):
        return self.jobs.get(job_id)

    def list(self, *, requested_by=None, status=None, limit=50, cursor=None):
        items = list(self.jobs.values())
        return items, None


class _NoopQueue:
    """Queue that does nothing (leaves jobs in their submitted state)."""

    async def enqueue(self, job_id):
        return None


class _InlineCompleteQueue:
    """Queue that immediately marks the job DONE (sync-like)."""

    def __init__(self, jobstore):
        self.jobstore = jobstore

    async def enqueue(self, job_id):
        self.jobstore.update(
            job_id, status=JobStatus.DONE, doc_id="doc-x", chunks_created=2
        )


class _StubIntake:
    def __init__(self, ticket):
        self.ticket = ticket
        self.calls = []

    def begin(self, **kwargs):
        self.calls.append(kwargs)
        return self.ticket


def _service(*, jobstore=None, queue=None, intake=None):
    jobstore = jobstore or _DictJobStore()
    return IngestionService(
        intake=intake or _StubIntake(IntakeTicket(job_id="x")),
        queue=queue if queue is not None else _InlineCompleteQueue(jobstore),
        jobstore=jobstore,
        blobstore=AsyncMock(),
        notifier=AsyncMock(),
        worker=None,
    )


# ---------------------------------------------------------------------------
# wait-mode
# ---------------------------------------------------------------------------


def test_submit_wait_inline_returns_terminal():
    """Inline tier: queue completes the job; wait is a no-op returning terminal."""
    js = _DictJobStore()
    svc = _service(jobstore=js, queue=_InlineCompleteQueue(js))
    job = asyncio.run(
        svc.submit(
            namespace="default", content_type="text", requested_by="alice",
            text="hi", wait=True,
        )
    )
    assert job.status == JobStatus.DONE
    assert job.doc_id == "doc-x"


def test_submit_wait_polls_to_terminal():
    """Async-style: queue does NOT complete; an external mutation flips the job
    to terminal after a poll, and wait-mode picks it up."""
    js = _DictJobStore()
    svc = _service(jobstore=js, queue=_NoopQueue())

    real_get = js.get
    state = {"polls": 0}

    def mutating_get(job_id):
        job = real_get(job_id)
        if job and job.status == JobStatus.QUEUED:
            state["polls"] += 1
            if state["polls"] >= 2:
                job.status = JobStatus.DONE
                job.doc_id = "doc-late"
        return job

    js.get = mutating_get
    job = asyncio.run(
        svc.submit(
            namespace="default", content_type="text", requested_by="alice",
            text="hi", wait=True, wait_timeout=2.0, poll_interval=0.05,
        )
    )
    assert job.status == JobStatus.DONE
    assert job.doc_id == "doc-late"


def test_submit_wait_timeout_returns_last_non_terminal():
    """Never-completing job returns the last non-terminal state after timeout."""
    js = _DictJobStore()
    svc = _service(jobstore=js, queue=_NoopQueue())
    job = asyncio.run(
        svc.submit(
            namespace="default", content_type="text", requested_by="alice",
            text="hi", wait=True, wait_timeout=0.2, poll_interval=0.05,
        )
    )
    assert job.status == JobStatus.QUEUED


# ---------------------------------------------------------------------------
# begin_upload
# ---------------------------------------------------------------------------


def test_begin_upload_creates_uploading_job_and_ticket():
    js = _DictJobStore()
    intake = _StubIntake(
        IntakeTicket(job_id="ignored", upload_url="https://s3/put", required_headers={"Content-Type": "application/pdf"})
    )
    svc = _service(jobstore=js, intake=intake)
    job, ticket = asyncio.run(
        svc.begin_upload(
            namespace="docs", content_type="application/pdf",
            requested_by="bob", filename="big.pdf",
        )
    )
    assert job.status == JobStatus.UPLOADING
    assert job.blob_key == f"{job.job_id}/big.pdf"
    assert ticket.upload_url == "https://s3/put"
    assert js.get(job.job_id) is job


def test_begin_upload_sanitizes_filename_to_basename():
    js = _DictJobStore()
    intake = _StubIntake(IntakeTicket(job_id="x", upload_url="https://s3/put"))
    svc = _service(jobstore=js, intake=intake)
    job, _ = asyncio.run(
        svc.begin_upload(
            namespace="docs", content_type="application/pdf",
            requested_by="bob", filename="../../etc/passwd",
        )
    )
    assert job.blob_key == f"{job.job_id}/passwd"


def test_begin_upload_raises_without_upload_url():
    intake = _StubIntake(IntakeTicket(job_id="x", upload_url=None))
    svc = _service(intake=intake)
    with pytest.raises(ValueError, match="presigned upload"):
        asyncio.run(
            svc.begin_upload(
                namespace="docs", content_type="application/pdf",
                requested_by="bob", filename="big.pdf",
            )
        )


# ---------------------------------------------------------------------------
# Worker presign linking + idempotency (moto + real AWS providers)
# ---------------------------------------------------------------------------

from stache_ai.providers import plugin_loader  # noqa: E402

_HAVE_AWS = (
    "s3" in plugin_loader.get_available_providers("ingest_blob")
    and "sqs" in plugin_loader.get_available_providers("ingest_queue")
    and "dynamodb" in plugin_loader.get_available_providers("ingest_jobstore")
    and "s3presign" in plugin_loader.get_available_providers("ingest_intake")
)

aws_only = pytest.mark.skipif(
    not _HAVE_AWS, reason="stache-ai-aws / stache-ai-dynamodb not installed"
)

if _HAVE_AWS:
    moto = pytest.importorskip("moto")
    boto3 = pytest.importorskip("boto3")
    from moto import mock_aws

    REGION = "us-east-1"
    JOBS_TABLE = "p3-ingest-jobs"
    BUCKET = "p3-originals"
    QUEUE = "p3-ingest-queue"

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

    def _settings(queue_url):
        return Settings(
            ingest_queue_provider="sqs",
            ingest_jobstore_provider="dynamodb",
            ingest_blob_provider="s3",
            ingest_intake_provider="s3presign",
            ingest_queue_sqs_url=queue_url,
            ingest_jobstore_dynamodb_table=JOBS_TABLE,
            ingest_blob_s3_bucket=BUCKET,
            ingest_blob_s3_prefix="originals",
            aws_region=REGION,
        )

    def _pipeline():
        p = AsyncMock()
        p.ingest_text.return_value = {"doc_id": "doc-async", "action": "ingested_new", "chunks_created": 4}
        p.ingest_file.return_value = {"doc_id": "doc-file", "chunks_created": 8}
        return p

    def _drive(service, body):
        from stache_ai.ingestion import sqs_worker
        from stache_ai.ingestion.factory import reset_ingestion_service
        import stache_ai.ingestion.factory as factory_mod
        factory_mod._service = service
        try:
            return sqs_worker.lambda_handler(
                {"Records": [{"messageId": "m1", "body": body}]}, None
            )
        finally:
            reset_ingestion_service()


@aws_only
@mock_aws
def test_worker_resumes_presign_job():
    queue_url = _provision()
    pipeline = _pipeline()
    service = IngestionServiceFactory.build(_settings(queue_url), pipeline)

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


@aws_only
@mock_aws
def test_worker_unknown_job_creates_producer_job():
    queue_url = _provision()
    pipeline = _pipeline()
    service = IngestionServiceFactory.build(_settings(queue_url), pipeline)

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


@aws_only
@mock_aws
def test_worker_skips_already_terminal_presign_redelivery():
    queue_url = _provision()
    pipeline = _pipeline()
    service = IngestionServiceFactory.build(_settings(queue_url), pipeline)

    # Pre-create a job already in DONE.
    now = datetime.now(timezone.utc).isoformat()
    service.jobstore.create(Job(
        job_id="DONEJOB", status=JobStatus.DONE, namespace="docs", source="api",
        filename="f.pdf", content_type="text", requested_by="bob",
        blob_key="DONEJOB/f.pdf", doc_id="already", created_at=now, updated_at=now,
    ))

    from stache_ai.ingestion.sqs_worker import _ingest_dropped_object
    rec = {"s3": {"object": {"key": "originals/DONEJOB/f.pdf"}}}
    with patch("stache_ai.config.settings", _settings(queue_url)):
        result = _ingest_dropped_object(rec, service)
    assert result is None
    # Pipeline was never invoked for re-delivery.
    assert pipeline.ingest_text.await_count == 0
    assert pipeline.ingest_file.await_count == 0


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@pytest.fixture
def inline_service(tmp_path):
    p = AsyncMock()
    p.ingest_text.return_value = {"doc_id": "doc-1", "action": "ingested_new", "chunks_created": 3}
    p.ingest_file.return_value = {"doc_id": "doc-file", "chunks_created": 9}
    cfg = Settings(
        ingest_blob_provider="filesystem",
        ingest_blob_root=str(tmp_path / "blobs"),
    )
    return IngestionServiceFactory.build(cfg, p)


def test_route_ingest_wait_text_terminal(inline_service):
    from stache_ai.api.main import app
    with patch("stache_ai.api.routes.ingest.get_ingestion_service", return_value=inline_service):
        client = TestClient(app)
        resp = client.post("/api/ingest", json={"wait": True, "text": "hello"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "done"
    assert resp.json()["doc_id"] == "doc-1"


def test_route_ingest_upload_on_inline_intake_is_400(inline_service):
    from stache_ai.api.main import app
    with patch("stache_ai.api.routes.ingest.get_ingestion_service", return_value=inline_service):
        client = TestClient(app)
        resp = client.post("/api/ingest", json={
            "upload": True, "filename": "big.pdf", "content_type": "application/pdf",
        })
    assert resp.status_code == 400
    assert "presigned upload" in resp.json()["detail"]


def test_route_ingest_upload_requires_filename(inline_service):
    from stache_ai.api.main import app
    with patch("stache_ai.api.routes.ingest.get_ingestion_service", return_value=inline_service):
        client = TestClient(app)
        resp = client.post("/api/ingest", json={"upload": True, "content_type": "application/pdf"})
    assert resp.status_code == 400
    assert "filename" in resp.json()["detail"]


@aws_only
@mock_aws
def test_route_ingest_upload_presign_returns_url():
    queue_url = _provision()
    service = IngestionServiceFactory.build(_settings(queue_url), _pipeline())
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


@aws_only
@mock_aws
def test_route_capture_wait_mode_on_async_backend():
    """/api/capture blocks server-side (wait-mode) until the worker completes,
    so doc_id/chunks_created come back populated even on the SQS backend."""
    queue_url = _provision()
    pipeline = _pipeline()
    service = IngestionServiceFactory.build(_settings(queue_url), pipeline)

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

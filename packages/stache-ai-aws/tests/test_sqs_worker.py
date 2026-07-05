"""Tests for the SQS worker Lambda handler (no live AWS; stub seams)."""

import json
from unittest.mock import AsyncMock

from stache_ai.config import Settings
from stache_ai.ingestion.base import BlobStore, Job, JobStatus
from stache_ai.ingestion.factory import IngestionService
from stache_ai.ingestion.providers.inline import (
    EphemeralJobStore,
    InlineIntake,
    InlineQueue,
    NullNotifier,
)
from stache_ai.ingestion.worker import make_worker

from stache_ai_aws import sqs_worker


def _mock_pipeline():
    p = AsyncMock()
    p.ingest_text.return_value = {"doc_id": "doc-1", "action": "ingested_new", "chunks_created": 2}
    p.ingest_file.return_value = {"doc_id": "doc-2", "chunks_created": 5}
    return p


class FakeBlobStore(BlobStore):
    """Returns canned bytes/metadata for the producer (S3 drop) path."""

    def __init__(self, meta):
        self._meta = meta

    def put(self, key, data, metadata):
        return key

    def get(self, key):
        return b"%PDF fake bytes", self._meta

    def head(self, key):
        return self._meta


def _build_service(pipeline, *, blobstore=None, jobstore=None):
    jobstore = jobstore or EphemeralJobStore()
    blobstore = blobstore or FakeBlobStore({})
    notifier = NullNotifier()
    worker = make_worker(jobstore, blobstore, notifier, pipeline)
    return IngestionService(
        intake=InlineIntake(),
        queue=InlineQueue(worker),
        jobstore=jobstore,
        blobstore=blobstore,
        notifier=notifier,
        worker=worker,
    )


def test_bare_job_id_record_processed(monkeypatch):
    jobstore = EphemeralJobStore()
    service = _build_service(_mock_pipeline(), jobstore=jobstore)
    # Pre-create a QUEUED text job.
    job = Job(
        job_id="job-abc", status=JobStatus.QUEUED, namespace="n",
        source="api", filename="text", content_type="text",
        requested_by="alice", metadata={"_text": "hi", "_chunking": "recursive"},
        created_at="t0", updated_at="t0",
    )
    jobstore.create(job)
    monkeypatch.setattr(sqs_worker, "get_ingestion_service", lambda: service)

    event = {"Records": [{"messageId": "m1", "body": "job-abc"}]}
    resp = sqs_worker.lambda_handler(event, None)

    assert resp == {"batchItemFailures": []}
    assert jobstore.get("job-abc").status == JobStatus.DONE


def test_s3_event_record_creates_producer_job(monkeypatch):
    jobstore = EphemeralJobStore()
    blob = FakeBlobStore({
        "namespace": "n", "filename": "f.pdf",
        "requested_by": "u", "content_type": "application/pdf",
    })
    service = _build_service(_mock_pipeline(), blobstore=blob, jobstore=jobstore)
    monkeypatch.setattr(sqs_worker, "get_ingestion_service", lambda: service)
    # The prefix is read from this package's env-backed settings.
    monkeypatch.setenv("INGEST_BLOB_S3_PREFIX", "originals")

    s3_body = json.dumps({
        "Records": [{
            "eventSource": "aws:s3",
            "s3": {"object": {"key": "originals/producers/f.pdf"}},
        }]
    })
    event = {"Records": [{"messageId": "m2", "body": s3_body}]}
    resp = sqs_worker.lambda_handler(event, None)

    assert resp == {"batchItemFailures": []}
    jobs, _ = jobstore.list()
    assert len(jobs) == 1
    created = jobs[0]
    assert created.source == "producer"
    assert created.namespace == "n"
    assert created.filename == "f.pdf"
    assert created.blob_key == "producers/f.pdf"
    assert created.status == JobStatus.DONE


def test_producer_job_unquotes_encoded_filename(monkeypatch):
    # The presign intake percent-encodes a non-ASCII filename into object
    # metadata; the producer path must unquote it back to the original name.
    import urllib.parse

    original = "résumé.pdf"
    jobstore = EphemeralJobStore()
    blob = FakeBlobStore({
        "namespace": "n", "filename": urllib.parse.quote(original, safe=""),
        "requested_by": "u", "content_type": "application/pdf",
    })
    service = _build_service(_mock_pipeline(), blobstore=blob, jobstore=jobstore)
    monkeypatch.setattr(sqs_worker, "get_ingestion_service", lambda: service)
    monkeypatch.setenv("INGEST_BLOB_S3_PREFIX", "originals")

    s3_body = json.dumps({"Records": [
        {"eventSource": "aws:s3", "s3": {"object": {"key": "originals/producers/enc.pdf"}}},
    ]})
    resp = sqs_worker.lambda_handler({"Records": [{"messageId": "m", "body": s3_body}]}, None)

    assert resp == {"batchItemFailures": []}
    jobs, _ = jobstore.list()
    assert len(jobs) == 1
    assert jobs[0].filename == original


def test_failing_record_appears_in_batch_failures(monkeypatch):
    # A service whose process_job raises -> record reported as a batch failure.
    class BadService:
        def process_job(self, job_id):
            raise RuntimeError("kaboom")

    monkeypatch.setattr(sqs_worker, "get_ingestion_service", lambda: BadService())
    event = {"Records": [{"messageId": "bad-1", "body": "job-x"}]}
    resp = sqs_worker.lambda_handler(event, None)
    assert resp == {"batchItemFailures": [{"itemIdentifier": "bad-1"}]}


def test_redelivery_while_processing_does_not_reset(monkeypatch):
    # A duplicate S3 event for a job already PROCESSING must lose the
    # UPLOADING->QUEUED claim and leave the job untouched (no double ingestion).
    jobstore = EphemeralJobStore()
    service = _build_service(_mock_pipeline(), jobstore=jobstore)
    monkeypatch.setenv("INGEST_BLOB_S3_PREFIX", "originals")
    jobstore.create(Job(
        job_id="job-proc", status=JobStatus.PROCESSING, namespace="n",
        source="api", filename="f.pdf", content_type="application/pdf",
        requested_by="bob", blob_key="job-proc/f.pdf",
        created_at="t0", updated_at="t0",
    ))
    rec = {"s3": {"object": {"key": "originals/job-proc/f.pdf"}}}
    assert sqs_worker._ingest_dropped_object(rec, service) is None
    assert jobstore.get("job-proc").status == JobStatus.PROCESSING


def test_two_s3_records_both_processed(monkeypatch):
    # An S3 notification body may carry multiple Records; every aws:s3 record
    # must be handled, not just the first.
    jobstore = EphemeralJobStore()
    blob = FakeBlobStore({
        "namespace": "n", "filename": "f.pdf",
        "requested_by": "u", "content_type": "application/pdf",
    })
    service = _build_service(_mock_pipeline(), blobstore=blob, jobstore=jobstore)
    monkeypatch.setattr(sqs_worker, "get_ingestion_service", lambda: service)
    monkeypatch.setenv("INGEST_BLOB_S3_PREFIX", "originals")

    s3_body = json.dumps({"Records": [
        {"eventSource": "aws:s3", "s3": {"object": {"key": "originals/a/f1.pdf"}}},
        {"eventSource": "aws:s3", "s3": {"object": {"key": "originals/b/f2.pdf"}}},
    ]})
    resp = sqs_worker.lambda_handler({"Records": [{"messageId": "m", "body": s3_body}]}, None)

    assert resp == {"batchItemFailures": []}
    jobs, _ = jobstore.list()
    assert len(jobs) == 2
    assert all(j.source == "producer" for j in jobs)


def test_producer_drop_disabled_creates_no_job(monkeypatch):
    # With INGEST_PRODUCER_DROPS_ENABLED=false a raw drop is ignored (message
    # consumed, no job created).
    import stache_ai.config as cfg

    jobstore = EphemeralJobStore()
    blob = FakeBlobStore({
        "namespace": "n", "filename": "f.pdf",
        "requested_by": "u", "content_type": "application/pdf",
    })
    service = _build_service(_mock_pipeline(), blobstore=blob, jobstore=jobstore)
    monkeypatch.setattr(sqs_worker, "get_ingestion_service", lambda: service)
    monkeypatch.setenv("INGEST_BLOB_S3_PREFIX", "originals")
    monkeypatch.setattr(cfg, "settings", Settings(ingest_producer_drops_enabled=False))

    s3_body = json.dumps({"Records": [
        {"eventSource": "aws:s3", "s3": {"object": {"key": "originals/Z/f.pdf"}}},
    ]})
    resp = sqs_worker.lambda_handler({"Records": [{"messageId": "m", "body": s3_body}]}, None)

    assert resp == {"batchItemFailures": []}
    jobs, _ = jobstore.list()
    assert jobs == []


def test_dedup_skipped(monkeypatch):
    pipeline = _mock_pipeline()
    pipeline.ingest_text.return_value = {"doc_id": "dup", "action": "skipped", "chunks_created": 0}
    jobstore = EphemeralJobStore()
    service = _build_service(pipeline, jobstore=jobstore)
    job = Job(
        job_id="job-dup", status=JobStatus.QUEUED, namespace="n",
        source="api", filename="text", content_type="text",
        requested_by="alice", metadata={"_text": "dup", "_chunking": "recursive"},
        created_at="t0", updated_at="t0",
    )
    jobstore.create(job)
    monkeypatch.setattr(sqs_worker, "get_ingestion_service", lambda: service)

    resp = sqs_worker.lambda_handler({"Records": [{"messageId": "m3", "body": "job-dup"}]}, None)
    assert resp == {"batchItemFailures": []}
    assert jobstore.get("job-dup").status == JobStatus.SKIPPED

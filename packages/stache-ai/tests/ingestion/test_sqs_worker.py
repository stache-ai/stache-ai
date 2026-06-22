"""Tests for the SQS worker Lambda handler (provider-agnostic, no live AWS)."""

import json
from unittest.mock import AsyncMock

import pytest

from stache_ai.config import Settings
from stache_ai.ingestion import sqs_worker
from stache_ai.ingestion.base import BlobStore, Job, JobStatus
from stache_ai.ingestion.factory import IngestionService
from stache_ai.ingestion.providers.inline import (
    EphemeralJobStore,
    InlineIntake,
    InlineQueue,
    NullNotifier,
)
from stache_ai.ingestion.worker import make_worker


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
    # _ingest_dropped_object reads `from stache_ai.config import settings`; patch there.
    import stache_ai.config as cfg
    monkeypatch.setattr(cfg, "settings", Settings(ingest_blob_s3_prefix="originals"))

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


def test_failing_record_appears_in_batch_failures(monkeypatch):
    # A service whose process_job raises -> record reported as a batch failure.
    class BadService:
        def process_job(self, job_id):
            raise RuntimeError("kaboom")

    monkeypatch.setattr(sqs_worker, "get_ingestion_service", lambda: BadService())
    event = {"Records": [{"messageId": "bad-1", "body": "job-x"}]}
    resp = sqs_worker.lambda_handler(event, None)
    assert resp == {"batchItemFailures": [{"itemIdentifier": "bad-1"}]}


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

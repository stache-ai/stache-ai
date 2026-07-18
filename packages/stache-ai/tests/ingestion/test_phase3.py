"""Phase 3 tests: wait-mode submit, begin_upload (presign), and the
upload/wait API routes, all against stub seams and the inline tier.

The async-provider variants (presign linking, idempotent claims, routes on the
async backend) live in the plugin packages' test suites.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from stache_ai.config import Settings
from stache_ai.ingestion.base import (
    IntakeTicket,
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

    def create(self, job, *, principal=None):
        self.jobs[job.job_id] = job

    def update(self, job_id, **fields):
        job = self.jobs[job_id]
        for k, v in fields.items():
            setattr(job, k, v)
        return job

    def get(self, job_id):
        return self.jobs.get(job_id)

    def claim(self, job_id, *, from_statuses, to_status=None):
        job = self.jobs.get(job_id)
        if job is None or job.status not in from_statuses:
            return False
        job.status = to_status or JobStatus.PROCESSING
        return True

    def list(self, *, requested_by=None, status=None, limit=50, cursor=None, principal=None):
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
        # Mirror the real intake: report the key it presigned so the factory
        # records the identical blob_key (the worker inverts it via parse_job_id).
        import os
        from dataclasses import replace
        key = f"{kwargs['job_id']}/{os.path.basename(kwargs['filename'])}"
        return replace(self.ticket, blob_key=key)


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
        IntakeTicket(job_id="ignored", upload_url="https://blobs/put", required_headers={"Content-Type": "application/pdf"})
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
    assert ticket.upload_url == "https://blobs/put"
    assert js.get(job.job_id) is job


def test_begin_upload_sanitizes_filename_to_basename():
    js = _DictJobStore()
    intake = _StubIntake(IntakeTicket(job_id="x", upload_url="https://blobs/put"))
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


def test_default_make_key_parse_job_id_round_trip():
    """make_key and parse_job_id are inverses -- the invariant the async worker
    relies on to recover the job from an object-created event. A store that
    overrides one MUST override both, or a prefixed key strands the job."""
    from stache_ai.ingestion.base import BlobStore

    class _Default(BlobStore):
        def put(self, key, data, metadata): return key
        def get(self, key): return b"", {}

    s = _Default()
    for job_id, filename in [("abc-123", "file.pdf"), ("j0", "notes.txt")]:
        assert s.parse_job_id(s.make_key(job_id, filename)) == job_id

    class _Prefixed(BlobStore):
        def put(self, key, data, metadata): return key
        def get(self, key): return b"", {}
        def make_key(self, job_id, filename, *, principal=None):
            return f"acme/{job_id}/{filename}"
        def parse_job_id(self, key):
            return key.split("/")[1]

    p = _Prefixed()
    assert p.parse_job_id(p.make_key("xyz", "f.pdf")) == "xyz"

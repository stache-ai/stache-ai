"""Tests for the Principal identity seam (Workstream 0)."""

import asyncio
from unittest.mock import AsyncMock

from stache_ai.identity import ANONYMOUS, Principal, assert_can_write


def test_principal_of_normalizes_string():
    p = Principal.of("user-1")
    assert p.user_id == "user-1"
    assert p.claims == {}
    assert not p.is_anonymous


def test_principal_of_none_is_anonymous():
    p = Principal.of(None)
    assert p.user_id == ANONYMOUS
    assert p.is_anonymous


def test_principal_of_passthrough():
    p = Principal(user_id="u", claims={"scope": "x"})
    assert Principal.of(p) is p


def test_assert_can_write_is_noop_stub():
    assert assert_can_write(Principal(user_id="u"), "ns") is None


def test_api_principal_extracts_sub_and_opaque_claims():
    from stache_ai.api import auth

    class _Req:
        scope = {"aws.event": {"requestContext": {"authorizer": {"jwt": {"claims": {
            "sub": "abc", "custom:anything": "opaque-value"}}}}}}

    p = auth.principal(_Req())
    assert isinstance(p, Principal)
    assert p.user_id == "abc"
    # Claims pass through opaquely; core attaches no meaning to any key.
    assert p.claims["custom:anything"] == "opaque-value"


def test_api_principal_anonymous_without_event():
    from stache_ai.api import auth

    class _Req:
        scope = {}

    p = auth.principal(_Req())
    assert p.is_anonymous


def test_submit_normalizes_principal_and_stores_user_id():
    """service.submit accepts a Principal; Job.requested_by stores user_id and
    the opaque principal reaches jobstore.create and blobstore.make_key."""
    from stache_ai.ingestion.base import IntakeTicket, JobStatus
    from stache_ai.ingestion.factory import IngestionService

    seen = {}

    class _Store:
        def __init__(self):
            self.jobs = {}

        def create(self, job, *, principal=None):
            seen["create_principal"] = principal
            self.jobs[job.job_id] = job

        def update(self, job_id, **fields):
            job = self.jobs[job_id]
            for k, v in fields.items():
                setattr(job, k, v)
            return job

        def get(self, job_id):
            return self.jobs.get(job_id)

        def claim(self, job_id, *, from_statuses, to_status=None):
            return True

        def list(self, **kw):
            return list(self.jobs.values()), None

    class _Blob:
        def make_key(self, job_id, filename, *, principal=None):
            seen["make_key_principal"] = principal
            return f"custom/{job_id}/{filename}"

        def put(self, key, data, metadata):
            seen["put_key"] = key
            return key

        def get(self, key):
            return b"", {}

    class _Intake:
        def begin(self, **kwargs):
            seen["intake_kwargs"] = kwargs
            return IntakeTicket(job_id=kwargs["job_id"])

    class _Queue:
        async def enqueue(self, job_id):
            return None

    svc = IngestionService(
        intake=_Intake(), queue=_Queue(), jobstore=_Store(),
        blobstore=_Blob(), notifier=AsyncMock(), worker=None,
    )
    caller = Principal(user_id="alice", claims={"ext": "opaque"})
    job = asyncio.run(svc.submit(
        namespace="ns", content_type="application/pdf", requested_by=caller,
        filename="f.pdf", data=b"bytes",
    ))
    assert job.requested_by == "alice"
    assert job.status == JobStatus.QUEUED
    assert seen["create_principal"] is caller
    assert seen["make_key_principal"] is caller
    assert seen["intake_kwargs"]["principal"] is caller
    assert seen["intake_kwargs"]["requested_by"] == "alice"
    # Overridden make_key controls the blob key end-to-end.
    assert job.blob_key == f"custom/{job.job_id}/f.pdf"
    assert seen["put_key"] == job.blob_key


def test_worker_passes_context_and_job_to_pipeline():
    """The worker threads a RequestContext (user + opaque job) into the pipeline."""
    from stache_ai.ingestion.base import Job, JobStatus
    from stache_ai.ingestion.worker import make_worker

    job = Job(
        job_id="j1", status=JobStatus.QUEUED, namespace="ns", source="api",
        filename="note", content_type="text", requested_by="alice",
        metadata={"_text": "hello world"},
    )

    class _Store:
        def get(self, job_id):
            return job

        def claim(self, job_id, *, from_statuses, to_status=None):
            return True

        def update(self, job_id, **fields):
            for k, v in fields.items():
                setattr(job, k, v)
            return job

    pipeline = AsyncMock()
    pipeline.ingest_text.return_value = {"doc_id": "d1", "chunks_created": 1}
    notifier = type("N", (), {"publish": lambda self, e: None})()

    worker = make_worker(_Store(), AsyncMock(), notifier, pipeline)
    asyncio.run(worker("j1"))

    ctx = pipeline.ingest_text.call_args.kwargs["context"]
    assert ctx.user_id == "alice"
    assert ctx.namespace == "ns"
    assert ctx.source == "worker"
    assert ctx.custom["ingest_job"] is job
    assert job.status == JobStatus.DONE

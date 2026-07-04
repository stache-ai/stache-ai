"""Tests for entry-point discovery of async ingestion providers + worker wiring."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from stache_ai.config import Settings
from stache_ai.ingestion.base import (
    BlobStore,
    JobStatus,
    JobStore,
    Notifier,
    QueueProvider,
)
from stache_ai.ingestion.factory import IngestionServiceFactory
from stache_ai.providers import plugin_loader


def _mock_pipeline():
    p = AsyncMock()
    p.ingest_text.return_value = {"doc_id": "doc-1", "action": "ingested_new", "chunks_created": 2}
    p.ingest_file.return_value = {"doc_id": "doc-2", "chunks_created": 5}
    return p


class DummyJobStore(JobStore):
    def __init__(self, config):
        self.config = config
        self._jobs = {}

    def create(self, job, *, principal=None):
        self._jobs[job.job_id] = job

    def update(self, job_id, **fields):
        job = self._jobs[job_id]
        for k, v in fields.items():
            setattr(job, k, v)
        return job

    def get(self, job_id):
        return self._jobs.get(job_id)

    def list(self, *, requested_by=None, status=None, limit=50, cursor=None, principal=None):
        return list(self._jobs.values())[:limit], None


class DummyBlobStore(BlobStore):
    def __init__(self, config):
        self.config = config

    def put(self, key, data, metadata):
        return key

    def get(self, key):
        return b"", {}


class DummyNotifier(Notifier):
    def __init__(self, config):
        self.config = config

    def publish(self, event):
        pass


class DummyQueue(QueueProvider):
    def __init__(self, config):
        self.config = config

    async def enqueue(self, job_id):
        pass


@pytest.fixture(autouse=True)
def _reset_plugin_cache():
    yield
    plugin_loader.reset()


def test_factory_discovers_registered_jobstore():
    plugin_loader.register_provider("ingest_jobstore", "dummy", DummyJobStore)
    cfg = Settings(ingest_jobstore_provider="dummy")
    service = IngestionServiceFactory.build(cfg, _mock_pipeline())
    assert isinstance(service.jobstore, DummyJobStore)


def test_factory_discovers_registered_blob_notifier_queue():
    plugin_loader.register_provider("ingest_blob", "dummy", DummyBlobStore)
    plugin_loader.register_provider("ingest_notifier", "dummy", DummyNotifier)
    plugin_loader.register_provider("ingest_queue", "dummy", DummyQueue)
    cfg = Settings(
        ingest_blob_provider="dummy",
        ingest_notifier_provider="dummy",
        ingest_queue_provider="dummy",
    )
    service = IngestionServiceFactory.build(cfg, _mock_pipeline())
    assert isinstance(service.blobstore, DummyBlobStore)
    assert isinstance(service.notifier, DummyNotifier)
    assert isinstance(service.queue, DummyQueue)


def test_factory_attaches_worker_and_process_job_awaits_it():
    pipeline = _mock_pipeline()
    service = IngestionServiceFactory.build(Settings(), pipeline)
    assert service.worker is not None

    # Pre-create a job, then drive it via process_job (inline tier worker).
    job = asyncio.run(service.submit(
        namespace="default", content_type="text", requested_by="alice", text="hello",
    ))
    # Re-process the same job through process_job; worker is awaited.
    asyncio.run(service.process_job(job.job_id))
    assert service.get_job(job.job_id).status in (JobStatus.DONE, JobStatus.SKIPPED)

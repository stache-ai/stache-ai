"""Tests for the factory wiring + IngestionService facade (sync tier)."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from stache_ai.config import Settings
from stache_ai.ingestion.base import IngestTextTooLargeError, JobStatus
from stache_ai.ingestion.factory import IngestionServiceFactory


def _mock_pipeline():
    p = AsyncMock()
    p.ingest_text.return_value = {"doc_id": "doc-1", "action": "ingested_new", "chunks_created": 2}
    p.ingest_file.return_value = {"doc_id": "doc-2", "chunks_created": 5}
    return p


def test_factory_builds_default_sync_tier():
    service = IngestionServiceFactory.build(Settings(), _mock_pipeline())
    from stache_ai.ingestion.providers.inline import (
        EphemeralJobStore,
        InlineIntake,
        InlineQueue,
        NullBlobStore,
        NullNotifier,
    )
    assert isinstance(service.jobstore, EphemeralJobStore)
    assert isinstance(service.blobstore, NullBlobStore)
    assert isinstance(service.notifier, NullNotifier)
    assert isinstance(service.intake, InlineIntake)
    assert isinstance(service.queue, InlineQueue)


def test_factory_self_hosted_tier(tmp_path):
    cfg = Settings(
        ingest_jobstore_provider="sqlite",
        ingest_blob_provider="filesystem",
        ingest_jobstore_sqlite_path=str(tmp_path / "jobs.db"),
        ingest_blob_root=str(tmp_path / "blobs"),
    )
    service = IngestionServiceFactory.build(cfg, _mock_pipeline())
    from stache_ai.ingestion.providers.inline import FilesystemBlobStore, SqliteJobStore
    assert isinstance(service.jobstore, SqliteJobStore)
    assert isinstance(service.blobstore, FilesystemBlobStore)


@pytest.mark.parametrize("field", [
    "ingest_queue_provider",
    "ingest_jobstore_provider",
    "ingest_blob_provider",
])
def test_factory_rejects_unknown_provider(field):
    # An uninstalled/unknown provider name fails discovery with a clear error.
    cfg = Settings(**{field: "nonexistent-xyz"})
    with pytest.raises(ValueError, match="Unknown ingestion"):
        IngestionServiceFactory.build(cfg, _mock_pipeline())


def test_submit_text_is_born_terminal():
    service = IngestionServiceFactory.build(Settings(), _mock_pipeline())
    job = asyncio.run(service.submit(
        namespace="default", content_type="text", requested_by="alice",
        text="a quick note",
    ))
    assert job.status == JobStatus.DONE
    assert job.doc_id == "doc-1"
    assert job.chunks_created == 2
    assert job.requested_by == "alice"
    # Retrievable + scoped
    assert service.get_job(job.job_id).job_id == job.job_id
    jobs, _ = service.list_jobs(requested_by="alice")
    assert len(jobs) == 1


def test_submit_dedup_is_skipped():
    pipeline = _mock_pipeline()
    pipeline.ingest_text.return_value = {"doc_id": "dup", "action": "skipped", "chunks_created": 0}
    service = IngestionServiceFactory.build(Settings(), pipeline)
    job = asyncio.run(service.submit(
        namespace="default", content_type="text", requested_by="alice", text="dup",
    ))
    assert job.status == JobStatus.SKIPPED
    assert job.doc_id == "dup"


def test_submit_file_via_filesystem_blob(tmp_path):
    cfg = Settings(ingest_blob_provider="filesystem", ingest_blob_root=str(tmp_path / "blobs"))
    pipeline = _mock_pipeline()
    service = IngestionServiceFactory.build(cfg, pipeline)
    job = asyncio.run(service.submit(
        namespace="default", content_type="application/pdf", requested_by="alice",
        filename="r.pdf", data=b"%PDF fake bytes",
    ))
    assert job.status == JobStatus.DONE
    assert job.doc_id == "doc-2"
    pipeline.ingest_file.assert_awaited_once()


def test_submit_requires_text_or_data():
    service = IngestionServiceFactory.build(Settings(), _mock_pipeline())
    with pytest.raises(ValueError, match="text or data"):
        asyncio.run(service.submit(
            namespace="default", content_type="text", requested_by="alice",
        ))


def test_submit_honors_jobstore_inline_payload_cap():
    # A jobstore that declares a per-item cap (e.g. DynamoDB's 400KB) must reject
    # oversized text at submit (mapped to 413) instead of 500ing on the backend
    # write. The effective cap is the smaller of the config and jobstore limits.
    service = IngestionServiceFactory.build(Settings(), _mock_pipeline())
    service.jobstore.max_inline_payload_bytes = 16
    with pytest.raises(IngestTextTooLargeError, match="16-byte"):
        asyncio.run(service.submit(
            namespace="default", content_type="text", requested_by="alice",
            text="x" * 32,
        ))
    # Text within the cap still submits normally.
    job = asyncio.run(service.submit(
        namespace="default", content_type="text", requested_by="alice", text="ok",
    ))
    assert job.status == JobStatus.DONE

"""Unit tests for the provider-agnostic ingestion worker."""

import asyncio
from unittest.mock import AsyncMock

from stache_ai.ingestion.base import Job, JobStatus
from stache_ai.ingestion.providers.inline import EphemeralJobStore, NullNotifier
from stache_ai.ingestion.worker import make_worker


class _Blob:
    def __init__(self, data=b"file-bytes"):
        self._data = data

    def put(self, key, data, metadata):
        return key

    def get(self, key):
        return self._data, {}


def _text_job(metadata):
    return Job(
        job_id="j1", status=JobStatus.QUEUED, namespace="default", source="api",
        filename="note.txt", content_type="text", requested_by="alice",
        metadata=metadata, created_at="t", updated_at="t",
    )


def test_worker_text_success_marks_done():
    store = EphemeralJobStore()
    job = _text_job({"_text": "hello world", "_chunking": "recursive", "topic": "x"})
    store.create(job)

    pipeline = AsyncMock()
    pipeline.ingest_text.return_value = {
        "doc_id": "doc-1", "action": "ingested_new", "chunks_created": 4,
    }
    worker = make_worker(store, _Blob(), NullNotifier(), pipeline)
    asyncio.run(worker("j1"))

    done = store.get("j1")
    assert done.status == JobStatus.DONE
    assert done.doc_id == "doc-1"
    assert done.chunks_created == 4
    # transport keys stripped, real metadata preserved
    call_md = pipeline.ingest_text.call_args.kwargs["metadata"]
    assert call_md == {"topic": "x"}
    assert pipeline.ingest_text.call_args.kwargs["chunking_strategy"] == "recursive"


def test_worker_dedup_marks_skipped():
    store = EphemeralJobStore()
    store.create(_text_job({"_text": "dup"}))
    pipeline = AsyncMock()
    pipeline.ingest_text.return_value = {"doc_id": "existing", "action": "skipped", "chunks_created": 0}
    worker = make_worker(store, _Blob(), NullNotifier(), pipeline)
    asyncio.run(worker("j1"))

    job = store.get("j1")
    assert job.status == JobStatus.SKIPPED
    assert job.doc_id == "existing"


def test_worker_failure_marks_failed():
    store = EphemeralJobStore()
    store.create(_text_job({"_text": "boom"}))
    pipeline = AsyncMock()
    pipeline.ingest_text.side_effect = RuntimeError("embedding exploded")
    worker = make_worker(store, _Blob(), NullNotifier(), pipeline)
    asyncio.run(worker("j1"))

    job = store.get("j1")
    assert job.status == JobStatus.FAILED
    assert "embedding exploded" in job.error_detail


def test_worker_file_path_uses_ingest_file_and_blob():
    store = EphemeralJobStore()
    job = Job(
        job_id="j2", status=JobStatus.QUEUED, namespace="default", source="api",
        filename="report.pdf", content_type="application/pdf", requested_by="alice",
        blob_key="j2/report.pdf", metadata={}, created_at="t", updated_at="t",
    )
    store.create(job)
    pipeline = AsyncMock()
    # ingest_file returns no "action" key -> should become DONE
    pipeline.ingest_file.return_value = {"doc_id": "doc-2", "chunks_created": 7}
    worker = make_worker(store, _Blob(b"%PDF-1.4 fake"), NullNotifier(), pipeline)
    asyncio.run(worker("j2"))

    done = store.get("j2")
    assert done.status == JobStatus.DONE
    assert done.doc_id == "doc-2"
    assert done.chunks_created == 7
    pipeline.ingest_file.assert_awaited_once()
    assert pipeline.ingest_file.call_args.kwargs["metadata"]["filename"] == "report.pdf"


def test_worker_missing_job_is_noop():
    store = EphemeralJobStore()
    pipeline = AsyncMock()
    worker = make_worker(store, _Blob(), NullNotifier(), pipeline)
    asyncio.run(worker("does-not-exist"))  # must not raise
    pipeline.ingest_text.assert_not_called()


def test_worker_passes_prepend_metadata():
    store = EphemeralJobStore()
    store.create(_text_job({"_text": "hi", "_prepend_metadata": ["topic"], "topic": "faith"}))
    pipeline = AsyncMock()
    pipeline.ingest_text.return_value = {"doc_id": "d", "action": "ingested_new", "chunks_created": 1}
    worker = make_worker(store, _Blob(), NullNotifier(), pipeline)
    asyncio.run(worker("j1"))

    kwargs = pipeline.ingest_text.call_args.kwargs
    assert kwargs["prepend_metadata"] == ["topic"]
    assert "_prepend_metadata" not in kwargs["metadata"]

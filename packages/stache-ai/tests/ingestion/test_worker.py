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


def test_worker_strips_all_reserved_keys_not_just_transport_keys():
    """Any `_`-prefixed job.metadata key (server-stamped state, not just the
    transport keys) must never reach the pipeline's metadata kwarg - the
    worker rehydrates that state from context.custom["ingest_job"] instead."""
    store = EphemeralJobStore()
    job = _text_job({
        "_text": "hello world",
        "_chunking": "recursive",
        "_stamped": "server-set-state",
        "topic": "x",
    })
    store.create(job)

    pipeline = AsyncMock()
    pipeline.ingest_text.return_value = {
        "doc_id": "doc-1", "action": "ingested_new", "chunks_created": 4,
    }
    worker = make_worker(store, _Blob(), NullNotifier(), pipeline)
    asyncio.run(worker("j1"))

    call_md = pipeline.ingest_text.call_args.kwargs["metadata"]
    assert "_stamped" not in call_md
    assert call_md == {"topic": "x"}


def test_worker_strips_reserved_keys_from_file_ingestion_metadata():
    """Same guarantee on the ingest_file path: reserved keys never ride
    along, but `filename` (set by the worker itself) still does."""
    store = EphemeralJobStore()
    job = Job(
        job_id="j2", status=JobStatus.QUEUED, namespace="default", source="api",
        filename="report.pdf", content_type="application/pdf", requested_by="alice",
        blob_key="j2/report.pdf",
        metadata={"_stamped": "server-set-state", "author": "alice"},
        created_at="t", updated_at="t",
    )
    store.create(job)
    pipeline = AsyncMock()
    pipeline.ingest_file.return_value = {"doc_id": "doc-2", "chunks_created": 7}
    worker = make_worker(store, _Blob(b"%PDF-1.4 fake"), NullNotifier(), pipeline)
    asyncio.run(worker("j2"))

    call_md = pipeline.ingest_file.call_args.kwargs["metadata"]
    assert "_stamped" not in call_md
    assert call_md["author"] == "alice"
    assert call_md["filename"] == "report.pdf"


def test_worker_strips_content_hash_matching_sanitizer(monkeypatch):
    """INGESTION F2: the worker's reserved-key filter is the SAME predicate the
    API sanitizer uses (sanitize.is_reserved_metadata_key), so a non-underscore
    reserved key like ``content_hash`` is stripped by BOTH - they cannot drift.
    ``source_path`` (not reserved - a smart-update identifier) still rides
    along to the pipeline."""
    from stache_ai import sanitize

    store = EphemeralJobStore()
    job = _text_job({
        "_text": "hello world",
        "content_hash": "forged-by-somebody",
        "source_path": "notes/todo.md",
        "topic": "x",
    })
    store.create(job)

    pipeline = AsyncMock()
    pipeline.ingest_text.return_value = {
        "doc_id": "doc-1", "action": "ingested_new", "chunks_created": 1,
    }
    worker = make_worker(store, _Blob(), NullNotifier(), pipeline)
    asyncio.run(worker("j1"))

    call_md = pipeline.ingest_text.call_args.kwargs["metadata"]
    # content_hash is reserved (the sanitizer strips it too) -> gone here.
    assert "content_hash" not in call_md
    assert sanitize.is_reserved_metadata_key("content_hash")
    # source_path is a legitimate smart-update identifier, not reserved.
    assert not sanitize.is_reserved_metadata_key("source_path")
    assert call_md == {"source_path": "notes/todo.md", "topic": "x"}


def test_worker_strips_transport_keys_on_terminal():
    # The terminal job record must not retain the document body (_text) or other
    # transport-only keys, so GET /api/jobs / DynamoDB items stay small.
    store = EphemeralJobStore()
    store.create(_text_job({
        "_text": "hello world", "_chunking": "recursive",
        "_prepend_metadata": ["topic"], "topic": "x",
    }))
    pipeline = AsyncMock()
    pipeline.ingest_text.return_value = {"doc_id": "d", "action": "ingested_new", "chunks_created": 1}
    worker = make_worker(store, _Blob(), NullNotifier(), pipeline)
    asyncio.run(worker("j1"))

    md = store.get("j1").metadata
    assert "_text" not in md
    assert "_chunking" not in md
    assert "_prepend_metadata" not in md
    assert md == {"topic": "x"}


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
    # Even on failure the terminal record drops the transport-only body.
    assert "_text" not in job.metadata


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

"""Unit tests for the sync-tier ingestion providers (no AWS)."""

import asyncio

import pytest

from stache_ai.ingestion.base import Job, JobStatus
from stache_ai.ingestion.providers.inline import (
    EphemeralJobStore,
    FilesystemBlobStore,
    InlineIntake,
    InlineQueue,
    NullBlobStore,
    NullNotifier,
    SqliteJobStore,
)


def make_job(job_id="j1", requested_by="alice", status=JobStatus.QUEUED, created_at="2026-06-20T00:00:00"):
    return Job(
        job_id=job_id,
        status=status,
        namespace="default",
        source="api",
        filename="note.txt",
        content_type="text",
        requested_by=requested_by,
        created_at=created_at,
        updated_at=created_at,
    )


# ---- Job model ----

def test_job_round_trip_dict():
    job = make_job()
    d = job.to_dict()
    assert d["status"] == "queued"  # serialized to value
    restored = Job.from_dict(d)
    assert restored == job


def test_job_from_dict_ignores_unknown_keys():
    d = make_job().to_dict()
    d["bogus_future_field"] = 123
    restored = Job.from_dict(d)
    assert restored.job_id == "j1"


# ---- BlobStore ----

def test_null_blobstore_retains_nothing():
    store = NullBlobStore()
    assert store.put("k", b"data", {}) == "k"
    with pytest.raises(KeyError):
        store.get("k")


def test_filesystem_blobstore_round_trip(tmp_path):
    store = FilesystemBlobStore(str(tmp_path / "blobs"))
    key = store.put("abc/file.bin", b"hello", {"filename": "file.bin"})
    data, meta = store.get(key)
    assert data == b"hello"
    assert meta["filename"] == "file.bin"


def test_filesystem_blobstore_rejects_traversal(tmp_path):
    store = FilesystemBlobStore(str(tmp_path / "blobs"))
    with pytest.raises(ValueError):
        store.put("../escape.bin", b"x", {})


# ---- EphemeralJobStore ----

def test_ephemeral_crud_and_filters():
    store = EphemeralJobStore()
    store.create(make_job("a", "alice", created_at="2026-06-20T01:00:00"))
    store.create(make_job("b", "bob", created_at="2026-06-20T02:00:00"))
    store.create(make_job("c", "alice", status=JobStatus.DONE, created_at="2026-06-20T03:00:00"))

    assert store.get("a").requested_by == "alice"

    alice_jobs, cursor = store.list(requested_by="alice")
    assert cursor is None
    assert [j.job_id for j in alice_jobs] == ["c", "a"]  # newest first

    done_jobs, _ = store.list(status=JobStatus.DONE)
    assert [j.job_id for j in done_jobs] == ["c"]

    updated = store.update("a", status=JobStatus.DONE, doc_id="doc-1")
    assert updated.status == JobStatus.DONE
    assert store.get("a").doc_id == "doc-1"


def test_ephemeral_list_limit():
    store = EphemeralJobStore()
    for i in range(5):
        store.create(make_job(f"j{i}", created_at=f"2026-06-20T0{i}:00:00"))
    jobs, _ = store.list(limit=2)
    assert len(jobs) == 2


# ---- SqliteJobStore ----

def test_sqlite_crud_and_filters(tmp_path):
    store = SqliteJobStore(str(tmp_path / "jobs.db"))
    store.create(make_job("a", "alice", created_at="2026-06-20T01:00:00"))
    store.create(make_job("b", "bob", created_at="2026-06-20T02:00:00"))

    assert store.get("a").requested_by == "alice"
    assert store.get("missing") is None

    store.update("a", status=JobStatus.DONE, doc_id="doc-9", chunks_created=3)
    reloaded = store.get("a")
    assert reloaded.status == JobStatus.DONE
    assert reloaded.doc_id == "doc-9"
    assert reloaded.chunks_created == 3

    alice_jobs, _ = store.list(requested_by="alice")
    assert [j.job_id for j in alice_jobs] == ["a"]

    done_jobs, _ = store.list(status=JobStatus.DONE)
    assert [j.job_id for j in done_jobs] == ["a"]


def test_sqlite_update_missing_raises(tmp_path):
    store = SqliteJobStore(str(tmp_path / "jobs.db"))
    with pytest.raises(KeyError):
        store.update("nope", status=JobStatus.DONE)


def test_sqlite_persists_across_instances(tmp_path):
    path = str(tmp_path / "jobs.db")
    SqliteJobStore(path).create(make_job("a", "alice"))
    # New instance, same file
    reopened = SqliteJobStore(path)
    assert reopened.get("a").requested_by == "alice"


def test_sqlite_list_stuck(tmp_path):
    store = SqliteJobStore(str(tmp_path / "jobs.db"))
    old = make_job("old", status=JobStatus.PROCESSING, created_at="2026-06-19T00:00:00")
    old.updated_at = "2026-06-19T00:00:00"
    store.create(old)
    fresh = make_job("fresh", status=JobStatus.PROCESSING, created_at="2026-06-20T12:00:00")
    fresh.updated_at = "2026-06-20T12:00:00"
    store.create(fresh)
    done = make_job("done", status=JobStatus.DONE, created_at="2026-06-19T00:00:00")
    done.updated_at = "2026-06-19T00:00:00"
    store.create(done)

    stuck = store.list_stuck("2026-06-20T00:00:00")
    assert [j.job_id for j in stuck] == ["old"]  # fresh too recent, done not active


def test_ephemeral_list_stuck_default_empty():
    assert EphemeralJobStore().list_stuck("2026-06-20T00:00:00") == []


# ---- InlineQueue / InlineIntake / NullNotifier ----

def test_inline_queue_runs_worker_synchronously():
    ran = []

    async def worker(job_id):
        ran.append(job_id)

    queue = InlineQueue(worker)
    asyncio.run(queue.enqueue("j1"))
    assert ran == ["j1"]


def test_inline_intake_returns_no_upload_url():
    ticket = InlineIntake().begin(
        job_id="j1", filename="x", namespace="default",
        content_type="text", size=0, requested_by="alice", metadata={},
    )
    assert ticket.job_id == "j1"
    assert ticket.upload_url is None


def test_null_notifier_is_noop():
    NullNotifier().publish(object())  # must not raise

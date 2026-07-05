"""Tests for the provider-agnostic stuck-job reaper."""

from datetime import datetime, timedelta, timezone

from stache_ai.config import Settings
from stache_ai.ingestion.base import Job, JobStatus
from stache_ai.ingestion.factory import IngestionService
from stache_ai.ingestion.providers.inline import (
    InlineIntake,
    NullBlobStore,
    NullNotifier,
    SqliteJobStore,
)
from stache_ai.ingestion.reaper import reap_stuck_jobs


def _job(job_id, status, updated_at):
    return Job(
        job_id=job_id, status=status, namespace="n", source="api",
        filename="f", content_type="text", requested_by="alice",
        created_at=updated_at, updated_at=updated_at,
    )


def _build_service(jobstore):
    return IngestionService(
        intake=InlineIntake(),
        queue=None,
        jobstore=jobstore,
        blobstore=NullBlobStore(),
        notifier=NullNotifier(),
        worker=None,
    )


def test_reaper_fails_stuck_jobs_only(tmp_path, monkeypatch):
    jobstore = SqliteJobStore(str(tmp_path / "jobs.db"))
    now = datetime.now(timezone.utc)
    old = (now - timedelta(minutes=120)).isoformat()
    fresh = now.isoformat()

    jobstore.create(_job("stuck", JobStatus.PROCESSING, old))
    jobstore.create(_job("fresh", JobStatus.PROCESSING, fresh))
    jobstore.create(_job("done", JobStatus.DONE, old))

    service = _build_service(jobstore)

    import stache_ai.config as cfg
    monkeypatch.setattr(cfg, "settings", Settings(ingest_reaper_stuck_minutes=30))

    assert reap_stuck_jobs(service) == 1
    stuck = jobstore.get("stuck")
    assert stuck.status == JobStatus.FAILED
    assert "reaped" in stuck.error_detail
    assert jobstore.get("fresh").status == JobStatus.PROCESSING
    assert jobstore.get("done").status == JobStatus.DONE


def test_reaper_skips_job_that_went_terminal(tmp_path, monkeypatch):
    # list_stuck reads an eventually-consistent GSI: a job it reports may already
    # be DONE. The claim must lose and the job must be left untouched, not flipped
    # to FAILED (and not counted).
    jobstore = SqliteJobStore(str(tmp_path / "jobs.db"))
    now = datetime.now(timezone.utc)
    old = (now - timedelta(minutes=120)).isoformat()

    jobstore.create(_job("stuck", JobStatus.PROCESSING, old))
    jobstore.create(_job("raced", JobStatus.DONE, old))   # already terminal in the store

    service = _build_service(jobstore)
    import stache_ai.config as cfg
    monkeypatch.setattr(cfg, "settings", Settings(ingest_reaper_stuck_minutes=30))

    # Stale GSI view: "raced" still looks PROCESSING to the reaper's list_stuck.
    raced_stale = _job("raced", JobStatus.PROCESSING, old)
    monkeypatch.setattr(
        jobstore, "list_stuck",
        lambda cutoff: [jobstore.get("stuck"), raced_stale],
    )

    assert reap_stuck_jobs(service) == 1                    # only the genuinely-stuck job
    assert jobstore.get("stuck").status == JobStatus.FAILED
    assert jobstore.get("raced").status == JobStatus.DONE   # claim lost -> untouched


def test_reaper_strips_inline_text_on_failed_job(tmp_path, monkeypatch):
    # A reaped text job must drop its inline _text (matching the worker's terminal
    # updates), else the body leaks and strains the jobstore item cap.
    jobstore = SqliteJobStore(str(tmp_path / "jobs.db"))
    now = datetime.now(timezone.utc)
    old = (now - timedelta(minutes=120)).isoformat()

    job = _job("stuck-text", JobStatus.PROCESSING, old)
    job.metadata = {"_text": "a big inline body", "_chunking": "recursive", "tag": "keep"}
    jobstore.create(job)

    service = _build_service(jobstore)
    import stache_ai.config as cfg
    monkeypatch.setattr(cfg, "settings", Settings(ingest_reaper_stuck_minutes=30))

    assert reap_stuck_jobs(service) == 1
    reaped = jobstore.get("stuck-text")
    assert reaped.status == JobStatus.FAILED
    assert "_text" not in reaped.metadata
    assert "_chunking" not in reaped.metadata
    assert reaped.metadata == {"tag": "keep"}   # non-transport metadata preserved

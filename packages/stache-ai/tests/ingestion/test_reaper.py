"""Tests for the scheduled reaper Lambda handler."""

from datetime import datetime, timedelta, timezone

from stache_ai.config import Settings
from stache_ai.ingestion import reaper
from stache_ai.ingestion.base import Job, JobStatus
from stache_ai.ingestion.factory import IngestionService
from stache_ai.ingestion.providers.inline import (
    InlineIntake,
    NullBlobStore,
    NullNotifier,
    SqliteJobStore,
)


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
    monkeypatch.setattr(reaper, "get_ingestion_service", lambda: service)

    import stache_ai.config as cfg
    monkeypatch.setattr(cfg, "settings", Settings(ingest_reaper_stuck_minutes=30))

    result = reaper.lambda_handler({}, None)

    assert result == {"reaped": 1}
    stuck = jobstore.get("stuck")
    assert stuck.status == JobStatus.FAILED
    assert "reaped" in stuck.error_detail
    assert jobstore.get("fresh").status == JobStatus.PROCESSING
    assert jobstore.get("done").status == JobStatus.DONE

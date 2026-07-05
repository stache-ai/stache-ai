"""Scheduled reaper for the async ingestion tier.

Marks jobs wedged in a non-terminal state past ``INGEST_REAPER_STUCK_MINUTES``
as ``failed`` (retryable). Provider-agnostic: works through the JobStore seam.
Per design Decision 10 it does not auto-re-enqueue; originals are retained, so
recovery is a client/ops re-drop.

Deployment entrypoints (cron, scheduled cloud functions) live in the plugin
packages and call :func:`reap_stuck_jobs`.
"""

import logging
from datetime import datetime, timedelta, timezone

from .base import JobStatus, strip_transport
from .factory import get_ingestion_service

logger = logging.getLogger(__name__)


def reap_stuck_jobs(service=None) -> int:
    """Fail every job stuck in a non-terminal state past the configured TTL.

    Returns the number of jobs reaped.
    """
    from stache_ai.config import settings

    service = service or get_ingestion_service()
    cutoff = (
        datetime.now(timezone.utc) - timedelta(minutes=settings.ingest_reaper_stuck_minutes)
    ).isoformat()
    stuck = service.jobstore.list_stuck(cutoff)
    now = datetime.now(timezone.utc).isoformat()
    reaped = 0
    for job in stuck:
        # list_stuck reads an eventually-consistent GSI, so a job it reports may
        # already have reached a terminal state. Gate the FAILED transition on an
        # atomic claim so we never flip a DONE/SKIPPED job to FAILED; only jobs
        # still non-terminal at claim time are counted and annotated.
        if not service.jobstore.claim(
            job.job_id,
            from_statuses={JobStatus.QUEUED, JobStatus.UPLOADING, JobStatus.PROCESSING},
            to_status=JobStatus.FAILED,
        ):
            continue
        service.jobstore.update(
            job.job_id,
            error_detail="reaped: stuck past TTL (retryable)",
            # Drop the inline document body on the terminal record, matching the
            # worker's terminal updates: a reaper-failed text job would otherwise
            # keep _text and leak it / strain the jobstore item cap.
            metadata=strip_transport(job.metadata),
            completed_at=now,
        )
        logger.warning(f"[reaper] failed stuck job {job.job_id} (was {job.status.value})")
        reaped += 1
    return reaped

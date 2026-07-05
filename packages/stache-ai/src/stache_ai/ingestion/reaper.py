"""Scheduled reaper Lambda for the async ingestion tier.

Marks jobs wedged in a non-terminal state past ``INGEST_REAPER_STUCK_MINUTES``
as ``failed`` (retryable). Provider-agnostic: works through the JobStore seam,
so it stays boto3-free. Per design Decision 10 it does not auto-re-enqueue;
originals are retained, so recovery is a client/ops re-drop.
"""

import logging
from datetime import datetime, timedelta, timezone

from .base import JobStatus
from .factory import get_ingestion_service

logger = logging.getLogger(__name__)


def lambda_handler(event, context):
    from stache_ai.config import settings

    service = get_ingestion_service()
    cutoff = (
        datetime.now(timezone.utc) - timedelta(minutes=settings.ingest_reaper_stuck_minutes)
    ).isoformat()
    stuck = service.jobstore.list_stuck(cutoff)
    now = datetime.now(timezone.utc).isoformat()
    for job in stuck:
        service.jobstore.update(
            job.job_id,
            status=JobStatus.FAILED,
            error_detail="reaped: stuck past TTL (retryable)",
            updated_at=now,
            completed_at=now,
        )
        logger.warning(f"[reaper] failed stuck job {job.job_id} (was {job.status.value})")
    return {"reaped": len(stuck)}

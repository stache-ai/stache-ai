"""Provider abstractions for the portable ingestion backbone.

Phase 1 defines five seams - Intake, Queue, JobStore, BlobStore, Notifier -
plus the data models that flow through them. The synchronous tier wires these
to inline/null implementations that run the existing pipeline in-process; the
async (AWS) tiers slot S3/SQS/DynamoDB implementations behind the same seams
without touching routes or the worker.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Optional

from stache_ai.identity import Principal


class JobStatus(str, Enum):
    QUEUED = "queued"
    UPLOADING = "uploading"
    PROCESSING = "processing"
    DONE = "done"
    SKIPPED = "skipped"            # dedup hit
    FAILED = "failed"
    AWAITING_REVIEW = "awaiting_review"
    CANCELLED = "cancelled"


TERMINAL = {JobStatus.DONE, JobStatus.SKIPPED, JobStatus.FAILED, JobStatus.CANCELLED}


@dataclass
class Job:
    job_id: str
    status: JobStatus
    namespace: str
    source: str                    # cli | web | dropbox | producer | api
    filename: str
    content_type: str
    requested_by: str
    size_bytes: int = 0
    chunks_created: int = 0
    blob_key: Optional[str] = None
    job_group: Optional[str] = None
    hash: Optional[str] = None
    doc_id: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    error_detail: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
    completed_at: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Job":
        d = dict(d)
        d["status"] = JobStatus(d["status"])
        # Drop any unknown keys so the model can evolve without breaking reads.
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class IntakeTicket:
    job_id: str
    upload_url: Optional[str] = None       # None => inline (bytes already delivered)
    required_headers: dict = field(default_factory=dict)
    expires_at: Optional[str] = None


@dataclass
class JobEvent:
    job_id: str
    status: JobStatus
    requested_by: str
    namespace: str
    doc_id: Optional[str] = None


class BlobStore(ABC):
    def make_key(self, job_id: str, filename: str, *,
                 principal: Optional[Principal] = None) -> str:
        """Compose the storage key for a job's original blob.

        Overridable seam: deployment-specific stores may prefix keys (e.g. for
        per-prefix IAM policies or retention rules) using the opaque principal.
        """
        return f"{job_id}/{filename}"

    @abstractmethod
    def put(self, key: str, data: bytes, metadata: dict) -> str: ...

    @abstractmethod
    def get(self, key: str) -> tuple[bytes, dict]: ...

    def head(self, key: str) -> dict:
        """Return blob metadata only. Default reads the full object; S3 overrides efficiently."""
        return self.get(key)[1]

    def presign_put(self, key: str, *, headers: dict, expiry: int) -> Optional[str]:
        return None                        # not supported in Phase 1


class JobStore(ABC):
    @abstractmethod
    def create(self, job: Job, *, principal: Optional[Principal] = None) -> None:
        """Persist a new job. ``principal`` is the opaque caller identity; the
        OSS stores ignore it, deployment-specific stores may scope storage
        keys/attributes from it."""

    @abstractmethod
    def update(self, job_id: str, **fields) -> Job: ...

    @abstractmethod
    def get(self, job_id: str) -> Optional[Job]: ...

    @abstractmethod
    def list(self, *, requested_by: Optional[str] = None,
             status: Optional[JobStatus] = None, limit: int = 50,
             cursor: Optional[str] = None,
             principal: Optional[Principal] = None) -> tuple[list[Job], Optional[str]]: ...

    def visible_to(self, job: Job, principal: Optional[Principal]) -> bool:
        """Whether ``principal`` may read this job (single-job fetch scoping).

        Default: the requester themselves. Deployment-specific stores may
        tighten this from attributes they stamped at ``create`` time (the
        caller treats an invisible job exactly like a missing one, so a
        mismatch never leaks existence).
        """
        return principal is not None and job.requested_by == principal.user_id

    def principal_for(self, job: Job) -> Principal:
        """Reconstruct the acting principal for queued work on this job.

        The worker re-checks authorization before processing (defense in
        depth), which needs the caller's identity - not just the bare user id.
        Default rebuilds an id-only principal; deployment-specific stores may
        rehydrate claims from attributes they stamped at ``create`` time.
        """
        return Principal(user_id=job.requested_by)

    def claim(self, job_id: str, *, from_statuses: "set[JobStatus]",
              to_status: "JobStatus" = None) -> bool:
        """Atomically transition a job into ``to_status`` iff it is currently in
        one of ``from_statuses``. Returns True if this caller won the claim, or
        False if the job is missing or already claimed/terminal (the losing
        duplicate then no-ops).

        Idempotent-consumer guard. The async tier delivers the same job more than
        once by design - SQS is at-least-once, and a blob-backed job is triggered
        by both a direct enqueue and the bucket's S3 ObjectCreated event - so
        processing MUST be gated on winning this claim, not on a bare status read.
        This default is a non-atomic get+update, adequate for the single-process
        sync tier (ephemeral/sqlite); DynamoDB overrides it with a conditional
        write that is safe under real concurrency.
        """
        from datetime import datetime, timezone
        to_status = to_status or JobStatus.PROCESSING
        job = self.get(job_id)
        if job is None or job.status not in from_statuses:
            return False
        self.update(job_id, status=to_status,
                    updated_at=datetime.now(timezone.utc).isoformat())
        return True

    def list_stuck(self, older_than_iso: str) -> list[Job]:
        return []                          # reaper - async tiers only


class QueueProvider(ABC):
    @abstractmethod
    async def enqueue(self, job_id: str) -> None: ...   # ASYNC: inline impl awaits the worker now


class Notifier(ABC):
    @abstractmethod
    def publish(self, event: JobEvent) -> None: ...


class IntakeProvider(ABC):
    @abstractmethod
    def begin(self, *, job_id: str, filename: str, namespace: str,
              content_type: str, size: int, requested_by: str,
              metadata: dict,
              principal: Optional[Principal] = None) -> IntakeTicket: ...

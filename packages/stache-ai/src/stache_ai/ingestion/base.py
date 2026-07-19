"""Provider abstractions for the portable ingestion backbone.

Phase 1 defines five seams - Intake, Queue, JobStore, BlobStore, Notifier -
plus the data models that flow through them. The synchronous tier wires these
to inline/null implementations that run the existing pipeline in-process; async
tiers slot durable queue/blob/jobstore implementations (registered by plugin
packages via entry points) behind the same seams without touching routes or
the worker.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Optional

from stache_ai.identity import Principal


class IngestTextTooLargeError(ValueError):
    """Raised when submitted text exceeds ``max_ingest_text_bytes``.

    A dedicated subclass so routes can map the size cap to HTTP 413 while other
    ``ValueError`` submit failures stay 400.
    """


# Transport-only metadata keys that must never reach enrichers / the vector
# store, nor be persisted on the terminal job record (``_text`` can be hundreds
# of KB and would otherwise leak into GET /jobs responses and strain the
# jobstore item-size cap). Shared by the worker and reaper terminal updates.
_TRANSPORT_KEYS = {"_text", "_chunking", "_prepend_metadata"}


def strip_transport(metadata: dict) -> dict:
    """Metadata with transport-only keys removed (for terminal job records)."""
    return {k: v for k, v in (metadata or {}).items() if k not in _TRANSPORT_KEYS}


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
    # The storage key the bytes will land at, computed ONCE by the intake via
    # BlobStore.make_key. The caller records it as job.blob_key so the two never
    # disagree (a mismatch would guarantee a FAILED job); the worker inverts it
    # with BlobStore.parse_job_id. None for inline tickets that carry no upload.
    blob_key: Optional[str] = None


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

        MUST be pure and deterministic in (job_id, filename, principal): the
        async worker recovers job_id by inverting this via ``parse_job_id``, and
        an override that prefixes keys MUST override ``parse_job_id`` to match.
        """
        return f"{job_id}/{filename}"

    def parse_job_id(self, key: str) -> str:
        """Recover the job_id from a storage key -- the inverse of ``make_key``.

        The async ingestion path (an object-created event) knows only the key
        the bytes landed at; this returns the job it belongs to. The default
        pairs with the default ``make_key`` (``"{job_id}/{filename}"``). A store
        that overrides ``make_key`` to prefix keys MUST override this too so the
        round-trip ``parse_job_id(make_key(job_id, f)) == job_id`` holds.
        """
        return key.split("/")[0]

    @abstractmethod
    def put(self, key: str, data: bytes, metadata: dict) -> str: ...

    @abstractmethod
    def get(self, key: str) -> tuple[bytes, dict]: ...

    def head(self, key: str) -> dict:
        """Return blob metadata only. Default reads the full object; object-store providers override efficiently."""
        return self.get(key)[1]

    def presign_put(self, key: str, *, headers: dict, expiry: int) -> Optional[str]:
        return None                        # not supported in Phase 1

    def presign_get(self, key: str, *, expiry: int,
                    download_filename: Optional[str] = None) -> Optional[str]:
        """Presign a time-limited download URL for a stored blob, or None if the
        store cannot presign (e.g. the inline tier). download_filename sets the
        browser's save-as name."""
        return None

    @property
    def capabilities(self) -> set[str]:
        """Declared blob-store capabilities. Override to advertise support.

        Mirrors the ``VectorDBProvider.capabilities`` mechanism (a set of
        opaque capability strings checked with ``in``). Recognized values:
            - "presign_download": ``presign_get`` returns a usable, time-limited
              download URL (object-store tiers only; inline tiers do not).
        """
        return set()


class JobStore(ABC):
    # Largest inline payload (notably ``_text``) a single job record can hold,
    # or None for no store-imposed limit. Durable stores with a per-item cap
    # (e.g. DynamoDB's 400KB) set this so submit rejects oversized text with 413
    # instead of failing the backend write with a 500.
    max_inline_payload_bytes: "Optional[int]" = None

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

        OVERRIDE OBLIGATION (frozen ABI): a deployment whose authorizer keys on
        CLAIMS (roles/orgs/plans) MUST override this to restore those claims
        from the persisted job. The default returns an id-only principal with
        an EMPTY claims dict, so an intake decision that passed on the caller's
        claims would be re-evaluated here against no claims and diverge from
        intake (typically fail-closed, stalling the job). Overriding it is the
        only way to keep the worker's re-check consistent with intake.
        """
        return Principal(user_id=job.requested_by)

    def claim(self, job_id: str, *, from_statuses: "set[JobStatus]",
              to_status: "JobStatus" = None) -> bool:
        """Atomically transition a job into ``to_status`` iff it is currently in
        one of ``from_statuses``. Returns True if this caller won the claim, or
        False if the job is missing or already claimed/terminal (the losing
        duplicate then no-ops).

        Idempotent-consumer guard. The async tier delivers the same job more than
        once by design - queues deliver at-least-once, and a blob-backed job is
        triggered by both a direct enqueue and the blob store's object-created
        event - so processing MUST be gated on winning this claim, not on a bare
        status read. This default is a non-atomic get+update, adequate for the
        single-process sync tier (ephemeral/sqlite); durable jobstore providers
        override it with an atomic conditional write that is safe under real
        concurrency.
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

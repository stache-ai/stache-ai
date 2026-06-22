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
    def create(self, job: Job) -> None: ...

    @abstractmethod
    def update(self, job_id: str, **fields) -> Job: ...

    @abstractmethod
    def get(self, job_id: str) -> Optional[Job]: ...

    @abstractmethod
    def list(self, *, requested_by: Optional[str] = None,
             status: Optional[JobStatus] = None, limit: int = 50,
             cursor: Optional[str] = None) -> tuple[list[Job], Optional[str]]: ...

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
              metadata: dict) -> IntakeTicket: ...

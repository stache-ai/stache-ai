"""Factory + service facade for the ingestion backbone.

Builds the five seams from config (mirroring the providers/factories registry
pattern) and wires the worker into the queue. ``IngestionService`` is the single
entry point the API routes use: ``submit`` / ``get_job`` / ``list_jobs``.

Core ships only the synchronous tier (inline/null/sqlite/filesystem). Async
providers are registered by plugin packages via entry points and raise a clear
error when not installed - swapping ``INGEST_*_PROVIDER`` is the only change a
deployment needs.
"""

import asyncio
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from ..config import settings as global_settings
from ..providers import plugin_loader
from .base import TERMINAL, IngestTextTooLargeError, IntakeTicket, Job, JobStatus
from .providers.inline import (
    EphemeralJobStore,
    FilesystemBlobStore,
    InlineIntake,
    InlineQueue,
    NullBlobStore,
    NullNotifier,
    SqliteJobStore,
)
from .worker import make_worker

logger = logging.getLogger(__name__)


def _discover(group: str, name: str, config):
    cls = plugin_loader.get_provider_class(group, name)
    if not cls:
        avail = ", ".join(plugin_loader.get_available_providers(group)) or "none (check installed packages)"
        raise ValueError(f"Unknown ingestion {group} provider: {name!r}. Available: {avail}")
    return cls(config)


def _build_jobstore(config):
    name = config.ingest_jobstore_provider
    if name == "ephemeral":
        return EphemeralJobStore()
    if name == "sqlite":
        return SqliteJobStore(config.ingest_jobstore_sqlite_path)
    return _discover("ingest_jobstore", name, config)   # plugin-registered via entry points


def _build_blobstore(config):
    name = config.ingest_blob_provider
    if name == "null":
        return NullBlobStore()
    if name == "filesystem":
        return FilesystemBlobStore(config.ingest_blob_root)
    return _discover("ingest_blob", name, config)       # plugin-registered via entry points


def _build_notifier(config):
    name = config.ingest_notifier_provider
    if name == "null":
        return NullNotifier()
    return _discover("ingest_notifier", name, config)


def _build_intake(config):
    name = config.ingest_intake_provider
    if name == "inline":
        return InlineIntake()
    return _discover("ingest_intake", name, config)


class IngestionService:
    """Facade over the five seams. Clients submit and poll until terminal;
    in the sync tier the first ``submit`` response is already terminal.
    """

    def __init__(self, *, intake, queue, jobstore, blobstore, notifier, worker=None,
                 max_text_bytes=None):
        self.intake = intake
        self.queue = queue
        self.jobstore = jobstore
        self.blobstore = blobstore
        self.notifier = notifier
        self.worker = worker
        # Reject oversized text at the single submit choke point (both /ingest
        # and /capture flow through here). None disables the cap.
        self.max_text_bytes = max_text_bytes

    async def process_job(self, job_id):
        """Drive a single job through the worker (used by queue-driven workers)."""
        await self.worker(job_id)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _effective_text_cap(self) -> Optional[int]:
        """Smallest applicable inline-text cap, or None if unbounded.

        Combines the configured ``max_ingest_text_bytes`` with any per-item
        limit the jobstore declares (e.g. DynamoDB's 400KB), so oversized text
        is rejected at submit (413) rather than 500ing on the backend write.
        """
        caps = [
            c for c in (
                self.max_text_bytes,
                getattr(self.jobstore, "max_inline_payload_bytes", None),
            )
            if c is not None
        ]
        return min(caps) if caps else None

    async def submit(
        self,
        *,
        namespace: str,
        content_type: str,
        requested_by: str,
        filename: Optional[str] = None,
        source: str = "api",
        metadata: Optional[dict] = None,
        text: Optional[str] = None,
        data: Optional[bytes] = None,
        chunking_strategy: str = "recursive",
        wait: bool = False,
        wait_timeout: float = 25.0,
        poll_interval: float = 0.5,
    ) -> Job:
        if text is None and data is None:
            raise ValueError("submit requires either text or data")
        if text is not None:
            cap = self._effective_text_cap()
            if cap is not None:
                text_bytes = len(text.encode("utf-8"))
                if text_bytes > cap:
                    raise IngestTextTooLargeError(
                        f"text is {text_bytes} bytes, exceeds the {cap}-byte "
                        f"inline limit"
                    )

        job_id = str(uuid.uuid4())
        md = dict(metadata or {})
        size = 0
        blob_key = None

        self.intake.begin(
            job_id=job_id,
            filename=filename or "text",
            namespace=namespace,
            content_type=content_type,
            size=len(data) if data is not None else len(text or ""),
            requested_by=requested_by,
            metadata=md,
        )

        if text is not None:
            md["_text"] = text
            md["_chunking"] = chunking_strategy
            size = len(text.encode("utf-8"))
        else:
            blob_key = f"{job_id}/{filename or 'upload.bin'}"
            size = len(data)

        now = self._now()
        job = Job(
            job_id=job_id,
            status=JobStatus.QUEUED,
            namespace=namespace,
            source=source,
            filename=filename or "text",
            content_type=content_type,
            requested_by=requested_by,
            size_bytes=size,
            blob_key=blob_key,
            metadata=md,
            created_at=now,
            updated_at=now,
        )
        # Persist the job BEFORE writing the blob. In async tiers the blob write
        # fires an object-created event that reaches the worker; the job must
        # already exist so the event path recognizes it as already-owned and
        # skips it, instead of racing the write and spawning a duplicate
        # "producer" job for the same object. The direct enqueue below is the
        # authoritative trigger for this path.
        self.jobstore.create(job)
        if data is not None:
            self.blobstore.put(blob_key, data, {"filename": filename, "namespace": namespace})
        await self.queue.enqueue(job_id)   # inline tier: awaits the worker now
        job = self.jobstore.get(job_id) or job
        if wait and job.status not in TERMINAL:
            job = await self._wait_for_terminal(job_id, wait_timeout, poll_interval)
        return job

    async def _wait_for_terminal(self, job_id: str, timeout: float, interval: float) -> Job:
        """Poll the JobStore until the job reaches a terminal status or timeout.

        On timeout returns the last known (possibly non-terminal) state; the
        capture shim tolerates a non-terminal job rather than hitting the HTTP
        gateway timeout.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = self.jobstore.get(job_id)
            if job and job.status in TERMINAL:
                return job
            await asyncio.sleep(interval)
        return self.jobstore.get(job_id)

    async def begin_upload(
        self,
        *,
        namespace: str,
        content_type: str,
        requested_by: str,
        filename: str,
        source: str = "api",
        metadata: Optional[dict] = None,
    ) -> tuple[Job, IntakeTicket]:
        """Presigned-upload flow: create a job in UPLOADING, hand back an upload URL.

        Do NOT enqueue - the blob store's object-created event will, once bytes
        land. The worker recovers ``job_id`` from the blob key, so ``blob_key``
        MUST match the intake key convention ``f"{job_id}/{basename}"``.
        """
        job_id = str(uuid.uuid4())
        md = dict(metadata or {})
        ticket = self.intake.begin(
            job_id=job_id,
            filename=filename,
            namespace=namespace,
            content_type=content_type,
            size=0,
            requested_by=requested_by,
            metadata=md,
        )
        if not ticket.upload_url:
            raise ValueError("intake provider does not support presigned upload")
        # Sanitize to a basename so a filename containing "/" can't break the
        # job_id/key mapping the worker relies on.
        safe_name = os.path.basename(filename) or "upload.bin"
        now = self._now()
        job = Job(
            job_id=job_id,
            status=JobStatus.UPLOADING,
            namespace=namespace,
            source=source,
            filename=filename,
            content_type=content_type,
            requested_by=requested_by,
            blob_key=f"{job_id}/{safe_name}",
            metadata=md,
            created_at=now,
            updated_at=now,
        )
        self.jobstore.create(job)
        return job, ticket

    def get_job(self, job_id: str) -> Optional[Job]:
        return self.jobstore.get(job_id)

    def list_jobs(
        self,
        *,
        requested_by: Optional[str] = None,
        status: Optional[JobStatus] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> tuple[list[Job], Optional[str]]:
        return self.jobstore.list(
            requested_by=requested_by, status=status, limit=limit, cursor=cursor
        )


class IngestionServiceFactory:
    @classmethod
    def build(cls, config, pipeline) -> IngestionService:
        jobstore = _build_jobstore(config)
        blobstore = _build_blobstore(config)
        notifier = _build_notifier(config)
        intake = _build_intake(config)

        worker = make_worker(jobstore, blobstore, notifier, pipeline)
        queue_name = config.ingest_queue_provider
        if queue_name == "inline":
            queue = InlineQueue(worker)
        else:
            queue = _discover("ingest_queue", queue_name, config)   # plugin-registered via entry points

        logger.info(
            "Ingestion service: queue=%s jobstore=%s blob=%s intake=%s notifier=%s",
            queue_name,
            config.ingest_jobstore_provider,
            config.ingest_blob_provider,
            config.ingest_intake_provider,
            config.ingest_notifier_provider,
        )
        return IngestionService(
            intake=intake, queue=queue, jobstore=jobstore,
            blobstore=blobstore, notifier=notifier, worker=worker,
            max_text_bytes=getattr(config, "max_ingest_text_bytes", None),
        )


_service: Optional[IngestionService] = None
_service_lock = threading.Lock()


def get_ingestion_service() -> IngestionService:
    """Get or build the global ingestion service (thread-safe singleton)."""
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                from ..rag.pipeline import get_pipeline
                _service = IngestionServiceFactory.build(global_settings, get_pipeline())
    return _service


def reset_ingestion_service() -> None:
    """Drop the cached service (tests / config reload)."""
    global _service
    with _service_lock:
        _service = None

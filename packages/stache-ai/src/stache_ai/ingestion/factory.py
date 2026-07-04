"""Factory + service facade for the ingestion backbone.

Builds the five seams from config (mirroring the providers/factories registry
pattern) and wires the worker into the queue. ``IngestionService`` is the single
entry point the API routes use: ``submit`` / ``get_job`` / ``list_jobs``.

Phase 1 ships only the synchronous tier (inline/null/sqlite/filesystem).
Async providers (sqs/s3/dynamodb) raise a clear error until Phase 2 registers
them - swapping ``INGEST_*_PROVIDER`` is the only change that phase needs.
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
from stache_ai.identity import Principal

from .base import TERMINAL, IntakeTicket, Job, JobStatus
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
    return _discover("ingest_jobstore", name, config)   # dynamodb -> stache-ai-dynamodb


def _build_blobstore(config):
    name = config.ingest_blob_provider
    if name == "null":
        return NullBlobStore()
    if name == "filesystem":
        return FilesystemBlobStore(config.ingest_blob_root)
    return _discover("ingest_blob", name, config)       # s3 -> stache-ai-aws


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

    def __init__(self, *, intake, queue, jobstore, blobstore, notifier, worker=None):
        self.intake = intake
        self.queue = queue
        self.jobstore = jobstore
        self.blobstore = blobstore
        self.notifier = notifier
        self.worker = worker

    async def process_job(self, job_id):
        """Drive a single job through the worker (used by the SQS worker Lambda)."""
        await self.worker(job_id)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    async def submit(
        self,
        *,
        namespace: str,
        content_type: str,
        requested_by: "Principal | str",
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

        principal = Principal.of(requested_by)
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
            requested_by=principal.user_id,
            metadata=md,
            principal=principal,
        )

        if text is not None:
            md["_text"] = text
            md["_chunking"] = chunking_strategy
            size = len(text.encode("utf-8"))
        else:
            blob_key = self.blobstore.make_key(
                job_id, filename or "upload.bin", principal=principal)
            size = len(data)

        now = self._now()
        job = Job(
            job_id=job_id,
            status=JobStatus.QUEUED,
            namespace=namespace,
            source=source,
            filename=filename or "text",
            content_type=content_type,
            requested_by=principal.user_id,
            size_bytes=size,
            blob_key=blob_key,
            metadata=md,
            created_at=now,
            updated_at=now,
        )
        # Persist the job BEFORE writing the blob. In the async (S3) tier the blob
        # write fires an ObjectCreated event that reaches the worker; the job must
        # already exist so the S3-event path recognizes it as already-owned and
        # skips it, instead of racing the write and spawning a duplicate
        # "producer" job for the same object. The direct enqueue below is the
        # authoritative trigger for this path.
        self.jobstore.create(job, principal=principal)
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
        capture shim tolerates a non-terminal job rather than hitting the API
        Gateway 29s ceiling.
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
        requested_by: "Principal | str",
        filename: str,
        source: str = "api",
        metadata: Optional[dict] = None,
    ) -> tuple[Job, IntakeTicket]:
        """Presigned-upload flow: create a job in UPLOADING, hand back an upload URL.

        Do NOT enqueue - the S3 ObjectCreated event will, once bytes land. The
        worker recovers ``job_id`` from the S3 key, so ``blob_key`` MUST match
        the intake key convention ``f"{job_id}/{basename}"``.
        """
        principal = Principal.of(requested_by)
        job_id = str(uuid.uuid4())
        md = dict(metadata or {})
        ticket = self.intake.begin(
            job_id=job_id,
            filename=filename,
            namespace=namespace,
            content_type=content_type,
            size=0,
            requested_by=principal.user_id,
            metadata=md,
            principal=principal,
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
            requested_by=principal.user_id,
            blob_key=f"{job_id}/{safe_name}",
            metadata=md,
            created_at=now,
            updated_at=now,
        )
        self.jobstore.create(job, principal=principal)
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
        principal: Optional[Principal] = None,
    ) -> tuple[list[Job], Optional[str]]:
        return self.jobstore.list(
            requested_by=requested_by, status=status, limit=limit, cursor=cursor,
            principal=principal,
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
            queue = _discover("ingest_queue", queue_name, config)   # sqs -> stache-ai-aws

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

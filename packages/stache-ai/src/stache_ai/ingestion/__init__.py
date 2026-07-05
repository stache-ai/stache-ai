"""Portable ingestion backbone (Phase 1: provider abstractions + sync tier)."""

from .base import (
    TERMINAL,
    BlobStore,
    IntakeProvider,
    IntakeTicket,
    Job,
    JobEvent,
    JobStatus,
    JobStore,
    Notifier,
    QueueProvider,
)
from .factory import (
    IngestionService,
    IngestionServiceFactory,
    get_ingestion_service,
    reset_ingestion_service,
)
from .worker import make_worker

__all__ = [
    "TERMINAL",
    "BlobStore",
    "IntakeProvider",
    "IntakeTicket",
    "Job",
    "JobEvent",
    "JobStatus",
    "JobStore",
    "Notifier",
    "QueueProvider",
    "IngestionService",
    "IngestionServiceFactory",
    "get_ingestion_service",
    "reset_ingestion_service",
    "make_worker",
]

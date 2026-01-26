"""Middleware for stache-ai pipeline.

This module provides hook points for enterprise features:
- stache.enrichment: Pre-chunking content processing
- stache.chunk_observer: Post-storage tracking (advisory)
- stache.query_processor: Pre-search query modification
- stache.result_processor: Post-search result filtering
- stache.delete_observer: Delete validation and auditing
"""

from .context import (
    RequestContext,
    QueryContext,
)
from .results import (
    SearchResult,
    EnrichmentResult,
    ObserverResult,
    QueryProcessorResult,
    ResultProcessorResult,
    PostIngestResult,
)
from .base import (
    MiddlewareBase,
    Enricher,
    ChunkObserver,
    StorageResult,
    QueryProcessor,
    ResultProcessor,
    DeleteObserver,
    DeleteTarget,
    PostIngestProcessor,
    IngestGuard,
    GuardResult,
    ErrorProcessor,
    ErrorResult,
)
from .chain import (
    MiddlewareChain,
    MiddlewareError,
    MiddlewareRejection,
)

__all__ = [
    # Context
    "RequestContext",
    "QueryContext",
    # Results
    "SearchResult",
    "EnrichmentResult",
    "ObserverResult",
    "QueryProcessorResult",
    "ResultProcessorResult",
    "PostIngestResult",
    "GuardResult",
    "ErrorResult",
    # Base classes
    "MiddlewareBase",
    "Enricher",
    "ChunkObserver",
    "StorageResult",
    "QueryProcessor",
    "ResultProcessor",
    "DeleteObserver",
    "DeleteTarget",
    "PostIngestProcessor",
    "IngestGuard",
    "ErrorProcessor",
    # Chain executor
    "MiddlewareChain",
    "MiddlewareError",
    "MiddlewareRejection",
]

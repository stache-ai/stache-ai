"""Middleware discovery via entry points."""

from .base import (
    Enricher,
    ChunkObserver,
    PostIngestProcessor,
    QueryProcessor,
    ResultProcessor,
    DeleteObserver,
    IngestGuard,
    ErrorProcessor,
)

# Middleware type registry for entry point discovery
MIDDLEWARE_TYPES = {
    "stache.enrichment": Enricher,
    "stache.chunk_observer": ChunkObserver,
    "stache.post_ingest": PostIngestProcessor,
    "stache.query_processor": QueryProcessor,
    "stache.result_processor": ResultProcessor,
    "stache.delete_observer": DeleteObserver,
    "stache.ingest_guard": IngestGuard,
    "stache.error_processor": ErrorProcessor,
}

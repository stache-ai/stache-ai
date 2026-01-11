from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Any


@dataclass
class SearchResult:
    """Single search result from vector database."""
    text: str
    score: float
    metadata: dict[str, Any]
    vector_id: str


@dataclass
class EnrichmentResult:
    """Result from enrichment middleware (pre-chunking).

    Actions:
        allow: Pass content through unchanged
        transform: Use returned content/metadata
        reject: Block ingestion with reason
    """
    action: Literal["allow", "transform", "reject"]
    content: str | None = None
    metadata: dict[str, Any] | None = None
    reason: str | None = None


@dataclass
class ObserverResult:
    """Result from observer middleware (post-storage, advisory).

    Actions:
        allow: Continue normally
        reject: Log error/warning (no rollback in Phase 1)

    Note: No transform action - storage has already occurred.
    """
    action: Literal["allow", "reject"]
    reason: str | None = None


@dataclass
class QueryProcessorResult:
    """Result from query processor middleware (pre-search).

    Actions:
        allow: Use original query/filters
        transform: Use modified query and/or filters
        reject: Block query with reason
    """
    action: Literal["allow", "transform", "reject"]
    query: str | None = None
    filters: dict[str, Any] | None = None
    reason: str | None = None


@dataclass
class ResultProcessorResult:
    """Result from result processor middleware (post-search).

    Actions:
        allow: Return results (possibly filtered/enriched)
        reject: Block entire query response
    """
    action: Literal["allow", "reject"]
    results: list[SearchResult] | None = None
    reason: str | None = None


@dataclass
class PostIngestResult:
    """Result from post-ingest processor middleware (after chunk storage).

    PostIngestProcessors generate artifacts (summaries, extracted entities, etc.)
    that should be stored. The pipeline coordinates storage.

    Actions:
        allow: Continue with artifacts (if any)
        skip: Skip this processor (log reason)

    Note: No "reject" action - failures should not block ingestion.
    Use on_error="skip" enforced at base class level.

    Artifacts:
        Dictionary of generated content to store. Common keys:
        - "summary": Text summary of the document
        - "summary_embedding": Vector embedding of summary
        - "headings": List of extracted section headings
        - Custom keys for plugin-specific artifacts

    Warning: Duplicate keys will overwrite earlier artifacts.
    """
    action: Literal["allow", "skip"]
    artifacts: dict[str, Any] | None = None
    reason: str | None = None

    def __post_init__(self):
        """Validate artifacts dictionary if provided."""
        if self.artifacts is not None:
            if not isinstance(self.artifacts, dict):
                raise TypeError(f"artifacts must be dict, got {type(self.artifacts)}")
            # Note: We don't enforce strict typing of artifact values yet
            # Future: could add artifact type registry for validation

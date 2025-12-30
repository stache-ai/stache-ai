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

from __future__ import annotations

from typing import Any

from .base import (
    Enricher,
    ChunkObserver,
    QueryProcessor,
    ResultProcessor,
    DeleteObserver,
    StorageResult,
    DeleteTarget,
)
from .results import (
    EnrichmentResult,
    ObserverResult,
    QueryProcessorResult,
    ResultProcessorResult,
    SearchResult,
)
from .context import RequestContext, QueryContext


class MockEnricher(Enricher):
    """Mock enricher for testing."""

    def __init__(
        self,
        action: str = "allow",
        content: str | None = None,
        metadata: dict[str, Any] | None = None,
        reason: str | None = None,
        priority: int = 100,
        should_raise: Exception | None = None
    ):
        self._action = action
        self._content = content
        self._metadata = metadata
        self._reason = reason
        self.priority = priority
        self._should_raise = should_raise
        self.call_count = 0
        self.last_content: str | None = None
        self.last_metadata: dict[str, Any] | None = None
        self.last_context: RequestContext | None = None

    async def process(
        self,
        content: str,
        metadata: dict[str, Any],
        context: RequestContext
    ) -> EnrichmentResult:
        self.call_count += 1
        self.last_content = content
        self.last_metadata = metadata
        self.last_context = context

        if self._should_raise:
            raise self._should_raise

        return EnrichmentResult(
            action=self._action,  # type: ignore
            content=self._content if self._content is not None else content,
            metadata=self._metadata if self._metadata is not None else metadata,
            reason=self._reason
        )


class MockQueryProcessor(QueryProcessor):
    """Mock query processor for testing."""

    def __init__(
        self,
        action: str = "allow",
        query: str | None = None,
        filters: dict[str, Any] | None = None,
        reason: str | None = None,
        priority: int = 100,
        should_raise: Exception | None = None
    ):
        self._action = action
        self._query = query
        self._filters = filters
        self._reason = reason
        self.priority = priority
        self._should_raise = should_raise
        self.call_count = 0
        self.last_query: str | None = None
        self.last_filters: dict[str, Any] | None = None
        self.last_context: QueryContext | None = None

    async def process(
        self,
        query: str,
        filters: dict[str, Any] | None,
        context: QueryContext
    ) -> QueryProcessorResult:
        self.call_count += 1
        self.last_query = query
        self.last_filters = filters
        self.last_context = context

        if self._should_raise:
            raise self._should_raise

        return QueryProcessorResult(
            action=self._action,  # type: ignore
            query=self._query,
            filters=self._filters,
            reason=self._reason
        )


class MockChunkObserver(ChunkObserver):
    """Mock chunk observer for testing."""

    def __init__(
        self,
        action: str = "allow",
        reason: str | None = None,
        priority: int = 100,
        should_raise: Exception | None = None
    ):
        self._action = action
        self._reason = reason
        self.priority = priority
        self._should_raise = should_raise
        self.call_count = 0
        self.last_chunks: list[tuple[str, dict[str, Any]]] | None = None
        self.last_storage_result: StorageResult | None = None
        self.last_context: RequestContext | None = None

    async def on_chunks_stored(
        self,
        chunks: list[tuple[str, dict[str, Any]]],
        storage_result: StorageResult,
        context: RequestContext
    ) -> ObserverResult:
        self.call_count += 1
        self.last_chunks = chunks
        self.last_storage_result = storage_result
        self.last_context = context

        if self._should_raise:
            raise self._should_raise

        return ObserverResult(
            action=self._action,  # type: ignore
            reason=self._reason
        )


class MockResultProcessor(ResultProcessor):
    """Mock result processor for testing."""

    def __init__(
        self,
        action: str = "allow",
        results: list[SearchResult] | None = None,
        reason: str | None = None,
        priority: int = 100,
        should_raise: Exception | None = None
    ):
        self._action = action
        self._results = results
        self._reason = reason
        self.priority = priority
        self._should_raise = should_raise
        self.call_count = 0
        self.last_results: list[SearchResult] | None = None
        self.last_context: QueryContext | None = None

    async def process(
        self,
        results: list[SearchResult],
        context: QueryContext
    ) -> ResultProcessorResult:
        self.call_count += 1
        self.last_results = results
        self.last_context = context

        if self._should_raise:
            raise self._should_raise

        return ResultProcessorResult(
            action=self._action,  # type: ignore
            results=self._results if self._results is not None else results,
            reason=self._reason
        )


class MockDeleteObserver(DeleteObserver):
    """Mock delete observer for testing."""

    def __init__(
        self,
        action: str = "allow",
        reason: str | None = None,
        priority: int = 100,
        should_raise: Exception | None = None
    ):
        self._action = action
        self._reason = reason
        self.priority = priority
        self._should_raise = should_raise
        self.call_count = 0
        self.complete_count = 0
        self.last_target: DeleteTarget | None = None
        self.last_context: RequestContext | None = None

    async def on_delete(
        self,
        target: DeleteTarget,
        context: RequestContext
    ) -> ObserverResult:
        self.call_count += 1
        self.last_target = target
        self.last_context = context

        if self._should_raise:
            raise self._should_raise

        return ObserverResult(
            action=self._action,  # type: ignore
            reason=self._reason
        )

    async def on_delete_complete(
        self,
        target: DeleteTarget,
        context: RequestContext
    ) -> None:
        self.complete_count += 1


class RecordingMiddleware(Enricher):
    """Records all calls for assertion in tests.

    Useful for verifying call order and arguments.
    """

    def __init__(self, name: str = "RecordingMiddleware"):
        self._name = name
        self.calls: list[tuple[str, dict[str, Any], RequestContext]] = []

    async def process(
        self,
        content: str,
        metadata: dict[str, Any],
        context: RequestContext
    ) -> EnrichmentResult:
        self.calls.append((content, metadata, context))
        return EnrichmentResult(action="allow")

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal, Any, ClassVar, TYPE_CHECKING

if TYPE_CHECKING:
    from .context import RequestContext, QueryContext
    from .results import EnrichmentResult, ObserverResult, QueryProcessorResult, ResultProcessorResult, SearchResult, PostIngestResult


class MiddlewareBase(ABC):
    """Base class for all middleware.

    Attributes:
        priority: Lower values run earlier (default 100)
        depends_on: Must run after these middleware names
        runs_before: Must run before these middleware names
        on_error: Behavior when middleware raises exception
        required: If False, chain continues even on error
        timeout_seconds: Per-middleware timeout (None = no timeout)

    Lazy Loading Pattern (for heavy dependencies like Whisper):
        class AudioTranscriber(Enricher):
            _whisper = None

            @classmethod
            def _load_whisper(cls):
                if cls._whisper is None:
                    import whisper
                    cls._whisper = whisper.load_model("base")
                return cls._whisper
    """

    # Ordering
    priority: ClassVar[int] = 100
    depends_on: ClassVar[tuple[str, ...]] = ()
    runs_before: ClassVar[tuple[str, ...]] = ()

    # Error handling
    on_error: ClassVar[Literal["allow", "reject", "skip"]] = "reject"
    required: ClassVar[bool] = True

    # Timeout (PE addition)
    timeout_seconds: ClassVar[float | None] = None

    @classmethod
    def get_metadata(cls) -> dict[str, Any]:
        """Return middleware metadata for introspection."""
        return {
            "name": cls.__name__,
            "description": cls.__doc__,
            "priority": cls.priority,
            "depends_on": list(cls.depends_on),
            "runs_before": list(cls.runs_before),
            "on_error": cls.on_error,
            "required": cls.required,
            "timeout_seconds": cls.timeout_seconds,
        }

    async def on_chain_start(self, context: "RequestContext") -> None:
        """Called before middleware chain execution. Override to customize."""
        pass

    async def on_chain_complete(self, context: "RequestContext", success: bool) -> None:
        """Called after middleware chain execution. Override to customize."""
        pass


class Enricher(MiddlewareBase):
    """Base class for ingest enrichment middleware.

    Enrichers process content before chunking during ingestion.
    They can extract (from URLs, audio), transform, or enrich content.

    Phases run in order: extract -> transform -> enrich
    """

    phase: ClassVar[Literal["extract", "transform", "enrich"]] = "enrich"

    @abstractmethod
    async def process(
        self,
        content: str,
        metadata: dict[str, Any],
        context: "RequestContext"
    ) -> "EnrichmentResult":
        """Process content before chunking.

        Args:
            content: Raw text content to process
            metadata: Document metadata
            context: Request context with user/tenant info

        Returns:
            EnrichmentResult with action:
            - allow: Pass through unchanged
            - transform: Use returned content/metadata
            - reject: Block ingestion with reason
        """
        pass

    @classmethod
    def can_process(cls, content: str, metadata: dict[str, Any]) -> bool:
        """Check if this enricher can process the content type.

        Used for auto-detection. Override to check content patterns.
        Default returns True (accepts all content).
        """
        return True


class QueryProcessor(MiddlewareBase):
    """Base class for query preprocessing.

    Runs before vector search. Can rewrite queries, inject ACL filters,
    or reject queries (rate limiting).
    """

    @abstractmethod
    async def process(
        self,
        query: str,
        filters: dict[str, Any] | None,
        context: "QueryContext"
    ) -> "QueryProcessorResult":
        """Process query before vector search.

        Args:
            query: The search query string
            filters: Optional metadata filters (can be None)
            context: Query context with user/tenant info

        Returns:
            QueryProcessorResult with:
            - allow: Use original query/filters
            - transform: Use modified query and/or filters
            - reject: Block query with reason
        """
        pass


@dataclass
class GuardResult:
    """Result from ingest guard middleware (pre-enrichment validation)."""
    action: Literal["allow", "reject"]
    reason: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class ErrorResult:
    """Result from error processor middleware."""
    handled: bool = False
    """Whether error was handled (does not suppress exception)."""
    metadata: dict[str, Any] | None = None
    """Additional metadata about error handling."""


@dataclass
class DeleteTarget:
    """What is being deleted."""
    target_type: Literal["document", "namespace", "chunks"]
    doc_id: str | None = None
    namespace: str | None = None
    chunk_ids: list[str] | None = None


class DeleteObserver(MiddlewareBase):
    """Base class for delete observation.

    on_delete: Called BEFORE deletion (can reject)
    on_delete_complete: Called AFTER deletion (audit/sync only)
    """

    @abstractmethod
    async def on_delete(
        self,
        target: DeleteTarget,
        context: "RequestContext"
    ) -> "ObserverResult":
        """Called before deletion occurs.

        Returns:
            ObserverResult with:
            - allow: Proceed with deletion
            - reject: Block deletion with reason
        """
        pass

    async def on_delete_complete(
        self,
        target: DeleteTarget,
        context: "RequestContext"
    ) -> None:
        """Called after successful deletion. Override for audit/sync."""
        pass


class IngestGuard(MiddlewareBase):
    """Base class for pre-enrichment validation.

    IngestGuards run BEFORE Enrichers to validate content and block
    ingestion early if needed. Use cases:
    - PII detection (block before LLM enrichment)
    - Malware scanning
    - Deduplication checks
    - ACL validation

    Guards cannot transform content - only allow or reject.

    Error Handling:
        on_error="reject" (default) - Block ingestion on guard failure
        on_error="allow" - Continue if guard fails (log warning)
    """

    @abstractmethod
    async def validate(
        self,
        content: str,
        metadata: dict[str, Any],
        context: "RequestContext"
    ) -> "GuardResult":
        """Validate content before enrichment."""
        pass


class ErrorProcessor(MiddlewareBase):
    """Base class for error handling during ingestion.

    ErrorProcessors run when pipeline encounters an exception, allowing
    cleanup or recovery actions. Use cases:
    - Restore soft-deleted documents on REINGEST_VERSION failure
    - Release external resources allocated during enrichment
    - Log detailed error context for debugging
    - Trigger alerts for specific error patterns

    IMPORTANT: ErrorProcessors CANNOT suppress exceptions - the original
    exception is always re-raised. They can only perform cleanup/recovery.

    Error handling is best-effort - if an ErrorProcessor itself fails,
    the error is logged but does not block other processors.
    """

    @abstractmethod
    async def on_error(
        self,
        exception: Exception,
        context: "RequestContext",
        partial_state: dict[str, Any],
    ) -> "ErrorResult":
        """Handle pipeline error.

        Args:
            exception: The exception that occurred
            context: Request context with namespace, source, etc.
            partial_state: Partial pipeline state at time of error:
                - metadata: Document metadata dict
                - doc_id: Generated document ID
                - namespace: Target namespace
                - vectors_inserted: Whether vectors were written
                - chunk_ids: Vector IDs if inserted

        Returns:
            ErrorResult indicating whether error was handled
        """
        pass


class ResultProcessor(MiddlewareBase):
    """Base class for result post-processing.

    Runs after vector search, before returning results.
    Can filter (ACL), redact (PII), enrich, or inject citations.

    Supports batch mode (default) or streaming mode.
    """

    mode: ClassVar[Literal["batch", "stream"]] = "batch"

    @abstractmethod
    async def process(
        self,
        results: list["SearchResult"],
        context: "QueryContext"
    ) -> "ResultProcessorResult":
        """Process search results (batch mode).

        Args:
            results: All search results
            context: Query context

        Returns:
            ResultProcessorResult with:
            - allow: Return (possibly modified) results
            - reject: Block entire query response
        """
        pass

    async def process_item(
        self,
        result: "SearchResult",
        context: "QueryContext"
    ) -> "SearchResult | None":
        """Process single result (streaming mode).

        Override for streaming mode. Return None to filter out result.
        Default returns result unchanged.
        """
        return result


@dataclass
class StorageResult:
    """Information about stored chunks."""
    vector_ids: list[str]
    namespace: str
    index: str
    doc_id: str | None
    chunk_count: int
    embedding_model: str


class ChunkObserver(MiddlewareBase):
    """Base class for post-storage observation.

    IMPORTANT: Advisory only in Phase 1. Rejection logs error but
    does NOT rollback stored chunks. For quota enforcement, use
    pre-flight check in enrichment phase instead.
    """

    @abstractmethod
    async def on_chunks_stored(
        self,
        chunks: list[tuple[str, dict[str, Any]]],
        storage_result: StorageResult,
        context: "RequestContext"
    ) -> "ObserverResult":
        """Called after chunks are stored.

        Args:
            chunks: List of (text, metadata) tuples
            storage_result: Details about the storage operation
            context: Request context

        Returns:
            ObserverResult with action:
            - allow: Continue (normal case)
            - reject: Log error/warning (NO ROLLBACK in Phase 1)
        """
        pass


class PostIngestProcessor(MiddlewareBase):
    """Base class for post-ingest artifact generation.

    PostIngestProcessors run after chunks are stored to generate
    additional artifacts (summaries, extracted entities, etc.).
    Unlike ChunkObserver (advisory), PostIngestProcessor generates
    new content that should be stored.

    Error Handling:
        ALWAYS uses on_error="skip" (enforced at base class level).
        Failures should not block ingestion. The pipeline logs errors
        but continues processing.

    Provider Access:
        Access providers via context.custom for artifact generation:
        - context.custom.get("embedding_provider"): EmbeddingProvider
        - context.custom.get("vectordb"): VectorDBProvider
        - context.custom.get("document_index"): DocumentIndexProvider
        - context.custom.get("summaries_provider"): SummariesProvider
        - context.custom.get("config"): Settings

    Example:
        class SummaryGenerator(PostIngestProcessor):
            priority = 50  # Run before entity extraction

            async def process(self, chunks, storage_result, context):
                # Combine chunk text
                full_text = " ".join(chunk[0] for chunk in chunks[:10])

                # Generate summary (using LLM via context.llm_provider)
                summary = await generate_summary(full_text)

                # Generate embedding
                embedding = await context.embedding_provider.embed([summary])

                return PostIngestResult(
                    action="allow",
                    artifacts={
                        "summary": summary,
                        "summary_embedding": embedding[0]
                    }
                )
    """

    # Enforce skip-on-error semantics
    on_error: ClassVar[Literal["skip"]] = "skip"

    @abstractmethod
    async def process(
        self,
        chunks: list[tuple[str, dict[str, Any]]],
        storage_result: StorageResult,
        context: "RequestContext"
    ) -> "PostIngestResult":
        """Generate artifacts after chunk storage.

        Args:
            chunks: List of (text, metadata) tuples that were stored
            storage_result: Details about the storage operation
            context: Request context with provider access via custom dict

        Returns:
            PostIngestResult with:
            - allow: Continue with artifacts (if any)
            - skip: Skip this processor with reason (logged)

        Note: Providers accessed via context.custom:
            - context.custom.get("embedding_provider")
            - context.custom.get("vectordb")
            - context.custom.get("document_index")
        """
        pass

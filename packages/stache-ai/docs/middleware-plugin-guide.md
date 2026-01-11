# Middleware Plugin Developer Guide

## Overview

The Stache middleware plugin architecture enables developers to extend the RAG pipeline with custom functionality without modifying core code. Plugins integrate at critical points in the request lifecycle:

- **Enrichment**: Transform content before chunking (ingest phase)
- **Chunk Observation**: Monitor/audit chunks after storage (ingest phase)
- **Post-Ingest Processing**: Generate artifacts after chunk storage (ingest phase)
- **Query Processing**: Rewrite/filter queries before search (query phase)
- **Result Processing**: Filter/enrich results after search (query phase)
- **Delete Observation**: Validate and audit document deletion (delete phase)

## Quick Start

### Creating Your First Enricher

```python
from stache_ai.middleware.base import Enricher
from stache_ai.middleware.results import EnrichmentResult
from stache_ai.middleware.context import RequestContext

class LanguageDetectionEnricher(Enricher):
    """Detect document language and add to metadata."""

    phase = "enrich"  # Can be: extract, transform, enrich
    priority = 100    # Lower numbers run first

    async def process(
        self,
        content: str,
        metadata: dict,
        context: RequestContext
    ) -> EnrichmentResult:
        """Process content before chunking.

        Args:
            content: The raw text to process
            metadata: Document metadata (can be modified)
            context: Request context with user/tenant info

        Returns:
            EnrichmentResult with action and optionally modified content/metadata
        """
        import langdetect

        try:
            language = langdetect.detect(content)
            metadata["detected_language"] = language

            # Return modified metadata
            return EnrichmentResult(
                action="transform",
                content=content,  # Unchanged
                metadata=metadata
            )
        except Exception as e:
            # Reject documents with detection errors
            return EnrichmentResult(
                action="reject",
                reason=f"Language detection failed: {e}"
            )
```

### Registering Your Plugin

Add an entry point in `setup.py` or `pyproject.toml`:

```ini
# setup.cfg
[options.entry_points]
stache.enrichment =
    language_detector = my_package.middleware:LanguageDetectionEnricher
```

Or in `pyproject.toml`:

```toml
[project.entry-points."stache.enrichment"]
language_detector = "my_package.middleware:LanguageDetectionEnricher"
```

The plugin is automatically loaded on first use. No code changes needed!

## Middleware Types

### 1. Enricher - Content Enhancement (Ingest Phase)

Enrichers run **before chunking** and can:
- Extract content from URLs, files, or other sources
- Transform/standardize content
- Add metadata
- Validate content against policies

```python
from stache_ai.middleware.base import Enricher
from stache_ai.middleware.results import EnrichmentResult

class URLEnricher(Enricher):
    """Extract content from URLs."""

    phase = "extract"  # extract < transform < enrich
    priority = 50      # Runs early (lower priority = earlier)

    async def process(self, content, metadata, context):
        if content.startswith("http"):
            # Fetch and extract
            try:
                import httpx
                async with httpx.AsyncClient() as client:
                    response = await client.get(content)
                    extracted_text = extract_text(response.text)
                    metadata["source_url"] = content

                    return EnrichmentResult(
                        action="transform",
                        content=extracted_text,
                        metadata=metadata
                    )
            except Exception as e:
                return EnrichmentResult(
                    action="reject",
                    reason=f"URL fetch failed: {e}"
                )

        return EnrichmentResult(action="allow")
```

**Entry point**: `stache.enrichment`

**Actions**:
- `allow`: Pass through unchanged
- `transform`: Use returned content/metadata
- `reject`: Block ingestion with reason

**Lifecycle Hooks**:
```python
async def on_chain_start(self, context):
    """Called before any enrichers run."""
    logger.info(f"Starting enrichment for {context.request_id}")

async def on_chain_complete(self, context, success):
    """Called after all enrichers complete."""
    if not success:
        logger.error(f"Enrichment failed for {context.request_id}")
```

### 2. ChunkObserver - Storage Auditing (Ingest Phase)

ChunkObservers run **after chunking and storage** for monitoring/auditing (advisory only).

```python
from stache_ai.middleware.base import ChunkObserver, StorageResult
from stache_ai.middleware.results import ObserverResult

class QuotaEnforcer(ChunkObserver):
    """Monitor storage quota usage."""

    on_error = "allow"  # Don't fail ingestion if observer fails

    async def on_chunks_stored(self, chunks, storage_result, context):
        """Called after chunks are stored.

        Args:
            chunks: List of (text, metadata) tuples
            storage_result: Details about the storage operation
                - vector_ids: List of stored vector IDs
                - chunk_count: Number of chunks stored
                - embedding_model: Model used
            context: Request context
        """
        # Check quota
        quota = get_user_quota(context.user_id)
        used = count_user_vectors(context.user_id)
        new_total = used + storage_result.chunk_count

        if new_total > quota:
            # Advisory only - chunks already stored
            return ObserverResult(
                action="reject",
                reason=f"Quota exceeded: {new_total} > {quota}"
            )

        return ObserverResult(action="allow")
```

**Entry point**: `stache.chunk_observer`

**Important**: Rejections are **advisory only**. Chunks are already stored, so:
- Use for monitoring, auditing, quota enforcement
- For strict pre-flight checks, use `Enricher` instead
- For quota limits, check in enrichment phase

**Actions**:
- `allow`: Continue normally
- `reject`: Log warning (no rollback)

### 3. PostIngestProcessor - Artifact Generation (Ingest Phase)

PostIngestProcessors run **after chunks are stored** to generate additional artifacts like summaries, extracted entities, or metadata records. Unlike ChunkObserver (advisory), PostIngestProcessor creates new content that should be stored.

**Use Cases**:
- Generate document summaries for semantic discovery
- Extract named entities for metadata enrichment
- Create knowledge graph relationships
- Compute document fingerprints or signatures

**Key Features**:
- **Non-blocking**: Failures never block ingestion (enforced `on_error="skip"`)
- **Artifact collection**: Return structured artifacts for pipeline coordination
- **Provider access**: Access embedding, vector DB, and document index via context
- **Priority ordering**: Control execution sequence with priority values

```python
from stache_ai.middleware.base import PostIngestProcessor, StorageResult
from stache_ai.middleware.results import PostIngestResult
from stache_ai.middleware.context import RequestContext

class DocumentSummaryGenerator(PostIngestProcessor):
    """Generate semantic summaries for document discovery."""

    priority = 50  # Lower values run earlier

    async def process(
        self,
        chunks: list[tuple[str, dict]],
        storage_result: StorageResult,
        context: RequestContext
    ) -> PostIngestResult:
        """Generate summary from stored chunks.

        Args:
            chunks: List of (text, metadata) tuples that were stored
            storage_result: Details about storage (doc_id, namespace, etc.)
            context: Request context with provider access

        Returns:
            PostIngestResult with artifacts or skip action
        """
        # Access providers from context
        embedding_provider = context.custom.get("embedding_provider")
        summaries_provider = context.custom.get("summaries_provider")

        if not embedding_provider or not summaries_provider:
            return PostIngestResult(
                action="skip",
                reason="Required providers not available"
            )

        try:
            # Combine first few chunks for summary
            summary_text = " ".join(
                chunk[0] for chunk in chunks[:5]
            )[:1000]

            # Generate embedding
            summary_embedding = embedding_provider.embed(summary_text)

            # Store summary record
            summary_id = str(uuid.uuid4())
            summaries_provider.insert(
                vectors=[summary_embedding],
                texts=[summary_text],
                metadatas=[{
                    "_type": "document_summary",
                    "doc_id": storage_result.doc_id,
                    "namespace": storage_result.namespace
                }],
                ids=[summary_id],
                namespace=storage_result.namespace
            )

            # Return artifacts for document index
            return PostIngestResult(
                action="allow",
                artifacts={
                    "summary": summary_text,
                    "summary_embedding": summary_embedding,
                    "summary_id": summary_id
                }
            )

        except Exception as e:
            # Errors are logged but don't block ingestion
            return PostIngestResult(
                action="skip",
                reason=f"Summary generation failed: {e}"
            )
```

**Provider Access Pattern**:
```python
# Access providers via context.custom
config = context.custom.get("config")
embedding_provider = context.custom.get("embedding_provider")
vectordb = context.custom.get("vectordb")
document_index = context.custom.get("document_index")
llm_provider = context.custom.get("llm_provider")
```

**StorageResult Fields**:
```python
storage_result.vector_ids     # IDs of stored vectors
storage_result.namespace      # Target namespace
storage_result.index         # Index name
storage_result.doc_id        # Document ID (from metadata or generated)
storage_result.chunk_count   # Number of chunks stored
storage_result.embedding_model  # Embedding model used
```

**Error Handling**:
PostIngestProcessor enforces `on_error="skip"` at the base class level. Exceptions should be caught and returned as skip actions to avoid blocking ingestion:

```python
try:
    # ... artifact generation ...
    return PostIngestResult(action="allow", artifacts=artifacts)
except Exception as e:
    return PostIngestResult(
        action="skip",
        reason=f"Failed: {e}"
    )
```

**Actions**:
- `allow`: Continue with generated artifacts (if any)
- `skip`: Skip this processor (logged with reason)

Note: No `reject` action - failures should not block ingestion.

**Entry point**: `stache.post_ingest`

**Built-in Implementations**:
- `HeuristicSummaryGenerator`: Extracts headings and content preview for semantic document discovery (see `stache_ai.middleware.postingest.summary`)

**Registration Example**:
```toml
[project.entry-points."stache.post_ingest"]
summary = "my_package.middleware:DocumentSummaryGenerator"
entity_extractor = "my_package.middleware:EntityExtractor"
```

### 4. QueryProcessor - Query Enhancement (Query Phase)

QueryProcessors run **before vector search** and can:
- Expand queries with synonyms
- Inject ACL filters
- Validate queries (rate limiting)
- Rewrite for performance

```python
from stache_ai.middleware.base import QueryProcessor
from stache_ai.middleware.results import QueryProcessorResult
from stache_ai.middleware.context import QueryContext

class ACLEnforcer(QueryProcessor):
    """Inject namespace ACLs into queries."""

    priority = 50  # Run early

    async def process(self, query, filters, context: QueryContext):
        """Process query before search.

        Args:
            query: The search query string
            filters: Optional metadata filters (can be None)
            context: QueryContext with user/tenant info
        """
        # Get user's allowed namespaces
        allowed_ns = get_allowed_namespaces(context.user_id)

        # Inject ACL filter
        if filters is None:
            filters = {}
        filters["namespace"] = {"in": allowed_ns}

        return QueryProcessorResult(
            action="transform",
            query=query,
            filters=filters
        )
```

**Entry point**: `stache.query_processor`

**Context**: `QueryContext` (extends `RequestContext` with query-specific data)

```python
class QueryContext:
    context: RequestContext    # Base context
    query: str                # The search query
    top_k: int               # Number of results
    filters: dict | None     # Metadata filters

    # Property delegation for convenience
    @property
    def request_id(self) -> str: ...
    @property
    def user_id(self) -> str | None: ...
    @property
    def tenant_id(self) -> str | None: ...
    @property
    def namespace(self) -> str: ...
```

**Actions**:
- `allow`: Use original query/filters
- `transform`: Use modified query and/or filters
- `reject`: Block query with reason

### 5. ResultProcessor - Result Enhancement (Query Phase)

ResultProcessors run **after vector search** and can:
- Filter results by ACLs
- Redact PII
- Enrich with metadata
- Rerank results

```python
from stache_ai.middleware.base import ResultProcessor
from stache_ai.middleware.results import ResultProcessorResult, SearchResult

class ACLResultFilter(ResultProcessor):
    """Filter results by user's namespace ACLs."""

    mode = "batch"  # Can be: batch (default) or stream

    async def process(self, results, context):
        """Process search results (batch mode).

        Args:
            results: List of SearchResult objects
            context: QueryContext with user/tenant info

        Returns:
            ResultProcessorResult with filtered results
        """
        allowed_ns = get_allowed_namespaces(context.user_id)

        # Filter to allowed namespaces
        filtered = [
            r for r in results
            if r.metadata.get("namespace") in allowed_ns
        ]

        return ResultProcessorResult(
            action="allow",
            results=filtered
        )
```

**Entry point**: `stache.result_processor`

**SearchResult**: Input/output format
```python
@dataclass
class SearchResult:
    text: str                      # Chunk text
    score: float                   # Similarity score
    metadata: dict                 # Chunk metadata
    vector_id: str                # Vector database ID
```

**Modes**:

**Batch Mode** (default): Process all results at once
```python
async def process(self, results: list[SearchResult], context):
    # Modify entire list and return
    filtered = [r for r in results if ...]
    return ResultProcessorResult(action="allow", results=filtered)
```

**Stream Mode**: Process one result at a time
```python
class StreamingResultProcessor(ResultProcessor):
    mode = "stream"

    async def process_item(self, result, context):
        """Called once per result. Return None to filter out."""
        if not is_allowed(result, context):
            return None  # Filter out
        return result  # Keep
```

**Actions**:
- `allow`: Return results (possibly modified)
- `reject`: Block entire query response

### 6. DeleteObserver - Deletion Auditing (Delete Phase)

DeleteObservers run **before and after deletion** for validation and auditing.

```python
from stache_ai.middleware.base import DeleteObserver, DeleteTarget
from stache_ai.middleware.results import ObserverResult

class DeletionAuditor(DeleteObserver):
    """Audit all document deletions."""

    async def on_delete(self, target, context):
        """Called before deletion (can reject).

        Args:
            target: DeleteTarget with type, doc_id, namespace
            context: Request context
        """
        # Pre-delete validation
        if not can_delete(context.user_id, target.doc_id):
            return ObserverResult(
                action="reject",
                reason="Insufficient permissions"
            )

        return ObserverResult(action="allow")

    async def on_delete_complete(self, target, context):
        """Called after deletion (audit/logging only).

        No return value. Use for sync/logging.
        """
        # Log deletion for audit trail
        log_deletion(
            user_id=context.user_id,
            doc_id=target.doc_id,
            timestamp=context.timestamp
        )
```

**Entry point**: `stache.delete_observer`

**DeleteTarget**: What's being deleted
```python
@dataclass
class DeleteTarget:
    target_type: Literal["document", "namespace", "chunks"]
    doc_id: str | None = None         # For documents
    namespace: str | None = None       # For namespace or document
    chunk_ids: list[str] | None = None # For chunks
```

**Two-Phase Lifecycle**:

1. **on_delete** (pre-delete): Called before deletion
   - Can reject with `ObserverResult(action="reject", reason=...)`
   - If rejected, deletion is blocked
   - If exception, deletion is blocked

2. **on_delete_complete** (post-delete): Called after deletion
   - For audit, sync, logging only
   - Exceptions are logged but don't affect deletion
   - No return value expected

## Context Objects

### RequestContext

Passed to all middleware during ingest/delete operations.

```python
@dataclass
class RequestContext:
    # Required
    request_id: str               # Unique per request
    timestamp: datetime           # Request time (UTC)
    namespace: str                # Document namespace

    # Identity (populated by auth middleware)
    user_id: str | None = None
    tenant_id: str | None = None
    roles: list[str] = []

    # Request metadata
    source: Literal["api", "mcp", "cli"] = "api"
    trace_id: str | None = None   # For distributed tracing
    ip_address: str | None = None

    # Extensible storage for middleware data
    custom: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_fastapi_request(cls, request: Request, namespace: str):
        """Create from FastAPI request (auto-populated from headers)."""
        ...
```

**Using custom data** (proper namespacing):

```python
# In your middleware
context.custom["MyMiddleware.allowed_ns"] = ["ns1", "ns2"]
context.custom["MyMiddleware.user_roles"] = ["editor", "viewer"]

# Other middleware won't collide because they use different keys
```

### QueryContext

Passed to QueryProcessors and ResultProcessors.

```python
@dataclass
class QueryContext:
    context: RequestContext        # Base context (composition)
    query: str                    # The search query
    top_k: int                    # Number of results
    filters: dict[str, Any] | None = None  # Metadata filters

    # Properties delegate to RequestContext for convenience
    @property
    def request_id(self) -> str: return self.context.request_id
    @property
    def user_id(self) -> str | None: return self.context.user_id
    @property
    def namespace(self) -> str: return self.context.namespace
    # ... etc
```

## Error Handling

### Enrichers - Fail Fast

Enricher exceptions **block ingestion**:

```python
class StrictValidator(Enricher):
    async def process(self, content, metadata, context):
        if not passes_validation(content):
            # This blocks ingestion
            return EnrichmentResult(action="reject", reason="...")

        # Or raise to propagate exception
        if not has_license(content):
            raise PermissionError("Content requires license")
```

### ChunkObservers - Advisory Only

Observer exceptions **don't block ingestion** (they're logged):

```python
class QuotaCheck(ChunkObserver):
    on_error = "allow"  # Continue even if observer fails

    async def on_chunks_stored(self, chunks, storage_result, context):
        # If you return reject, it's advisory only (logged, not rolled back)
        # If you raise, it's caught and logged

        return ObserverResult(action="reject", reason="quota exceeded")
        # -> Logs warning, ingestion continues
```

### QueryProcessors - Fail Fast

QueryProcessor exceptions **block queries**:

```python
async def process(self, query, filters, context):
    if rate_limit_exceeded(context.user_id):
        return QueryProcessorResult(action="reject", reason="Rate limited")

    # Or raise to propagate exception
    if malicious_pattern_detected(query):
        raise SecurityError("Query blocked by security policy")
```

### ResultProcessors - Fail Fast

ResultProcessor exceptions **block queries**:

```python
async def process(self, results, context):
    if not can_serve_results(context.user_id):
        return ResultProcessorResult(action="reject", reason="Access denied")

    # Or raise
    if error_in_processing(results):
        raise RuntimeError("Result processing failed")
```

### DeleteObservers - Two Phases

- **on_delete** (pre-delete): Exceptions **block deletion**
- **on_delete_complete** (post-delete): Exceptions **don't block deletion** (logged)

## Ordering and Dependencies

### Priority-Based Execution

Middleware within the same type execute in priority order (lower = earlier):

```python
class FirstEnricher(Enricher):
    priority = 50  # Runs first

class SecondEnricher(Enricher):
    priority = 100  # Runs second

class ThirdEnricher(Enricher):
    priority = 200  # Runs third
```

### Dependency-Based Ordering

For explicit ordering, use `depends_on` and `runs_before`:

```python
class BaselineProcessor(QueryProcessor):
    priority = 100

class EnhancedProcessor(QueryProcessor):
    depends_on = ("BaselineProcessor",)  # Must run after BaselineProcessor
    priority = 100
```

**Rules**:
- Dependencies on class names that don't exist are ignored
- Circular dependencies raise `ValueError` during chain setup
- Within the same priority, tiebreaker is undefined (don't rely on it)

## Advanced Patterns

### Lazy Loading Heavy Dependencies

For middleware with heavy dependencies (ML models, large libraries):

```python
class AudioTranscriber(Enricher):
    """Transcribe audio to text using OpenAI Whisper."""

    _whisper = None  # Class-level cache

    @classmethod
    def _load_whisper(cls):
        if cls._whisper is None:
            import whisper
            # Load once, reuse across requests
            cls._whisper = whisper.load_model("base")
        return cls._whisper

    async def process(self, content, metadata, context):
        if not content.startswith("data:audio/"):
            return EnrichmentResult(action="allow")

        try:
            whisper = self._load_whisper()
            # Transcribe...
            return EnrichmentResult(action="transform", content=transcribed_text)
        except Exception as e:
            return EnrichmentResult(action="reject", reason=str(e))
```

### Conditional Processing

Check if middleware should process based on content:

```python
class ImageToText(Enricher):
    phase = "extract"

    @classmethod
    def can_process(cls, content: str, metadata: dict) -> bool:
        """Check if content is an image."""
        return metadata.get("content_type", "").startswith("image/")

    async def process(self, content, metadata, context):
        # Only called if can_process() returns True
        # Use OCR to extract text...
        return EnrichmentResult(action="transform", content=extracted_text)
```

### Timeouts

Prevent hung middleware from blocking requests:

```python
class SlowAnalyzer(Enricher):
    timeout_seconds = 5.0  # Timeout after 5 seconds
    on_error = "allow"     # If timeout, continue anyway

    async def process(self, content, metadata, context):
        # If this takes > 5 seconds, it's timed out and skipped
        result = await self.slow_analysis(content)
        return EnrichmentResult(action="transform", content=result)
```

### Testing Your Middleware

Use the mock utilities in `stache_ai.middleware.testing`:

```python
from stache_ai.middleware.testing import (
    MockEnricher, MockQueryProcessor, MockResultProcessor,
    MockChunkObserver, MockDeleteObserver, RecordingMiddleware
)

# Record calls for assertions
recording = RecordingMiddleware()

# Mock with specific return values
processor = MockQueryProcessor(
    action="transform",
    query="expanded query"
)

assert processor.call_count == 1
assert processor.last_query == "original query"
```

## Example: Complete Middleware Implementation

Here's a realistic example of a PII redaction middleware:

```python
from stache_ai.middleware.base import ResultProcessor
from stache_ai.middleware.results import ResultProcessorResult, SearchResult
from stache_ai.middleware.context import QueryContext

class PIIRedactor(ResultProcessor):
    """Redact personally identifiable information from results."""

    priority = 100
    on_error = "reject"  # Fail if redaction fails

    PATTERNS = {
        "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
        "phone": r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",
        "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
        "credit_card": r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
    }

    async def process(
        self,
        results: list[SearchResult],
        context: QueryContext
    ) -> ResultProcessorResult:
        """Redact PII from results."""

        # Skip redaction for admin users
        if "admin" in context.roles:
            return ResultProcessorResult(action="allow", results=results)

        try:
            import re

            redacted = []
            for result in results:
                redacted_text = result.text

                # Apply all patterns
                for pattern_name, pattern in self.PATTERNS.items():
                    redacted_text = re.sub(
                        pattern,
                        f"[REDACTED_{pattern_name.upper()}]",
                        redacted_text,
                        flags=re.IGNORECASE
                    )

                redacted.append(SearchResult(
                    text=redacted_text,
                    score=result.score,
                    metadata=result.metadata,
                    vector_id=result.vector_id
                ))

            return ResultProcessorResult(action="allow", results=redacted)

        except Exception as e:
            # on_error=reject means exceptions fail the query
            raise RuntimeError(f"PII redaction failed: {e}")
```

Register in entry points:

```toml
[project.entry-points."stache.result_processor"]
pii_redactor = "my_package.middleware:PIIRedactor"
```

Use in code:

```python
# Automatically loaded on first use
result = await pipeline.query(
    question="Find documents about john.smith@example.com",
    top_k=10,
    synthesize=True
)
# Results have emails redacted to [REDACTED_EMAIL]
```

## Lifecycle Example

Here's what happens during a request with multiple middleware:

```
1. REQUEST RECEIVED
   └─ ingest_text(content, metadata, namespace)

2. CONTEXT CREATION
   └─ RequestContext created with user_id, tenant_id, roles

3. ENRICHMENT PHASE
   ├─ on_chain_start() called for all enrichers
   ├─ Enricher 1 (priority=50) processes content
   ├─ Enricher 2 (priority=100) processes transformed content
   ├─ Enricher 3 (priority=200) processes transformed content
   └─ on_chain_complete() called for all enrichers

4. CHUNKING & EMBEDDING
   └─ Content is split into chunks and embedded

5. STORAGE
   └─ Chunks stored in vector database

6. OBSERVATION PHASE
   ├─ ChunkObserver 1 called (advisory only)
   ├─ ChunkObserver 2 called (advisory only)
   └─ Exceptions logged but not propagated

7. RESPONSE
   └─ Return success with chunk IDs and count
```

## Best Practices

1. **Use namespaced custom data**: `context.custom["YourMiddleware.key"]`
2. **Log thoughtfully**: Use request_id for traceability
3. **Handle timeouts gracefully**: Set `timeout_seconds` for long operations
4. **Fail fast when needed**: Raise exceptions in critical paths
5. **Test with mocks**: Use `stache_ai.middleware.testing` utilities
6. **Document your actions**: Include docstrings explaining behavior
7. **Version your interface**: Don't change method signatures in maintenance releases
8. **Use lazy loading**: For heavy dependencies like ML models
9. **Respect mode settings**: Implement both `process()` (batch) and `process_item()` (stream)
10. **Consider performance**: Chain runs synchronously per middleware

## Metrics and Observability

### Monitoring PostIngestProcessor Performance

PostIngestProcessors run after chunk storage, so monitoring their performance helps identify bottlenecks:

```python
from stache_ai.middleware.base import PostIngestProcessor, StorageResult
from stache_ai.middleware.results import PostIngestResult
from stache_ai.middleware.context import RequestContext
import logging
import time

logger = logging.getLogger(__name__)

class InstrumentedSummaryGenerator(PostIngestProcessor):
    """Summary generator with performance tracking."""

    priority = 50

    async def process(
        self,
        chunks: list[tuple[str, dict]],
        storage_result: StorageResult,
        context: RequestContext
    ) -> PostIngestResult:
        start_time = time.monotonic()

        try:
            # ... summary generation logic ...

            duration = time.monotonic() - start_time

            # Log metrics
            logger.info(
                f"Summary generated for doc_id={storage_result.doc_id} "
                f"in {duration:.3f}s "
                f"(chunks={storage_result.chunk_count}, "
                f"request_id={context.request_id})"
            )

            return PostIngestResult(
                action="allow",
                artifacts={
                    "summary": summary_text,
                    "processing_time": duration
                }
            )

        except Exception as e:
            duration = time.monotonic() - start_time
            logger.error(
                f"Summary generation failed for doc_id={storage_result.doc_id} "
                f"after {duration:.3f}s: {e}",
                extra={"request_id": context.request_id}
            )
            return PostIngestResult(
                action="skip",
                reason=f"Failed: {e}"
            )
```

### Tracking Artifact Generation

Monitor which artifacts are being generated and their sizes:

```python
class EntityExtractor(PostIngestProcessor):
    priority = 100

    async def process(self, chunks, storage_result, context):
        # ... extract entities ...

        logger.info(
            f"Extracted {len(entities)} entities from doc_id={storage_result.doc_id}",
            extra={
                "doc_id": storage_result.doc_id,
                "entity_count": len(entities),
                "namespace": storage_result.namespace,
                "request_id": context.request_id
            }
        )

        return PostIngestResult(
            action="allow",
            artifacts={
                "entities": entities,
                "entity_count": len(entities)
            }
        )
```

### Key Metrics to Track

For **PostIngestProcessor** implementations:

1. **Processing Time**: Duration from chunks received to artifacts returned
2. **Skip Rate**: Percentage of documents where processing was skipped
3. **Artifact Size**: Size of generated artifacts (summaries, embeddings, etc.)
4. **Chunk Count**: Correlation between chunk count and processing time
5. **Provider Latency**: Time spent calling embedding/vector DB providers
6. **Error Rate**: Frequency of exceptions caught and returned as skip

### Request Context Fields for Tracing

Use these fields from `RequestContext` for distributed tracing:

```python
async def process(self, chunks, storage_result, context):
    logger.info(
        "Processing document",
        extra={
            "request_id": context.request_id,  # Unique per request
            "trace_id": context.trace_id,      # Optional external trace ID
            "user_id": context.user_id,        # User identity
            "tenant_id": context.tenant_id,    # Multi-tenant tracking
            "namespace": context.namespace,    # Document namespace
            "source": context.source,          # "api", "mcp", or "cli"
            "timestamp": context.timestamp.isoformat()
        }
    )
```

### Structured Logging Example

```python
import structlog

logger = structlog.get_logger()

class LoggingPostIngestProcessor(PostIngestProcessor):
    async def process(self, chunks, storage_result, context):
        log = logger.bind(
            middleware="LoggingPostIngestProcessor",
            request_id=context.request_id,
            doc_id=storage_result.doc_id,
            namespace=storage_result.namespace
        )

        log.info("Starting artifact generation", chunk_count=len(chunks))

        try:
            # ... processing ...
            log.info("Artifact generation complete", artifact_count=len(artifacts))
            return PostIngestResult(action="allow", artifacts=artifacts)
        except Exception as e:
            log.error("Artifact generation failed", error=str(e))
            return PostIngestResult(action="skip", reason=str(e))
```

### CloudWatch Metrics (AWS Deployment)

For Lambda deployments, emit CloudWatch metrics:

```python
import boto3

cloudwatch = boto3.client('cloudwatch')

class CloudWatchPostIngestProcessor(PostIngestProcessor):
    async def process(self, chunks, storage_result, context):
        start = time.time()

        try:
            result = await self._generate_artifacts(chunks, storage_result, context)

            # Emit success metric
            cloudwatch.put_metric_data(
                Namespace='Stache/PostIngest',
                MetricData=[
                    {
                        'MetricName': 'ProcessingTime',
                        'Value': time.time() - start,
                        'Unit': 'Seconds',
                        'Dimensions': [
                            {'Name': 'Processor', 'Value': self.__class__.__name__},
                            {'Name': 'Namespace', 'Value': storage_result.namespace}
                        ]
                    },
                    {
                        'MetricName': 'ChunkCount',
                        'Value': len(chunks),
                        'Unit': 'Count'
                    }
                ]
            )

            return result

        except Exception as e:
            # Emit error metric
            cloudwatch.put_metric_data(
                Namespace='Stache/PostIngest',
                MetricData=[
                    {
                        'MetricName': 'Errors',
                        'Value': 1,
                        'Unit': 'Count',
                        'Dimensions': [
                            {'Name': 'Processor', 'Value': self.__class__.__name__}
                        ]
                    }
                ]
            )

            return PostIngestResult(action="skip", reason=str(e))
```

### Performance Benchmarking

Use the built-in timing from `context.timestamp`:

```python
async def process(self, chunks, storage_result, context):
    request_start = context.timestamp

    # ... processing ...

    from datetime import datetime, timezone
    processing_duration = (datetime.now(timezone.utc) - request_start).total_seconds()

    return PostIngestResult(
        action="allow",
        artifacts={
            "summary": summary,
            "metrics": {
                "request_duration": processing_duration,
                "chunk_count": len(chunks),
                "summary_length": len(summary)
            }
        }
    )
```

## Deployment

### Local Development

```python
# In your app initialization
from my_package.middleware import MyEnricher

pipeline = RAGPipeline()
pipeline._enrichers.append(MyEnricher())
```

### Production (via Entry Points)

```bash
# Install package with entry points
pip install my_package
```

No code changes needed - plugins are auto-discovered!

### Selective Loading

```python
import os
from stache_ai.rag.pipeline import RAGPipeline

# Load only specific plugins
pipeline = RAGPipeline()

if os.getenv("ENABLE_PII_REDACTION"):
    # Plugin is loaded on first access
    # Custom loaders can filter which plugins to load
    pass
```

## Troubleshooting

### Middleware not being called?

1. Check entry point is registered in `setup.py`/`pyproject.toml`
2. Verify class name matches entry point
3. Check middleware is in the right pipeline phase
4. Enable debug logging to see loaded plugins

```python
import logging
logging.getLogger("stache_ai.providers.plugin_loader").setLevel(logging.DEBUG)
```

### Middleware is slow?

1. Set `timeout_seconds` to prevent hangs
2. Use lazy loading for expensive dependencies
3. Profile with context.timestamp to measure
4. Consider `on_error = "skip"` for non-critical middleware

### Circular dependencies?

```
ValueError: Circular dependency detected in middleware chain
```

Check your `depends_on` and `runs_before` declarations don't form cycles.

### Plugin not loaded?

```python
# Debug plugin loading
from stache_ai.providers.plugin_loader import PluginLoader

loader = PluginLoader(config)
plugins = loader.load_plugins("stache.enrichment")
for plugin in plugins:
    print(f"Loaded: {plugin.__name__}")
```

## API Reference

### Base Classes

- `MiddlewareBase`: Base for all middleware (priority, dependencies, timeouts)
- `Enricher`: Content transformation before chunking
- `ChunkObserver`: Storage auditing (advisory only)
- `PostIngestProcessor`: Artifact generation after chunk storage
- `QueryProcessor`: Query rewriting before search
- `ResultProcessor`: Result filtering after search
- `DeleteObserver`: Deletion validation and auditing

### Result Classes

- `EnrichmentResult`: Action, content, metadata (allow/transform/reject)
- `ObserverResult`: Action (allow/reject)
- `PostIngestResult`: Action, artifacts (allow/skip)
- `QueryProcessorResult`: Action, query, filters (allow/transform/reject)
- `ResultProcessorResult`: Action, results (allow/reject)
- `SearchResult`: text, score, metadata, vector_id

### Data Classes

- `StorageResult`: Information about stored chunks (vector_ids, namespace, doc_id, chunk_count, embedding_model)
- `DeleteTarget`: What is being deleted (target_type, doc_id, namespace, chunk_ids)

### Context Classes

- `RequestContext`: user_id, tenant_id, roles, namespace, custom data
- `QueryContext`: RequestContext + query, top_k, filters

### Dataclasses

- `StorageResult`: vector_ids, chunk_count, embedding_model
- `DeleteTarget`: target_type, doc_id, namespace, chunk_ids

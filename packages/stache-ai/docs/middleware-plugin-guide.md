# Middleware Plugin Developer Guide

## Overview

The Stache middleware plugin architecture enables developers to extend the RAG pipeline with custom functionality without modifying core code. Plugins integrate at critical points in the request lifecycle:

- **Enrichment**: Transform content before chunking (ingest phase)
- **Chunk Observation**: Monitor/audit chunks after storage (ingest phase)
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

### 3. QueryProcessor - Query Enhancement (Query Phase)

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

### 4. ResultProcessor - Result Enhancement (Query Phase)

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

### 5. DeleteObserver - Deletion Auditing (Delete Phase)

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
- `QueryProcessor`: Query rewriting before search
- `ResultProcessor`: Result filtering after search
- `ChunkObserver`: Storage auditing (advisory only)
- `DeleteObserver`: Deletion validation and auditing

### Result Classes

- `EnrichmentResult`: Action, content, metadata (allow/transform/reject)
- `QueryProcessorResult`: Action, query, filters (allow/transform/reject)
- `ResultProcessorResult`: Action, results (allow/reject)
- `ObserverResult`: Action (allow/reject)
- `SearchResult`: text, score, metadata, vector_id

### Context Classes

- `RequestContext`: user_id, tenant_id, roles, namespace, custom data
- `QueryContext`: RequestContext + query, top_k, filters

### Dataclasses

- `StorageResult`: vector_ids, chunk_count, embedding_model
- `DeleteTarget`: target_type, doc_id, namespace, chunk_ids

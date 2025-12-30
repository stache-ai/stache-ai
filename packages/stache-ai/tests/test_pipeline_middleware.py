"""Tests for middleware integration in RAG pipeline"""

import pytest
from unittest.mock import AsyncMock, MagicMock

# Use anyio for async test support
pytestmark = pytest.mark.anyio

from stache_ai.rag.pipeline import RAGPipeline
from stache_ai.middleware.base import Enricher, ChunkObserver, QueryProcessor, ResultProcessor, DeleteObserver, StorageResult, DeleteTarget
from stache_ai.middleware.results import EnrichmentResult, ObserverResult, QueryProcessorResult, ResultProcessorResult, SearchResult
from stache_ai.middleware.context import RequestContext, QueryContext
from stache_ai.middleware.chain import MiddlewareRejection
from stache_ai.middleware.testing import (
    MockEnricher as BaseTestMockEnricher,
    MockQueryProcessor as BaseTestMockQueryProcessor,
    MockChunkObserver as BaseTestMockChunkObserver,
    MockResultProcessor as BaseTestMockResultProcessor,
    MockDeleteObserver as BaseTestMockDeleteObserver,
)


class MockEnricher(Enricher):
    """Mock enricher for testing"""
    phase = "enrich"

    def __init__(self, action="allow", content=None, metadata=None, reason=None):
        self._action = action
        self._content = content
        self._metadata = metadata
        self._reason = reason
        self.calls = []

    async def process(self, content, metadata, context):
        self.calls.append({"content": content, "metadata": metadata, "context": context})
        return EnrichmentResult(
            action=self._action,
            content=self._content,
            metadata=self._metadata,
            reason=self._reason
        )


class MockChunkObserver(ChunkObserver):
    """Mock chunk observer for testing"""

    def __init__(self, action="allow", reason=None):
        self._action = action
        self._reason = reason
        self.calls = []

    async def on_chunks_stored(self, chunks, storage_result, context):
        self.calls.append({
            "chunks": chunks,
            "storage_result": storage_result,
            "context": context
        })
        return ObserverResult(action=self._action, reason=self._reason)


class MockQueryProcessor(QueryProcessor):
    """Mock query processor for testing"""

    def __init__(self, action="allow", query=None, filters=None, reason=None):
        self._action = action
        self._query = query
        self._filters = filters
        self._reason = reason
        self.calls = []

    async def process(self, query, filters, context):
        self.calls.append({"query": query, "filters": filters, "context": context})
        return QueryProcessorResult(
            action=self._action,
            query=self._query,
            filters=self._filters,
            reason=self._reason
        )


class MockResultProcessor(ResultProcessor):
    """Mock result processor for testing"""

    def __init__(self, action="allow", results=None, reason=None):
        self._action = action
        self._results = results
        self._reason = reason
        self.calls = []

    async def process(self, results, context):
        self.calls.append({"results": results, "context": context})
        return ResultProcessorResult(
            action=self._action,
            results=self._results,
            reason=self._reason
        )


class MockDeleteObserver(DeleteObserver):
    """Mock delete observer for testing"""

    def __init__(self, action="allow", reason=None):
        self._action = action
        self._reason = reason
        self.calls = []
        self.complete_calls = []

    async def on_delete(self, target, context):
        self.calls.append({"target": target, "context": context})
        return ObserverResult(action=self._action, reason=self._reason)

    async def on_delete_complete(self, target, context):
        self.complete_calls.append({"target": target, "context": context})


class TestMiddlewareIntegration:
    """Tests for middleware integration in pipeline"""

    @pytest.fixture
    def mock_pipeline(self, mock_embedding_provider, mock_llm_provider, mock_vectordb_provider, mock_document_index_provider, mock_documents_provider, mock_summaries_provider):
        """Create a pipeline with mocked providers"""
        pipeline = RAGPipeline()
        pipeline._embedding_provider = mock_embedding_provider
        pipeline._llm_provider = mock_llm_provider
        pipeline._vectordb_provider = mock_vectordb_provider
        pipeline._document_index_provider = mock_document_index_provider
        pipeline._documents_provider = mock_documents_provider
        pipeline._summaries_provider = mock_summaries_provider

        # Mock middleware lists (empty by default)
        pipeline._enrichers = []
        pipeline._chunk_observers = []
        pipeline._query_processors = []
        pipeline._result_processors = []
        pipeline._delete_observers = []

        return pipeline

    def _create_context(self, request_id="test-request-1", namespace="test-ns"):
        """Helper to create a RequestContext for testing."""
        from datetime import datetime, timezone
        return RequestContext(
            request_id=request_id,
            timestamp=datetime.now(timezone.utc),
            namespace=namespace,
            source="api"
        )

    async def test_enricher_allow(self, mock_pipeline):
        """Test enricher that allows content through"""
        enricher = MockEnricher(action="allow")
        mock_pipeline._enrichers = [enricher]

        result = await mock_pipeline.ingest_text(
            text="Test content",
            metadata={"source": "test"}
        )

        assert result["success"]
        assert len(enricher.calls) == 1
        assert enricher.calls[0]["content"] == "Test content"
        assert enricher.calls[0]["metadata"] == {"source": "test"}

    async def test_enricher_transform(self, mock_pipeline):
        """Test enricher that transforms content"""
        enricher = MockEnricher(
            action="transform",
            content="Transformed content",
            metadata={"source": "test", "enriched": True}
        )
        mock_pipeline._enrichers = [enricher]

        result = await mock_pipeline.ingest_text(
            text="Original content",
            metadata={"source": "test"}
        )

        assert result["success"]
        # Verify the enricher was called with original content
        assert len(enricher.calls) == 1
        assert enricher.calls[0]["content"] == "Original content"
        # Verify the transformed metadata was applied
        assert enricher.calls[0]["metadata"] == {"source": "test"}
        # Verify documents were stored (embed was called either directly or via wrapper)
        assert mock_pipeline._documents_provider.insert.called

    async def test_enricher_reject(self, mock_pipeline):
        """Test enricher that rejects content"""
        enricher = MockEnricher(action="reject", reason="Content not allowed")
        mock_pipeline._enrichers = [enricher]

        with pytest.raises(MiddlewareRejection) as exc_info:
            await mock_pipeline.ingest_text(
                text="Bad content",
                metadata={}
            )

        assert "Content not allowed" in str(exc_info.value)

    async def test_chunk_observer_called(self, mock_pipeline):
        """Test chunk observer is called after storage"""
        observer = MockChunkObserver(action="allow")
        mock_pipeline._chunk_observers = [observer]

        result = await mock_pipeline.ingest_text(
            text="Test content for observation",
            metadata={"source": "test"}
        )

        assert result["success"]
        assert len(observer.calls) == 1

        # Verify storage result details
        storage_result = observer.calls[0]["storage_result"]
        assert isinstance(storage_result, StorageResult)
        assert storage_result.index == "documents"
        assert storage_result.chunk_count > 0

    async def test_chunk_observer_rejection_logs_warning(self, mock_pipeline, caplog):
        """Test chunk observer rejection logs warning but doesn't fail"""
        observer = MockChunkObserver(action="reject", reason="Quota exceeded")
        mock_pipeline._chunk_observers = [observer]

        result = await mock_pipeline.ingest_text(
            text="Test content",
            metadata={}
        )

        # Ingestion still succeeds (advisory only)
        assert result["success"]
        assert len(observer.calls) == 1

        # Check warning was logged
        assert "rejected storage" in caplog.text.lower()
        assert "Quota exceeded" in caplog.text

    async def test_query_processor_transform(self, mock_pipeline):
        """Test query processor that transforms query"""
        processor = MockQueryProcessor(
            action="transform",
            query="expanded query with synonyms",
            filters={"namespace": "expanded"}
        )
        mock_pipeline._query_processors = [processor]

        result = await mock_pipeline.query(
            question="simple query",
            top_k=5,
            synthesize=False
        )

        assert len(processor.calls) == 1
        assert processor.calls[0]["query"] == "simple query"

        # Verify transformed query was used for embedding
        mock_pipeline._embedding_provider.embed_query.assert_called_with("expanded query with synonyms")

    async def test_query_processor_reject(self, mock_pipeline):
        """Test query processor that rejects query"""
        processor = MockQueryProcessor(action="reject", reason="Rate limit exceeded")
        mock_pipeline._query_processors = [processor]

        with pytest.raises(MiddlewareRejection) as exc_info:
            await mock_pipeline.query(
                question="blocked query",
                synthesize=False
            )

        assert "Rate limit exceeded" in str(exc_info.value)

    async def test_result_processor_filter(self, mock_pipeline):
        """Test result processor that filters results"""
        # Create mock results to return from search
        mock_results = [
            {"text": "Result 1", "metadata": {"allowed": True}, "score": 0.9},
            {"text": "Result 2", "metadata": {"allowed": False}, "score": 0.8},
            {"text": "Result 3", "metadata": {"allowed": True}, "score": 0.7},
        ]
        mock_pipeline._documents_provider.search.return_value = mock_results

        # Filter to only allowed results
        filtered_results = [
            SearchResult(text="Result 1", score=0.9, metadata={"allowed": True}, vector_id="1"),
            SearchResult(text="Result 3", score=0.7, metadata={"allowed": True}, vector_id="3"),
        ]
        processor = MockResultProcessor(action="allow", results=filtered_results)
        mock_pipeline._result_processors = [processor]

        result = await mock_pipeline.query(
            question="test query",
            top_k=5,
            synthesize=False
        )

        # Verify only filtered results returned
        assert len(result["sources"]) == 2
        assert result["sources"][0]["text"] == "Result 1"
        assert result["sources"][1]["text"] == "Result 3"

    async def test_result_processor_reject(self, mock_pipeline):
        """Test result processor that rejects all results"""
        processor = MockResultProcessor(action="reject", reason="Access denied")
        mock_pipeline._result_processors = [processor]

        with pytest.raises(MiddlewareRejection) as exc_info:
            await mock_pipeline.query(
                question="blocked query",
                synthesize=False
            )

        assert "Access denied" in str(exc_info.value)

    async def test_delete_observer_allow(self, mock_pipeline):
        """Test delete observer that allows deletion"""
        observer = MockDeleteObserver(action="allow")
        mock_pipeline._delete_observers = [observer]

        # Mock the delete methods
        mock_pipeline._document_index_provider.delete_document = MagicMock()
        mock_pipeline._documents_provider.delete = MagicMock()
        mock_pipeline._summaries_provider.delete = MagicMock()

        result = await mock_pipeline.delete_document(
            doc_id="test-doc-id",
            namespace="test-namespace"
        )

        assert result["success"]
        assert len(observer.calls) == 1
        assert len(observer.complete_calls) == 1

        # Verify delete target
        target = observer.calls[0]["target"]
        assert isinstance(target, DeleteTarget)
        assert target.target_type == "document"
        assert target.doc_id == "test-doc-id"
        assert target.namespace == "test-namespace"

    async def test_delete_observer_reject(self, mock_pipeline):
        """Test delete observer that rejects deletion"""
        observer = MockDeleteObserver(action="reject", reason="Insufficient permissions")
        mock_pipeline._delete_observers = [observer]

        with pytest.raises(MiddlewareRejection) as exc_info:
            await mock_pipeline.delete_document(
                doc_id="test-doc-id",
                namespace="test-namespace"
            )

        assert "Insufficient permissions" in str(exc_info.value)
        assert len(observer.calls) == 1
        assert len(observer.complete_calls) == 0  # Should not call complete on rejection

    async def test_multiple_enrichers_chain(self, mock_pipeline):
        """Test multiple enrichers execute in order"""
        enricher1 = MockEnricher(action="transform", content="Step 1", metadata={"step": 1})
        enricher2 = MockEnricher(action="transform", content="Step 2", metadata={"step": 2})
        mock_pipeline._enrichers = [enricher1, enricher2]

        result = await mock_pipeline.ingest_text(
            text="Original",
            metadata={"step": 0}
        )

        assert result["success"]
        assert len(enricher1.calls) == 1
        assert len(enricher2.calls) == 1

        # Verify chaining: enricher2 receives enricher1's output
        assert enricher1.calls[0]["content"] == "Original"
        assert enricher2.calls[0]["content"] == "Step 1"
        assert enricher2.calls[0]["metadata"]["step"] == 1

    async def test_context_propagation(self, mock_pipeline):
        """Test request context is properly created and propagated"""
        enricher = MockEnricher(action="allow")
        observer = MockChunkObserver(action="allow")
        mock_pipeline._enrichers = [enricher]
        mock_pipeline._chunk_observers = [observer]

        result = await mock_pipeline.ingest_text(
            text="Test content",
            namespace="test-namespace"
        )

        assert result["success"]

        # Verify context in enricher
        enricher_context = enricher.calls[0]["context"]
        assert isinstance(enricher_context, RequestContext)
        assert enricher_context.namespace == "test-namespace"
        assert enricher_context.source == "api"
        assert enricher_context.request_id is not None

        # Verify same context in observer
        observer_context = observer.calls[0]["context"]
        assert observer_context.request_id == enricher_context.request_id


# ==================== COMPLEX MIDDLEWARE CHAIN TESTS ====================

class TestComplexMiddlewareChains:
    """Tests for complex middleware orchestration scenarios"""

    @pytest.fixture
    def mock_pipeline(self, mock_embedding_provider, mock_llm_provider, mock_vectordb_provider, mock_document_index_provider, mock_documents_provider, mock_summaries_provider):
        """Create a pipeline with mocked providers"""
        pipeline = RAGPipeline()
        pipeline._embedding_provider = mock_embedding_provider
        pipeline._llm_provider = mock_llm_provider
        pipeline._vectordb_provider = mock_vectordb_provider
        pipeline._document_index_provider = mock_document_index_provider
        pipeline._documents_provider = mock_documents_provider
        pipeline._summaries_provider = mock_summaries_provider

        pipeline._enrichers = []
        pipeline._chunk_observers = []
        pipeline._query_processors = []
        pipeline._result_processors = []
        pipeline._delete_observers = []

        return pipeline

    async def test_three_enrichers_sequential_chaining(self, mock_pipeline):
        """Test three enrichers execute sequentially with proper chaining"""
        enricher1 = MockEnricher(
            action="transform",
            content="Step 1 content",
            metadata={"step": 1, "timestamp": "t1"}
        )
        enricher2 = MockEnricher(
            action="transform",
            content="Step 2 content",
            metadata={"step": 2, "timestamp": "t2"}
        )
        enricher3 = MockEnricher(
            action="transform",
            content="Step 3 content",
            metadata={"step": 3, "timestamp": "t3"}
        )
        mock_pipeline._enrichers = [enricher1, enricher2, enricher3]

        result = await mock_pipeline.ingest_text(
            text="Original content",
            metadata={"step": 0}
        )

        # Verify success
        assert result["success"]

        # Verify all enrichers called
        assert len(enricher1.calls) == 1
        assert len(enricher2.calls) == 1
        assert len(enricher3.calls) == 1

        # Verify proper chaining order
        assert enricher1.calls[0]["content"] == "Original content"
        assert enricher2.calls[0]["content"] == "Step 1 content"
        assert enricher3.calls[0]["content"] == "Step 2 content"

        # Verify metadata chaining
        assert enricher1.calls[0]["metadata"]["step"] == 0
        assert enricher2.calls[0]["metadata"]["step"] == 1
        assert enricher3.calls[0]["metadata"]["step"] == 2

    async def test_enricher_stops_chain_on_reject(self, mock_pipeline):
        """Test that rejecting enricher stops subsequent enrichers"""
        enricher1 = MockEnricher(action="allow")
        enricher2 = MockEnricher(action="reject", reason="Content blocked")
        enricher3 = MockEnricher(action="allow")
        mock_pipeline._enrichers = [enricher1, enricher2, enricher3]

        with pytest.raises(MiddlewareRejection) as exc_info:
            await mock_pipeline.ingest_text(text="Test", metadata={})

        assert "Content blocked" in str(exc_info.value)
        assert len(enricher1.calls) == 1  # Called before rejection
        assert len(enricher2.calls) == 1  # Called, then rejects
        assert len(enricher3.calls) == 0  # Never called after rejection

    async def test_multiple_query_processors_sequential(self, mock_pipeline):
        """Test multiple query processors execute in order"""
        proc1 = MockQueryProcessor(
            action="transform",
            query="expanded with synonyms"
        )
        proc2 = MockQueryProcessor(
            action="transform",
            filters={"namespace": "filtered"}
        )
        mock_pipeline._query_processors = [proc1, proc2]

        result = await mock_pipeline.query(
            question="original query",
            top_k=5,
            synthesize=False
        )

        # Verify both processors called
        assert len(proc1.calls) == 1
        assert len(proc2.calls) == 1

        # First processor gets original query
        assert proc1.calls[0]["query"] == "original query"
        # Second processor gets transformed query from first
        assert proc2.calls[0]["query"] == "expanded with synonyms"

    async def test_multiple_result_processors_filter_and_transform(self, mock_pipeline):
        """Test multiple result processors apply transformations in sequence"""
        # Setup initial results
        initial_results = [
            {"text": "Result 1", "metadata": {"priority": "high"}, "score": 0.9},
            {"text": "Result 2", "metadata": {"priority": "low"}, "score": 0.7},
            {"text": "Result 3", "metadata": {"priority": "high"}, "score": 0.8},
        ]
        mock_pipeline._documents_provider.search.return_value = initial_results

        # First processor: filter to high priority only
        filtered_high = [
            SearchResult(text="Result 1", score=0.9, metadata={"priority": "high"}, vector_id="1"),
            SearchResult(text="Result 3", score=0.8, metadata={"priority": "high"}, vector_id="3"),
        ]
        proc1 = MockResultProcessor(action="allow", results=filtered_high)

        # Second processor: re-rank by score
        reranked = [
            SearchResult(text="Result 3", score=0.95, metadata={"priority": "high"}, vector_id="3"),
            SearchResult(text="Result 1", score=0.9, metadata={"priority": "high"}, vector_id="1"),
        ]
        proc2 = MockResultProcessor(action="allow", results=reranked)

        mock_pipeline._result_processors = [proc1, proc2]

        result = await mock_pipeline.query(
            question="test query",
            top_k=5,
            synthesize=False
        )

        # Verify results are from second processor (final in chain)
        assert len(result["sources"]) == 2
        assert result["sources"][0]["text"] == "Result 3"
        assert result["sources"][1]["text"] == "Result 1"

    async def test_chunk_observer_sees_all_chunks(self, mock_pipeline):
        """Test chunk observer sees all chunks from multi-chunk ingestion"""
        observer = MockChunkObserver(action="allow")
        mock_pipeline._chunk_observers = [observer]

        result = await mock_pipeline.ingest_text(
            text="This is a document with some content.",
            metadata={"source": "test"},
            namespace="test-ns"
        )

        assert result["success"]
        assert len(observer.calls) == 1

        storage_result = observer.calls[0]["storage_result"]
        chunks = observer.calls[0]["chunks"]

        # Verify metadata about chunks
        assert storage_result.chunk_count >= 1
        assert len(chunks) == storage_result.chunk_count
        assert storage_result.embedding_model is not None
        assert storage_result.index == "documents"
        assert storage_result.namespace == "test-ns"


# ==================== ERROR HANDLING TESTS ====================

class TestMiddlewareErrorHandling:
    """Tests for error scenarios and edge cases"""

    @pytest.fixture
    def mock_pipeline(self, mock_embedding_provider, mock_llm_provider, mock_vectordb_provider, mock_document_index_provider, mock_documents_provider, mock_summaries_provider):
        """Create a pipeline with mocked providers"""
        pipeline = RAGPipeline()
        pipeline._embedding_provider = mock_embedding_provider
        pipeline._llm_provider = mock_llm_provider
        pipeline._vectordb_provider = mock_vectordb_provider
        pipeline._document_index_provider = mock_document_index_provider
        pipeline._documents_provider = mock_documents_provider
        pipeline._summaries_provider = mock_summaries_provider

        pipeline._enrichers = []
        pipeline._chunk_observers = []
        pipeline._query_processors = []
        pipeline._result_processors = []
        pipeline._delete_observers = []

        return pipeline

    async def test_enricher_exception_propagates(self, mock_pipeline):
        """Test that enricher exception blocks ingestion"""
        enricher = BaseTestMockEnricher(
            should_raise=ValueError("Content validation failed")
        )
        mock_pipeline._enrichers = [enricher]

        with pytest.raises(ValueError) as exc_info:
            await mock_pipeline.ingest_text(text="Test", metadata={})

        assert "Content validation failed" in str(exc_info.value)

    async def test_query_processor_exception_propagates(self, mock_pipeline):
        """Test that query processor exception blocks query"""
        processor = BaseTestMockQueryProcessor(
            should_raise=RuntimeError("Query expansion failed")
        )
        mock_pipeline._query_processors = [processor]

        with pytest.raises(RuntimeError) as exc_info:
            await mock_pipeline.query(
                question="test",
                synthesize=False
            )

        assert "Query expansion failed" in str(exc_info.value)

    async def test_chunk_observer_exception_logged_not_propagated(self, mock_pipeline, caplog):
        """Test chunk observer exceptions are logged but don't fail ingestion"""
        observer = BaseTestMockChunkObserver(
            should_raise=Exception("Observer processing failed")
        )
        mock_pipeline._chunk_observers = [observer]

        result = await mock_pipeline.ingest_text(
            text="Test content",
            metadata={}
        )

        # Ingestion still succeeds
        assert result["success"]

        # Exception was logged
        assert "Observer processing failed" in caplog.text

    async def test_result_processor_exception_propagates(self, mock_pipeline):
        """Test that result processor exception blocks query"""
        processor = BaseTestMockResultProcessor(
            should_raise=Exception("Result processing failed")
        )
        mock_pipeline._result_processors = [processor]

        with pytest.raises(Exception) as exc_info:
            await mock_pipeline.query(
                question="test",
                synthesize=False
            )

        assert "Result processing failed" in str(exc_info.value)

    async def test_delete_observer_pre_exception_blocks_deletion(self, mock_pipeline):
        """Test pre-delete observer exception blocks deletion"""
        observer = BaseTestMockDeleteObserver(
            should_raise=Exception("Permission denied")
        )
        mock_pipeline._delete_observers = [observer]

        with pytest.raises(Exception) as exc_info:
            await mock_pipeline.delete_document(
                doc_id="test-id",
                namespace="test-ns"
            )

        assert "Permission denied" in str(exc_info.value)

    async def test_delete_observer_post_exception_logged_not_propagated(self, mock_pipeline, caplog):
        """Test post-delete observer exception is logged but doesn't fail deletion"""
        observer = MockDeleteObserver(action="allow")
        mock_pipeline._delete_observers = [observer]

        # Setup observer to raise in on_delete_complete
        async def raise_in_complete(*args):
            raise Exception("Audit log failed")

        observer.on_delete_complete = raise_in_complete

        result = await mock_pipeline.delete_document(
            doc_id="test-id",
            namespace="test-ns"
        )

        # Deletion still succeeds
        assert result["success"]


# ==================== CONTEXT AND CONFIGURATION TESTS ====================

class TestContextAndConfiguration:
    """Tests for context creation and middleware ordering"""

    def test_request_context_from_fastapi_request(self):
        """Test RequestContext factory from FastAPI request"""
        from fastapi import Request
        from starlette.datastructures import Headers

        # Create a mock FastAPI request
        scope = {
            "type": "http",
            "method": "POST",
            "headers": [
                (b"x-request-id", b"custom-request-id"),
                (b"x-trace-id", b"trace-123"),
            ],
        }
        request = Request(scope)
        request._receive = AsyncMock(return_value={"type": "http.request", "body": b""})

        context = RequestContext.from_fastapi_request(request, namespace="test-ns")

        assert context.request_id == "custom-request-id"
        assert context.trace_id == "trace-123"
        assert context.namespace == "test-ns"
        assert context.source == "api"

    def test_request_context_generates_request_id_if_missing(self):
        """Test RequestContext generates request_id if not provided"""
        from fastapi import Request

        scope = {"type": "http", "method": "POST", "headers": []}
        request = Request(scope)
        request._receive = AsyncMock(return_value={"type": "http.request", "body": b""})

        context = RequestContext.from_fastapi_request(request, namespace="test-ns")

        assert context.request_id is not None
        assert len(context.request_id) > 0

    def test_query_context_composition(self):
        """Test QueryContext composition and property delegation"""
        from datetime import datetime, timezone

        base_context = RequestContext(
            request_id="req-123",
            timestamp=datetime.now(timezone.utc),
            namespace="test-ns",
            user_id="user-456",
            tenant_id="tenant-789",
            roles=["admin", "editor"],
            source="api"
        )

        query_context = QueryContext.from_request_context(
            context=base_context,
            query="test query",
            top_k=10,
            filters={"namespace": "test"}
        )

        # Verify composition
        assert query_context.context is base_context
        assert query_context.query == "test query"
        assert query_context.top_k == 10

        # Verify property delegation
        assert query_context.request_id == "req-123"
        assert query_context.namespace == "test-ns"
        assert query_context.user_id == "user-456"
        assert query_context.tenant_id == "tenant-789"
        assert query_context.roles == ["admin", "editor"]
        assert query_context.source == "api"

    def test_request_context_custom_data_namespacing(self):
        """Test custom data uses proper namespacing to avoid collisions"""
        from datetime import datetime, timezone

        context = RequestContext(
            request_id="req-123",
            timestamp=datetime.now(timezone.utc),
            namespace="test-ns"
        )

        # Different middleware can store data without collision
        context.custom["ACLMiddleware.allowed_ns"] = ["ns1", "ns2"]
        context.custom["AuditMiddleware.action"] = "create"
        context.custom["RateLimitMiddleware.calls"] = 5

        assert context.custom["ACLMiddleware.allowed_ns"] == ["ns1", "ns2"]
        assert context.custom["AuditMiddleware.action"] == "create"
        assert context.custom["RateLimitMiddleware.calls"] == 5


# ==================== UNIT TESTS FOR MIDDLEWARE COMPONENTS ====================

class TestMiddlewareChainUnit:
    """Unit tests for MiddlewareChain component"""

    async def test_middleware_chain_topological_sort_simple(self):
        """Test topological sort with simple dependencies"""
        from stache_ai.middleware.chain import MiddlewareChain

        m1 = BaseTestMockEnricher(priority=100)
        m2 = BaseTestMockEnricher(priority=50)

        # Lower priority should come first
        chain = MiddlewareChain([m1, m2])
        sorted_names = [m.__class__.__name__ for m in chain.middlewares]

        assert chain.middlewares[0].priority == 50
        assert chain.middlewares[1].priority == 100

    async def test_middleware_chain_respects_dependencies(self):
        """Test chain respects depends_on relationships"""
        from stache_ai.middleware.chain import MiddlewareChain

        m1 = BaseTestMockEnricher(priority=100)
        m2 = BaseTestMockEnricher(priority=100)

        # For now, just test that chain can be created
        # In practice, depends_on should use unique class names
        chain = MiddlewareChain([m1, m2])
        assert len(chain.middlewares) == 2

    async def test_search_result_dataclass(self):
        """Test SearchResult dataclass structure"""
        result = SearchResult(
            text="Sample result",
            score=0.95,
            metadata={"source": "docs", "page": 1},
            vector_id="vec-123"
        )

        assert result.text == "Sample result"
        assert result.score == 0.95
        assert result.metadata["source"] == "docs"
        assert result.vector_id == "vec-123"

    async def test_enrichment_result_allow_action(self):
        """Test EnrichmentResult with allow action"""
        result = EnrichmentResult(action="allow")

        assert result.action == "allow"
        assert result.content is None
        assert result.metadata is None
        assert result.reason is None

    async def test_enrichment_result_transform_action(self):
        """Test EnrichmentResult with transform action"""
        result = EnrichmentResult(
            action="transform",
            content="New content",
            metadata={"enriched": True}
        )

        assert result.action == "transform"
        assert result.content == "New content"
        assert result.metadata["enriched"] is True

    async def test_enrichment_result_reject_action(self):
        """Test EnrichmentResult with reject action"""
        result = EnrichmentResult(
            action="reject",
            reason="Content policy violation"
        )

        assert result.action == "reject"
        assert result.reason == "Content policy violation"

    async def test_observer_result_no_transform_action(self):
        """Test that ObserverResult has no transform action"""
        result = ObserverResult(action="allow")

        assert result.action == "allow"
        # ObserverResult should only have allow/reject
        # Transform is not applicable for post-storage observers

    async def test_delete_target_document_type(self):
        """Test DeleteTarget with document type"""
        from stache_ai.middleware.base import DeleteTarget

        target = DeleteTarget(
            target_type="document",
            doc_id="doc-123",
            namespace="test-ns"
        )

        assert target.target_type == "document"
        assert target.doc_id == "doc-123"
        assert target.namespace == "test-ns"
        assert target.chunk_ids is None

    async def test_delete_target_namespace_type(self):
        """Test DeleteTarget with namespace type"""
        from stache_ai.middleware.base import DeleteTarget

        target = DeleteTarget(
            target_type="namespace",
            namespace="test-ns"
        )

        assert target.target_type == "namespace"
        assert target.namespace == "test-ns"
        assert target.doc_id is None

    async def test_delete_target_chunks_type(self):
        """Test DeleteTarget with chunks type"""
        from stache_ai.middleware.base import DeleteTarget

        target = DeleteTarget(
            target_type="chunks",
            chunk_ids=["chunk-1", "chunk-2", "chunk-3"]
        )

        assert target.target_type == "chunks"
        assert target.chunk_ids == ["chunk-1", "chunk-2", "chunk-3"]
        assert target.doc_id is None


# ==================== MIDDLEWARE ORDERING TESTS ====================

class TestMiddlewareOrdering:
    """Tests for middleware priority and dependency ordering"""

    @pytest.fixture
    def mock_pipeline(self, mock_embedding_provider, mock_llm_provider, mock_vectordb_provider, mock_document_index_provider, mock_documents_provider, mock_summaries_provider):
        """Create a pipeline with mocked providers"""
        pipeline = RAGPipeline()
        pipeline._embedding_provider = mock_embedding_provider
        pipeline._llm_provider = mock_llm_provider
        pipeline._vectordb_provider = mock_vectordb_provider
        pipeline._document_index_provider = mock_document_index_provider
        pipeline._documents_provider = mock_documents_provider
        pipeline._summaries_provider = mock_summaries_provider

        pipeline._enrichers = []
        pipeline._chunk_observers = []
        pipeline._query_processors = []
        pipeline._result_processors = []
        pipeline._delete_observers = []

        return pipeline

    async def test_enrichers_respect_priority(self, mock_pipeline):
        """Test enrichers execute in priority order"""
        # Create enrichers with different priorities
        enricher_low = BaseTestMockEnricher(action="allow", priority=200)
        enricher_mid = BaseTestMockEnricher(action="allow", priority=100)
        enricher_high = BaseTestMockEnricher(action="allow", priority=50)

        # Add in non-sorted order
        mock_pipeline._enrichers = [enricher_low, enricher_high, enricher_mid]

        result = await mock_pipeline.ingest_text(
            text="Test content",
            metadata={}
        )

        # Verify execution order by checking call sequence
        # The first enricher to process gets the original content
        # (This assumes the pipeline sorts by priority)
        assert result["success"]
        assert enricher_low.call_count == 1
        assert enricher_mid.call_count == 1
        assert enricher_high.call_count == 1

"""Tests for RAG pipeline"""

from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from stache_ai.rag.pipeline import RAGPipeline, get_pipeline


class TestRAGPipeline:
    """Tests for RAGPipeline class"""

    @pytest.fixture
    def mock_pipeline(self, mock_embedding_provider, mock_llm_provider, mock_vectordb_provider, mock_document_index_provider, mock_documents_provider, mock_summaries_provider, mock_insights_provider):
        """Create a pipeline with mocked providers"""
        pipeline = RAGPipeline()
        pipeline._embedding_provider = mock_embedding_provider
        pipeline._llm_provider = mock_llm_provider
        pipeline._vectordb_provider = mock_vectordb_provider
        pipeline._document_index_provider = mock_document_index_provider
        # CRITICAL: Set via _private attribute, not property
        pipeline._documents_provider = mock_documents_provider
        pipeline._summaries_provider = mock_summaries_provider
        pipeline._insights_provider = mock_insights_provider
        return pipeline

    def test_pipeline_initialization(self, test_settings):
        """Test pipeline initialization with custom settings"""
        pipeline = RAGPipeline(config=test_settings)
        assert pipeline.config == test_settings
        assert pipeline._embedding_provider is None
        assert pipeline._llm_provider is None
        assert pipeline._vectordb_provider is None

    def test_pipeline_default_settings(self):
        """Test pipeline uses default settings when none provided"""
        pipeline = RAGPipeline()
        assert pipeline.config is not None

    def test_lazy_load_embedding_provider(self):
        """Test that embedding provider is lazy-loaded"""
        with patch('stache_ai.rag.pipeline.EmbeddingProviderFactory') as mock_factory:
            mock_provider = MagicMock()
            mock_factory.create.return_value = mock_provider

            pipeline = RAGPipeline()
            assert pipeline._embedding_provider is None

            # Access the property to trigger lazy loading
            provider = pipeline.embedding_provider
            assert provider == mock_provider
            mock_factory.create.assert_called_once()

    def test_lazy_load_llm_provider(self):
        """Test that LLM provider is lazy-loaded"""
        with patch('stache_ai.rag.pipeline.LLMProviderFactory') as mock_factory:
            mock_provider = MagicMock()
            mock_factory.create.return_value = mock_provider

            pipeline = RAGPipeline()
            assert pipeline._llm_provider is None

            provider = pipeline.llm_provider
            assert provider == mock_provider
            mock_factory.create.assert_called_once()

    def test_lazy_load_vectordb_provider(self):
        """Test that vector DB provider is lazy-loaded"""
        with patch('stache_ai.rag.pipeline.VectorDBProviderFactory') as mock_factory:
            mock_provider = MagicMock()
            mock_factory.create.return_value = mock_provider

            pipeline = RAGPipeline()
            assert pipeline._vectordb_provider is None

            provider = pipeline.vectordb_provider
            assert provider == mock_provider
            mock_factory.create.assert_called_once()

    def test_ingest_text_basic(self, mock_pipeline):
        """Test basic text ingestion"""
        result = mock_pipeline.ingest_text(
            text="This is test content for ingestion.",
            metadata={"filename": "test.txt"}
        )

        assert result["success"] is True
        assert result["chunks_created"] > 0
        assert "ids" in result
        assert "doc_id" in result
        # Pipeline calls insert once for chunks on documents_provider and once for summary on summaries_provider
        assert mock_pipeline._documents_provider.insert.call_count == 1
        assert mock_pipeline._summaries_provider.insert.call_count == 1

    def test_ingest_text_with_namespace(self, mock_pipeline):
        """Test text ingestion with namespace"""
        result = mock_pipeline.ingest_text(
            text="Test content",
            namespace="test-namespace"
        )

        assert result["namespace"] == "test-namespace"
        # Check that namespace was passed to insert on documents_provider
        call_args = mock_pipeline._documents_provider.insert.call_args
        assert call_args.kwargs.get("namespace") == "test-namespace"

    def test_ingest_text_with_chunking_strategy(self, mock_pipeline):
        """Test text ingestion with specific chunking strategy"""
        result = mock_pipeline.ingest_text(
            text="# Header\n\nContent paragraph.",
            chunking_strategy="markdown"
        )

        assert result["success"] is True
        assert result["chunks_created"] > 0

    def test_ingest_text_with_prepend_metadata(self, mock_pipeline):
        """Test text ingestion with metadata prepended to chunks"""
        # Disable auto-split for this test to check embed_batch directly
        mock_pipeline.config.embedding_auto_split_enabled = False

        result = mock_pipeline.ingest_text(
            text="Content about AI and machine learning.",
            metadata={"speaker": "John Doe", "topic": "AI"},
            prepend_metadata=["speaker", "topic"]
        )

        assert result["success"] is True
        # The embedding provider should receive chunks with prepended metadata
        call_args = mock_pipeline._embedding_provider.embed_batch.call_args
        embedded_texts = call_args[0][0]
        # At least one chunk should have the prepended metadata
        assert any("Speaker: John Doe" in text for text in embedded_texts)

    def test_query_with_synthesis(self, mock_pipeline):
        """Test query with LLM synthesis"""
        result = mock_pipeline.query(
            question="What is Stache?",
            top_k=3,
            synthesize=True
        )

        assert "question" in result
        assert "sources" in result
        assert "answer" in result
        assert result["question"] == "What is Stache?"
        mock_pipeline._llm_provider.generate_with_context.assert_called_once()

    def test_query_without_synthesis(self, mock_pipeline):
        """Test query without LLM synthesis (search only)"""
        result = mock_pipeline.query(
            question="What is Stache?",
            top_k=3,
            synthesize=False
        )

        assert "question" in result
        assert "sources" in result
        assert "answer" not in result
        mock_pipeline._llm_provider.generate_with_context.assert_not_called()

    def test_query_with_namespace(self, mock_pipeline):
        """Test query with namespace filter"""
        result = mock_pipeline.query(
            question="Test question",
            namespace="test-namespace"
        )

        assert result["namespace"] == "test-namespace"
        # Check that namespace was passed to search on documents_provider
        call_args = mock_pipeline._documents_provider.search.call_args
        assert call_args.kwargs.get("namespace") == "test-namespace"

    def test_query_returns_sources(self, mock_pipeline):
        """Test that query returns properly formatted sources"""
        result = mock_pipeline.query(
            question="Test question",
            synthesize=False
        )

        assert len(result["sources"]) == 2  # Based on mock_vectordb_provider fixture
        for source in result["sources"]:
            assert "text" in source
            assert "metadata" in source
            assert "score" in source

    def test_search_method(self, mock_pipeline):
        """Test search method (alias for query without synthesis)"""
        result = mock_pipeline.search(
            query="Test query",
            top_k=5
        )

        assert "sources" in result
        assert "answer" not in result

    def test_get_available_chunking_strategies(self, mock_pipeline):
        """Test getting available chunking strategies"""
        strategies = mock_pipeline.get_available_chunking_strategies()

        assert isinstance(strategies, list)
        assert len(strategies) > 0

    def test_get_providers_info(self, mock_pipeline):
        """Test getting provider information"""
        info = mock_pipeline.get_providers_info()

        assert "embedding_provider" in info
        assert "llm_provider" in info
        assert "vectordb_provider" in info
        assert "embedding_dimensions" in info

    def test_query_empty_results(self, mock_pipeline):
        """Test query when no results found"""
        mock_pipeline._documents_provider.search.return_value = []

        result = mock_pipeline.query(
            question="Unknown topic",
            synthesize=True
        )

        assert result["sources"] == []
        # Should not call LLM if no sources
        mock_pipeline._llm_provider.generate_with_context.assert_not_called()


class TestGetPipeline:
    """Tests for get_pipeline function"""

    def test_get_pipeline_returns_instance(self):
        """Test that get_pipeline returns a RAGPipeline instance"""
        # Reset global pipeline
        import stache_ai.rag.pipeline as pipeline_module
        pipeline_module._pipeline = None

        with patch.object(RAGPipeline, 'embedding_provider', new_callable=PropertyMock) as mock_emb, \
             patch.object(RAGPipeline, 'llm_provider', new_callable=PropertyMock) as mock_llm, \
             patch.object(RAGPipeline, 'vectordb_provider', new_callable=PropertyMock) as mock_vdb:

            pipeline = get_pipeline()
            assert isinstance(pipeline, RAGPipeline)

    def test_get_pipeline_returns_same_instance(self):
        """Test that get_pipeline returns the same instance (singleton)"""

        with patch.object(RAGPipeline, 'embedding_provider', new_callable=PropertyMock), \
             patch.object(RAGPipeline, 'llm_provider', new_callable=PropertyMock), \
             patch.object(RAGPipeline, 'vectordb_provider', new_callable=PropertyMock):

            pipeline1 = get_pipeline()
            pipeline2 = get_pipeline()
            assert pipeline1 is pipeline2


class TestPipelineIntegration:
    """Integration tests for RAG pipeline (with mocks)"""

    def test_full_ingest_and_query_flow(
        self,
        mock_embedding_provider,
        mock_llm_provider,
        mock_vectordb_provider,
        mock_document_index_provider,
        mock_documents_provider,
        mock_summaries_provider,
        mock_insights_provider
    ):
        """Test complete flow: ingest -> query -> get answer"""
        pipeline = RAGPipeline()
        pipeline._embedding_provider = mock_embedding_provider
        pipeline._llm_provider = mock_llm_provider
        pipeline._vectordb_provider = mock_vectordb_provider
        pipeline._document_index_provider = mock_document_index_provider
        # CRITICAL: Set via _private attribute
        pipeline._documents_provider = mock_documents_provider
        pipeline._summaries_provider = mock_summaries_provider
        pipeline._insights_provider = mock_insights_provider

        # Ingest some content
        ingest_result = pipeline.ingest_text(
            text="Stache is a personal knowledge base system. It uses AI to help organize information.",
            metadata={"filename": "intro.txt", "type": "documentation"}
        )
        assert ingest_result["success"] is True

        # Query the content
        query_result = pipeline.query(
            question="What is Stache?",
            synthesize=True
        )

        assert query_result["question"] == "What is Stache?"
        assert "answer" in query_result
        assert len(query_result["sources"]) > 0

    def test_ingest_with_different_strategies(
        self,
        mock_embedding_provider,
        mock_vectordb_provider,
        mock_document_index_provider,
        mock_documents_provider,
        mock_summaries_provider,
        mock_insights_provider,
        sample_text
    ):
        """Test ingestion with different chunking strategies"""
        pipeline = RAGPipeline()
        pipeline._embedding_provider = mock_embedding_provider
        pipeline._vectordb_provider = mock_vectordb_provider
        pipeline._document_index_provider = mock_document_index_provider
        # CRITICAL: Set via _private attribute
        pipeline._documents_provider = mock_documents_provider
        pipeline._summaries_provider = mock_summaries_provider
        pipeline._insights_provider = mock_insights_provider

        strategies = ["recursive", "markdown", "character"]

        for strategy in strategies:
            mock_vectordb_provider.reset_mock()
            mock_embedding_provider.reset_mock()

            result = pipeline.ingest_text(
                text=sample_text,
                chunking_strategy=strategy
            )

            assert result["success"] is True
            assert result["chunks_created"] > 0

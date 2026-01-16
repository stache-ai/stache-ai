"""Tests for BaseAIEnricher base class."""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch

pytestmark = pytest.mark.anyio


class TestBaseAIEnricher:
    """Tests for the BaseAIEnricher abstract base class."""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings for testing."""
        settings = MagicMock()
        settings.ai_enrichment_enabled = True
        settings.ai_enrichment_model = None
        settings.ai_enrichment_max_tokens = 1024
        settings.ai_enrichment_temperature = 0.0
        return settings

    @pytest.fixture
    def mock_llm_provider(self):
        """Create mock LLM provider with structured output support."""
        provider = MagicMock()
        provider.get_name.return_value = "MockLLMProvider"
        provider.capabilities = {"structured_output", "tool_use"}
        provider.generate_structured.return_value = {
            "summary": "Test summary",
            "doc_type": "article",
            "chunking_strategy": "recursive"
        }
        return provider

    @pytest.fixture
    def mock_context(self):
        """Create mock request context."""
        from stache_ai.middleware.context import RequestContext
        return RequestContext(
            request_id="test-request-1",
            timestamp=datetime.now(timezone.utc),
            namespace="test-ns",
            source="api"
        )

    @pytest.fixture
    def concrete_enricher(self, mock_settings, mock_llm_provider):
        """Create a concrete implementation of BaseAIEnricher for testing."""
        from stache_ai.middleware.enrichment.base_ai import BaseAIEnricher

        class TestEnricher(BaseAIEnricher):
            def get_schema(self):
                return {
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string"},
                        "doc_type": {"type": "string"}
                    },
                    "required": ["summary", "doc_type"]
                }

            def build_prompt(self, content, metadata):
                return f"Analyze: {content[:100]}"

            def apply_enrichment(self, metadata, llm_output):
                metadata["ai_summary"] = llm_output["summary"]
                metadata["doc_type"] = llm_output["doc_type"]
                return metadata

        enricher = TestEnricher(mock_settings)
        enricher._llm_provider = mock_llm_provider
        return enricher

    async def test_process_success(self, concrete_enricher, mock_context, mock_llm_provider):
        """Test successful enrichment processing."""
        result = await concrete_enricher.process(
            content="This is test content for enrichment.",
            metadata={"filename": "test.txt"},
            context=mock_context
        )

        assert result.action == "transform"
        assert result.metadata["ai_summary"] == "Test summary"
        assert result.metadata["doc_type"] == "article"
        mock_llm_provider.generate_structured.assert_called_once()

    async def test_process_preserves_original_content(self, concrete_enricher, mock_context):
        """Test that process returns original content unchanged."""
        original_content = "Original content here"
        result = await concrete_enricher.process(
            content=original_content,
            metadata={},
            context=mock_context
        )

        assert result.content == original_content

    async def test_truncate_content_short(self, concrete_enricher):
        """Test truncation with content under limit."""
        short_content = "Short content"
        result = concrete_enricher.truncate_content(short_content, max_chars=1000)
        assert result == short_content

    async def test_truncate_content_long(self, concrete_enricher):
        """Test truncation with content over limit."""
        long_content = "A" * 10000
        result = concrete_enricher.truncate_content(long_content, max_chars=100)

        assert len(result) < len(long_content)
        assert result.startswith("A" * 100)
        assert "[... content truncated for analysis ...]" in result

    async def test_llm_provider_lazy_loading(self, mock_settings):
        """Test that LLM provider is lazily loaded."""
        from stache_ai.middleware.enrichment.base_ai import BaseAIEnricher

        class TestEnricher(BaseAIEnricher):
            def get_schema(self):
                return {}

            def build_prompt(self, content, metadata):
                return ""

            def apply_enrichment(self, metadata, llm_output):
                return metadata

        enricher = TestEnricher(mock_settings)
        assert enricher._llm_provider is None

    async def test_llm_provider_capability_check(self, mock_settings):
        """Test that LLM provider without structured_output raises error."""
        from stache_ai.middleware.enrichment.base_ai import BaseAIEnricher

        class TestEnricher(BaseAIEnricher):
            def get_schema(self):
                return {}

            def build_prompt(self, content, metadata):
                return ""

            def apply_enrichment(self, metadata, llm_output):
                return metadata

        # Mock provider without structured_output capability
        mock_provider = MagicMock()
        mock_provider.capabilities = set()  # No structured_output
        mock_provider.get_name.return_value = "NoStructuredProvider"

        with patch("stache_ai.providers.LLMProviderFactory") as mock_factory:
            mock_factory.create.return_value = mock_provider

            enricher = TestEnricher(mock_settings)

            with pytest.raises(RuntimeError) as exc_info:
                _ = enricher.llm_provider

            assert "does not support structured output" in str(exc_info.value)

    async def test_process_handles_not_implemented_error(
        self, concrete_enricher, mock_context, mock_llm_provider
    ):
        """Test that NotImplementedError from LLM returns allow action."""
        mock_llm_provider.generate_structured.side_effect = NotImplementedError(
            "Structured output not supported"
        )

        result = await concrete_enricher.process(
            content="Test content",
            metadata={},
            context=mock_context
        )

        assert result.action == "allow"

    async def test_process_handles_generic_exception(
        self, concrete_enricher, mock_context, mock_llm_provider, caplog
    ):
        """Test that generic exceptions are logged but don't block ingestion."""
        mock_llm_provider.generate_structured.side_effect = RuntimeError(
            "LLM API error"
        )

        result = await concrete_enricher.process(
            content="Test content",
            metadata={},
            context=mock_context
        )

        assert result.action == "allow"
        assert "LLM API error" in caplog.text

    async def test_class_attributes(self):
        """Test class-level attributes are set correctly."""
        from stache_ai.middleware.enrichment.base_ai import BaseAIEnricher

        assert BaseAIEnricher.phase == "enrich"
        assert BaseAIEnricher.priority == 80
        assert BaseAIEnricher.on_error == "skip"
        assert BaseAIEnricher.timeout_seconds == 30.0

    async def test_metadata_copy_isolation(
        self, concrete_enricher, mock_context, mock_llm_provider
    ):
        """Test that original metadata is not mutated."""
        original_metadata = {"filename": "test.txt", "existing": "value"}
        original_copy = original_metadata.copy()

        await concrete_enricher.process(
            content="Test content",
            metadata=original_metadata,
            context=mock_context
        )

        # Original should be unchanged (process uses .copy())
        assert original_metadata == original_copy


class TestLLMProviderCapabilities:
    """Tests for LLMProvider capabilities property."""

    def test_base_llm_provider_default_capabilities(self):
        """Test that base LLMProvider has empty capabilities by default."""
        from stache_ai.providers.base import LLMProvider

        class MinimalProvider(LLMProvider):
            def generate(self, prompt, **kwargs):
                return ""

            def generate_with_context(self, query, context, **kwargs):
                return ""

        provider = MinimalProvider()
        assert provider.capabilities == set()

    def test_base_llm_provider_generate_structured_raises(self):
        """Test that base generate_structured raises NotImplementedError."""
        from stache_ai.providers.base import LLMProvider

        class MinimalProvider(LLMProvider):
            def generate(self, prompt, **kwargs):
                return ""

            def generate_with_context(self, query, context, **kwargs):
                return ""

        provider = MinimalProvider()

        with pytest.raises(NotImplementedError) as exc_info:
            provider.generate_structured(
                prompt="test",
                schema={"type": "object"}
            )

        assert "does not support structured output" in str(exc_info.value)

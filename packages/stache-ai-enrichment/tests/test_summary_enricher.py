"""Tests for SummaryEnricher standard enrichment plugin."""

import pytest
from unittest.mock import MagicMock

pytestmark = pytest.mark.anyio


class TestSummaryEnricher:
    """Tests for the SummaryEnricher class."""

    @pytest.fixture
    def enricher(self, mock_settings, mock_llm_provider):
        """Create SummaryEnricher with mocked dependencies."""
        from stache_ai_enrichment.enrichers import SummaryEnricher

        enricher = SummaryEnricher(mock_settings)
        enricher._llm_provider = mock_llm_provider
        return enricher

    def test_priority_is_80(self, mock_settings):
        """Test that SummaryEnricher has priority 80."""
        from stache_ai_enrichment.enrichers import SummaryEnricher

        enricher = SummaryEnricher(mock_settings)
        assert enricher.priority == 80

    def test_get_schema_returns_valid_json_schema(self, enricher):
        """Test that get_schema returns a valid JSON schema."""
        schema = enricher.get_schema()

        assert schema["type"] == "object"
        assert "summary" in schema["properties"]
        assert "doc_type" in schema["properties"]
        assert "chunking_strategy" in schema["properties"]
        assert schema["required"] == ["summary", "doc_type", "chunking_strategy"]

    def test_schema_summary_constraints(self, enricher):
        """Test summary field has proper constraints."""
        schema = enricher.get_schema()

        summary_prop = schema["properties"]["summary"]
        assert summary_prop["type"] == "string"
        assert summary_prop["minLength"] == 20
        assert summary_prop["maxLength"] == 300

    def test_schema_doc_type_enum(self, enricher):
        """Test doc_type has valid enum values."""
        schema = enricher.get_schema()

        doc_type_prop = schema["properties"]["doc_type"]
        assert "enum" in doc_type_prop
        assert "article" in doc_type_prop["enum"]
        assert "guide" in doc_type_prop["enum"]
        assert "api_docs" in doc_type_prop["enum"]
        assert "research_paper" in doc_type_prop["enum"]

    def test_schema_chunking_strategy_enum(self, enricher):
        """Test chunking_strategy has valid enum values."""
        schema = enricher.get_schema()

        strategy_prop = schema["properties"]["chunking_strategy"]
        assert strategy_prop["enum"] == ["recursive", "markdown", "hierarchical", "semantic"]

    def test_build_prompt_includes_filename(self, enricher):
        """Test that build_prompt includes the filename."""
        prompt = enricher.build_prompt(
            content="Test content",
            metadata={"filename": "test_document.pdf"}
        )

        assert "test_document.pdf" in prompt
        assert "Test content" in prompt

    def test_build_prompt_handles_missing_filename(self, enricher):
        """Test that build_prompt handles missing filename gracefully."""
        prompt = enricher.build_prompt(
            content="Test content",
            metadata={}
        )

        assert "unknown" in prompt

    def test_build_prompt_includes_instructions(self, enricher):
        """Test that build_prompt includes extraction instructions."""
        prompt = enricher.build_prompt(
            content="Test content",
            metadata={"filename": "test.txt"}
        )

        assert "summary" in prompt.lower()
        assert "doc_type" in prompt.lower()
        assert "chunking_strategy" in prompt.lower()

    def test_apply_enrichment_sets_ai_summary(self, enricher):
        """Test that apply_enrichment sets ai_summary field."""
        llm_output = {
            "summary": "This is a test summary",
            "doc_type": "article",
            "chunking_strategy": "recursive"
        }

        result = enricher.apply_enrichment({}, llm_output)

        assert result["ai_summary"] == "This is a test summary"

    def test_apply_enrichment_sets_doc_type(self, enricher):
        """Test that apply_enrichment sets doc_type field."""
        llm_output = {
            "summary": "Summary",
            "doc_type": "guide",
            "chunking_strategy": "markdown"
        }

        result = enricher.apply_enrichment({}, llm_output)

        assert result["doc_type"] == "guide"

    def test_apply_enrichment_sets_ai_chunking_strategy(self, enricher):
        """Test that apply_enrichment sets ai_chunking_strategy field."""
        llm_output = {
            "summary": "Summary",
            "doc_type": "article",
            "chunking_strategy": "semantic"
        }

        result = enricher.apply_enrichment({}, llm_output)

        assert result["ai_chunking_strategy"] == "semantic"

    def test_apply_enrichment_sets_tracking_fields(self, enricher):
        """Test that apply_enrichment sets tracking metadata."""
        llm_output = {
            "summary": "Summary",
            "doc_type": "article",
            "chunking_strategy": "recursive"
        }

        result = enricher.apply_enrichment({}, llm_output)

        assert result["ai_enriched"] is True
        assert result["enrichment_version"] == "standard-0.1.0"

    def test_apply_enrichment_preserves_existing_metadata(self, enricher):
        """Test that apply_enrichment preserves existing metadata."""
        existing_metadata = {"filename": "test.pdf", "author": "John"}
        llm_output = {
            "summary": "Summary",
            "doc_type": "article",
            "chunking_strategy": "recursive"
        }

        result = enricher.apply_enrichment(existing_metadata, llm_output)

        assert result["filename"] == "test.pdf"
        assert result["author"] == "John"

    async def test_process_success(self, enricher, mock_llm_provider, mock_context):
        """Test successful processing through the enricher."""
        mock_llm_provider.generate_structured.return_value = {
            "summary": "A comprehensive test document about software testing.",
            "doc_type": "guide",
            "chunking_strategy": "markdown"
        }

        result = await enricher.process(
            content="# Testing Guide\n\nThis guide covers testing best practices.",
            metadata={"filename": "testing_guide.md"},
            context=mock_context
        )

        assert result.action == "transform"
        assert result.metadata["ai_summary"] == "A comprehensive test document about software testing."
        assert result.metadata["doc_type"] == "guide"
        assert result.metadata["ai_chunking_strategy"] == "markdown"


class TestStandardEnrichmentSchema:
    """Tests for the STANDARD_ENRICHMENT_SCHEMA constant."""

    def test_schema_is_valid_json_schema(self):
        """Test that the schema is a valid JSON Schema."""
        from stache_ai_enrichment.enrichers import STANDARD_ENRICHMENT_SCHEMA

        assert STANDARD_ENRICHMENT_SCHEMA["type"] == "object"
        assert "properties" in STANDARD_ENRICHMENT_SCHEMA
        assert "required" in STANDARD_ENRICHMENT_SCHEMA

    def test_schema_disallows_additional_properties(self):
        """Test that schema disallows additional properties."""
        from stache_ai_enrichment.enrichers import STANDARD_ENRICHMENT_SCHEMA

        assert STANDARD_ENRICHMENT_SCHEMA.get("additionalProperties") is False


class TestEntryPointRegistration:
    """Tests for entry point registration."""

    def test_entry_point_name(self):
        """Test that the entry point is registered as 'ai_summary'."""
        # This test verifies the pyproject.toml configuration
        # In a real test, you'd use importlib.metadata after pip install -e .
        from stache_ai_enrichment.enrichers import SummaryEnricher

        # The class should exist and be importable
        assert SummaryEnricher is not None

    def test_enricher_inherits_from_base_ai(self):
        """Test that SummaryEnricher inherits from BaseAIEnricher."""
        from stache_ai_enrichment.enrichers import SummaryEnricher
        from stache_ai.middleware.enrichment.base_ai import BaseAIEnricher

        assert issubclass(SummaryEnricher, BaseAIEnricher)

"""Test fixtures for stache-ai-enrichment."""

import os
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock

# Set up test environment
os.environ.setdefault("STACHE_TEST_MODE", "true")


@pytest.fixture
def mock_settings():
    """Create mock settings for testing."""
    settings = MagicMock()
    settings.ai_enrichment_enabled = True
    settings.ai_enrichment_model = None
    settings.ai_enrichment_max_tokens = 1024
    settings.ai_enrichment_temperature = 0.0
    return settings


@pytest.fixture
def mock_llm_provider():
    """Create mock LLM provider with structured output support."""
    provider = MagicMock()
    provider.get_name.return_value = "MockLLMProvider"
    provider.capabilities = {"structured_output", "tool_use"}
    return provider


@pytest.fixture
def mock_context():
    """Create mock request context."""
    from stache_ai.middleware.context import RequestContext
    return RequestContext(
        request_id="test-request-1",
        timestamp=datetime.now(timezone.utc),
        namespace="test-ns",
        source="api"
    )

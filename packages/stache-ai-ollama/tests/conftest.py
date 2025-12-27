"""Test fixtures for stache-ai-ollama"""

import pytest
import os

# Set up test environment
os.environ.setdefault("STACHE_TEST_MODE", "true")


@pytest.fixture
def test_settings():
    """Create test settings."""
    from stache_ai.config import Settings
    return Settings()

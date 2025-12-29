"""LLM provider contract tests."""

from abc import ABC, abstractmethod
from typing import Any

import pytest


class LLMContractTest(ABC):
    """Base class for LLM provider contract tests."""

    @pytest.fixture
    @abstractmethod
    def provider(self):
        """Create the provider instance under test."""
        pass

    @pytest.fixture
    def sample_prompt(self) -> str:
        return "What is 2 + 2? Answer with just the number."

    @pytest.fixture
    def sample_context(self) -> list[dict[str, Any]]:
        return [
            {"text": "The capital of France is Paris.", "metadata": {"source": "geography.txt"}},
            {"text": "Paris has a population of about 2 million.", "metadata": {"source": "stats.txt"}},
        ]

    def test_generate_returns_string(self, provider, sample_prompt):
        """generate() must return a string."""
        response = provider.generate(sample_prompt)

        assert isinstance(response, str)
        assert len(response) > 0

    def test_generate_with_context_returns_string(self, provider, sample_context):
        """generate_with_context() must return a string."""
        response = provider.generate_with_context(
            query="What is the capital of France?",
            context=sample_context
        )

        assert isinstance(response, str)
        assert len(response) > 0

    def test_get_name_returns_string(self, provider):
        """get_name() must return provider name."""
        name = provider.get_name()

        assert isinstance(name, str)
        assert len(name) > 0

    def test_get_available_models_returns_list(self, provider):
        """get_available_models() must return list (may be empty)."""
        models = provider.get_available_models()

        assert isinstance(models, list)

    def test_get_default_model_returns_string(self, provider):
        """get_default_model() must return string (may be empty)."""
        model = provider.get_default_model()

        assert isinstance(model, str)

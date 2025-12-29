"""Reranker provider contract tests."""

from abc import ABC, abstractmethod
from typing import Any

import pytest


class RerankerContractTest(ABC):
    """Base class for Reranker provider contract tests."""

    @pytest.fixture
    @abstractmethod
    def provider(self):
        """Create the provider instance under test."""
        pass

    @pytest.fixture
    def sample_results(self) -> list[dict[str, Any]]:
        return [
            {"text": "Paris is the capital of France.", "score": 0.8},
            {"text": "The Eiffel Tower is in Paris.", "score": 0.7},
            {"text": "Berlin is the capital of Germany.", "score": 0.6},
        ]

    def test_rerank_returns_list(self, provider, sample_results):
        """rerank() must return list of results."""
        reranked = provider.rerank(
            query="What is the capital of France?",
            results=sample_results,
            top_k=3
        )

        assert isinstance(reranked, list)

    def test_rerank_respects_top_k(self, provider, sample_results):
        """rerank() must not return more than top_k results."""
        reranked = provider.rerank(
            query="capital",
            results=sample_results,
            top_k=1
        )

        assert len(reranked) <= 1

    def test_rerank_preserves_structure(self, provider, sample_results):
        """rerank() results must have text and score."""
        reranked = provider.rerank(
            query="France",
            results=sample_results,
            top_k=3
        )

        for result in reranked:
            assert "text" in result or "content" in result
            assert "score" in result

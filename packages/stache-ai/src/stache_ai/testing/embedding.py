"""Embedding provider contract tests."""

from abc import ABC, abstractmethod

import pytest


class EmbeddingContractTest(ABC):
    """Base class for Embedding provider contract tests."""

    @pytest.fixture
    @abstractmethod
    def provider(self):
        """Create the provider instance under test."""
        pass

    @pytest.fixture
    def sample_text(self) -> str:
        return "The quick brown fox jumps over the lazy dog."

    @pytest.fixture
    def sample_texts(self) -> list[str]:
        return [
            "First document about machine learning.",
            "Second document about natural language processing.",
            "Third document about vector databases.",
        ]

    def test_embed_returns_vector(self, provider, sample_text):
        """embed() must return a list of floats."""
        embedding = provider.embed(sample_text)

        assert isinstance(embedding, list)
        assert len(embedding) > 0
        assert all(isinstance(x, (int, float)) for x in embedding)

    def test_embed_batch_returns_vectors(self, provider, sample_texts):
        """embed_batch() must return list of vectors matching input count."""
        embeddings = provider.embed_batch(sample_texts)

        assert isinstance(embeddings, list)
        assert len(embeddings) == len(sample_texts)
        for emb in embeddings:
            assert isinstance(emb, list)
            assert all(isinstance(x, (int, float)) for x in emb)

    def test_get_dimensions_returns_positive_int(self, provider):
        """get_dimensions() must return a positive integer."""
        dims = provider.get_dimensions()

        assert isinstance(dims, int)
        assert dims > 0

    def test_embed_dimensions_match(self, provider, sample_text):
        """embed() output dimensions must match get_dimensions()."""
        embedding = provider.embed(sample_text)
        expected_dims = provider.get_dimensions()

        assert len(embedding) == expected_dims

    def test_embed_query_returns_vector(self, provider, sample_text):
        """embed_query() must return a vector (may differ from embed())."""
        embedding = provider.embed_query(sample_text)

        assert isinstance(embedding, list)
        assert len(embedding) == provider.get_dimensions()

    def test_empty_text_handling(self, provider):
        """Provider should handle empty text gracefully."""
        try:
            embedding = provider.embed("")
            # Either returns zero vector or raises ValueError
            assert isinstance(embedding, list)
        except ValueError:
            pass  # Acceptable to raise ValueError for empty input

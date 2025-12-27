"""Tests for embedding resilience utilities.

Tests for AutoSplitEmbeddingWrapper and related components.
"""

import pytest
from unittest.mock import Mock, MagicMock


class TestAutoSplitEmbeddingWrapper:
    """Test AutoSplitEmbeddingWrapper"""

    @pytest.fixture
    def mock_provider(self):
        """Mock embedding provider"""
        provider = Mock()
        provider.embed.return_value = [0.1, 0.2, 0.3]
        provider.get_name.return_value = "MockProvider"
        provider.get_dimensions.return_value = 1024
        provider.is_available.return_value = True
        return provider

    def test_no_split_when_embed_succeeds(self, mock_provider):
        """Should not split if embedding succeeds"""
        from stache_ai.rag.embedding_resilience import AutoSplitEmbeddingWrapper

        wrapper = AutoSplitEmbeddingWrapper(provider=mock_provider)

        results, split_count = wrapper.embed_batch_with_splits(["short text"])

        assert len(results) == 1
        assert split_count == 0
        assert results[0].was_split is False
        assert results[0].text == "short text"

    def test_auto_split_on_context_error(self, mock_provider):
        """Should auto-split when context length error occurs"""
        from stache_ai.rag.embedding_resilience import AutoSplitEmbeddingWrapper

        # First call fails with context error, subsequent calls succeed
        mock_provider.embed.side_effect = [
            Exception("context length exceeded"),  # Original text fails
            [0.1, 0.2, 0.3],  # Left half succeeds
            [0.4, 0.5, 0.6],  # Right half succeeds
        ]

        wrapper = AutoSplitEmbeddingWrapper(provider=mock_provider)
        results, split_count = wrapper.embed_batch_with_splits(["long text " * 100])

        # Should have split into 2
        assert len(results) == 2
        assert split_count == 1
        assert all(r.was_split for r in results)
        assert results[0].split_index == 0
        assert results[1].split_index == 1
        assert results[0].split_total == 2

    def test_recursive_split(self, mock_provider):
        """Should split recursively if needed"""
        from stache_ai.rag.embedding_resilience import AutoSplitEmbeddingWrapper

        # First call fails, subsequent splits eventually succeed
        mock_provider.embed.side_effect = [
            Exception("context length exceeded"),  # Original fails
            Exception("context length exceeded"),  # Left half fails
            [0.1],  # Left-left succeeds
            [0.2],  # Left-right succeeds
            [0.3],  # Right half succeeds
        ]

        wrapper = AutoSplitEmbeddingWrapper(provider=mock_provider, max_split_depth=2)
        results, split_count = wrapper.embed_batch_with_splits(["very long text"])

        # Should have split into 3 or more results
        assert len(results) >= 3
        assert split_count == 1
        assert any(r.was_split for r in results)

    def test_max_depth_raises_error(self, mock_provider):
        """Should raise error if max depth exceeded"""
        from stache_ai.rag.embedding_resilience import AutoSplitEmbeddingWrapper

        # Always fail
        mock_provider.embed.side_effect = Exception("context length exceeded")

        wrapper = AutoSplitEmbeddingWrapper(provider=mock_provider, max_split_depth=2)

        with pytest.raises(Exception, match="context length exceeded"):
            wrapper.embed_batch_with_splits(["pathological text"])

    def test_non_context_error_raises(self, mock_provider):
        """Should re-raise non-context errors immediately"""
        from stache_ai.rag.embedding_resilience import AutoSplitEmbeddingWrapper

        mock_provider.embed.side_effect = Exception("network timeout")

        wrapper = AutoSplitEmbeddingWrapper(provider=mock_provider)

        with pytest.raises(Exception, match="network timeout"):
            wrapper.embed_batch_with_splits(["text"])

    def test_disabled_wrapper_bypasses_split(self, mock_provider):
        """Should bypass splitting when disabled"""
        from stache_ai.rag.embedding_resilience import AutoSplitEmbeddingWrapper

        mock_provider.embed.side_effect = Exception("context length exceeded")

        wrapper = AutoSplitEmbeddingWrapper(provider=mock_provider, enabled=False)

        # Should raise error without attempting split
        with pytest.raises(Exception, match="context length exceeded"):
            wrapper.embed_batch_with_splits(["text"])

    def test_mixed_batch_some_split(self, mock_provider):
        """Should handle batch with mix of normal and oversized chunks"""
        from stache_ai.rag.embedding_resilience import AutoSplitEmbeddingWrapper

        # First succeeds, second fails then succeeds on split, third succeeds
        mock_provider.embed.side_effect = [
            [0.1],  # First chunk succeeds
            Exception("context length exceeded"),  # Second fails
            [0.2],  # Second-left succeeds
            [0.3],  # Second-right succeeds
            [0.4],  # Third succeeds
        ]

        wrapper = AutoSplitEmbeddingWrapper(provider=mock_provider)
        results, split_count = wrapper.embed_batch_with_splits([
            "short",
            "long " * 100,
            "also short"
        ])

        # 3 inputs → 4 results (middle one split)
        assert len(results) == 4
        assert split_count == 1
        assert results[0].was_split is False
        assert results[1].was_split is True
        assert results[2].was_split is True
        assert results[3].was_split is False

    def test_delegates_to_base_provider(self, mock_provider):
        """Should delegate metadata methods to base provider"""
        from stache_ai.rag.embedding_resilience import AutoSplitEmbeddingWrapper

        wrapper = AutoSplitEmbeddingWrapper(provider=mock_provider)

        assert "AutoSplit" in wrapper.get_name()
        assert "MockProvider" in wrapper.get_name()
        assert wrapper.get_dimensions() == 1024
        assert wrapper.is_available() is True

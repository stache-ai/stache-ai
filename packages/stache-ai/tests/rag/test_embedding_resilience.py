"""Tests for embedding resilience utilities.

Tests for AutoSplitEmbeddingWrapper and related components.
"""

from unittest.mock import Mock

import pytest


class TestAutoSplitEmbeddingWrapper:
    """Test AutoSplitEmbeddingWrapper"""

    @pytest.fixture
    def mock_provider(self):
        """Mock embedding provider"""
        provider = Mock()
        provider.embed.return_value = [0.1, 0.2, 0.3]
        provider.embed_batch.return_value = [[0.1, 0.2, 0.3]]
        provider.get_name.return_value = "MockProvider"
        provider.get_dimensions.return_value = 1024
        provider.is_available.return_value = True
        return provider

    def test_no_split_when_embed_succeeds(self, mock_provider):
        """Should use embed_batch on happy path"""
        from stache_ai.rag.embedding_resilience import AutoSplitEmbeddingWrapper

        mock_provider.embed_batch.return_value = [[0.1, 0.2, 0.3]]

        wrapper = AutoSplitEmbeddingWrapper(provider=mock_provider)
        results, split_count = wrapper.embed_batch_with_splits(["short text"])

        assert len(results) == 1
        assert split_count == 0
        assert results[0].was_split is False
        assert results[0].text == "short text"
        # Should use embed_batch, not embed
        mock_provider.embed_batch.assert_called_once()
        mock_provider.embed.assert_not_called()

    def test_auto_split_on_context_error(self, mock_provider):
        """Should fall back to individual embed with auto-split on batch failure"""
        from stache_ai.rag.embedding_resilience import AutoSplitEmbeddingWrapper

        # Batch call fails, then individual calls: first fails, halves succeed
        mock_provider.embed_batch.side_effect = Exception("context length exceeded")
        mock_provider.embed.side_effect = [
            Exception("context length exceeded"),  # Original text fails
            [0.1, 0.2, 0.3],  # Left half succeeds
            [0.4, 0.5, 0.6],  # Right half succeeds
        ]

        wrapper = AutoSplitEmbeddingWrapper(provider=mock_provider)
        results, split_count = wrapper.embed_batch_with_splits(["long text " * 100])

        assert len(results) == 2
        assert split_count == 1
        assert all(r.was_split for r in results)
        assert results[0].split_index == 0
        assert results[1].split_index == 1
        assert results[0].split_total == 2

    def test_recursive_split(self, mock_provider):
        """Should split recursively if needed"""
        from stache_ai.rag.embedding_resilience import AutoSplitEmbeddingWrapper

        # Batch fails, then individual: original fails, left half fails, pieces succeed
        mock_provider.embed_batch.side_effect = Exception("context length exceeded")
        mock_provider.embed.side_effect = [
            Exception("context length exceeded"),  # Original fails
            Exception("context length exceeded"),  # Left half fails
            [0.1],  # Left-left succeeds
            [0.2],  # Left-right succeeds
            [0.3],  # Right half succeeds
        ]

        wrapper = AutoSplitEmbeddingWrapper(provider=mock_provider, max_split_depth=2)
        results, split_count = wrapper.embed_batch_with_splits(["very long text"])

        assert len(results) >= 3
        assert split_count == 1
        assert any(r.was_split for r in results)

    def test_max_depth_raises_error(self, mock_provider):
        """Should raise error if max depth exceeded"""
        from stache_ai.rag.embedding_resilience import AutoSplitEmbeddingWrapper

        mock_provider.embed_batch.side_effect = Exception("context length exceeded")
        mock_provider.embed.side_effect = Exception("context length exceeded")

        wrapper = AutoSplitEmbeddingWrapper(provider=mock_provider, max_split_depth=2)

        with pytest.raises(Exception, match="context length exceeded"):
            wrapper.embed_batch_with_splits(["pathological text"])

    def test_non_context_error_raises(self, mock_provider):
        """Should re-raise non-context errors immediately"""
        from stache_ai.rag.embedding_resilience import AutoSplitEmbeddingWrapper

        mock_provider.embed_batch.side_effect = Exception("network timeout")

        wrapper = AutoSplitEmbeddingWrapper(provider=mock_provider)

        with pytest.raises(Exception, match="network timeout"):
            wrapper.embed_batch_with_splits(["text"])

    def test_disabled_wrapper_bypasses_split(self, mock_provider):
        """Should bypass splitting when disabled"""
        from stache_ai.rag.embedding_resilience import AutoSplitEmbeddingWrapper

        mock_provider.embed_batch.side_effect = Exception("context length exceeded")

        wrapper = AutoSplitEmbeddingWrapper(provider=mock_provider, enabled=False)

        with pytest.raises(Exception, match="context length exceeded"):
            wrapper.embed_batch_with_splits(["text"])

    def test_mixed_batch_some_split(self, mock_provider):
        """Should handle batch where embed_batch fails and fallback splits some"""
        from stache_ai.rag.embedding_resilience import AutoSplitEmbeddingWrapper

        # Batch fails due to one oversized text, fallback to individual:
        mock_provider.embed_batch.side_effect = Exception("context length exceeded")
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

    def test_multiple_batches_parallel(self, mock_provider):
        """Should process multiple batches in parallel"""
        from stache_ai.rag.embedding_resilience import AutoSplitEmbeddingWrapper

        texts = [f"text {i}" for i in range(10)]
        embeddings = [[float(i)] * 3 for i in range(10)]

        # embed_batch called per batch, return correct count each time
        mock_provider.embed_batch.side_effect = [
            embeddings[:3],   # batch 0
            embeddings[3:6],  # batch 1
            embeddings[6:9],  # batch 2
            embeddings[9:],   # batch 3
        ]

        wrapper = AutoSplitEmbeddingWrapper(
            provider=mock_provider, batch_size=3, max_workers=4
        )
        results, split_count = wrapper.embed_batch_with_splits(texts)

        assert len(results) == 10
        assert split_count == 0
        # Verify order preserved
        for i, r in enumerate(results):
            assert r.text == f"text {i}"
            assert r.parent_index == i

    def test_one_batch_fails_others_succeed(self, mock_provider):
        """Only the failing batch should fall back to individual"""
        from stache_ai.rag.embedding_resilience import AutoSplitEmbeddingWrapper

        texts = ["ok1", "ok2", "ok3", "oversized " * 100, "ok4", "ok5"]

        # Batch 0 (ok1, ok2, ok3) succeeds, batch 1 (oversized, ok4, ok5) fails
        mock_provider.embed_batch.side_effect = [
            [[0.1], [0.2], [0.3]],  # batch 0 succeeds
            Exception("context length exceeded"),  # batch 1 fails
        ]
        # Fallback individual calls for batch 1:
        mock_provider.embed.side_effect = [
            Exception("context length exceeded"),  # oversized fails
            [0.41],  # oversized-left succeeds
            [0.42],  # oversized-right succeeds
            [0.5],   # ok4 succeeds
            [0.6],   # ok5 succeeds
        ]

        wrapper = AutoSplitEmbeddingWrapper(
            provider=mock_provider, batch_size=3
        )
        results, split_count = wrapper.embed_batch_with_splits(texts)

        # 6 inputs → 7 results (oversized split into 2)
        assert len(results) == 7
        assert split_count == 1
        # First 3 from batch (no split)
        assert results[0].text == "ok1"
        assert results[0].was_split is False
        # oversized was split
        assert results[3].was_split is True
        assert results[4].was_split is True
        # ok4, ok5 not split
        assert results[5].was_split is False
        assert results[6].was_split is False

    def test_empty_input(self, mock_provider):
        """Should handle empty input"""
        from stache_ai.rag.embedding_resilience import AutoSplitEmbeddingWrapper

        wrapper = AutoSplitEmbeddingWrapper(provider=mock_provider)
        results, split_count = wrapper.embed_batch_with_splits([])

        assert len(results) == 0
        assert split_count == 0
        mock_provider.embed_batch.assert_not_called()

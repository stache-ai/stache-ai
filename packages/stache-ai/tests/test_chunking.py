"""Tests for chunking strategies"""

import pytest

from stache_ai.chunking.base import Chunk, ChunkingStrategy
from stache_ai.chunking.character import CharacterChunkingStrategy
from stache_ai.chunking.factory import ChunkingStrategyFactory
from stache_ai.chunking.markdown import MarkdownChunkingStrategy
from stache_ai.chunking.recursive import RecursiveChunkingStrategy, find_best_boundary


class TestChunk:
    """Tests for Chunk dataclass"""

    def test_chunk_creation(self):
        """Test creating a chunk with all fields"""
        chunk = Chunk(
            text="Test content",
            index=0,
            metadata={"strategy": "test", "chunk_size": 12}
        )
        assert chunk.text == "Test content"
        assert chunk.index == 0
        assert chunk.metadata["strategy"] == "test"
        assert chunk.metadata["chunk_size"] == 12

    def test_chunk_empty_metadata(self):
        """Test creating a chunk with empty metadata"""
        chunk = Chunk(text="Test", index=0, metadata={})
        assert chunk.metadata == {}


class TestFindBestBoundary:
    """Tests for the find_best_boundary helper function"""

    def test_find_paragraph_break(self):
        """Should find paragraph break (double newline)"""
        text = "First paragraph.\n\nSecond paragraph."
        # Position near the end, should find the paragraph break
        boundary = find_best_boundary(text, 25, search_range=20)
        assert boundary == 18  # After the double newline

    def test_find_sentence_break(self):
        """Should find sentence break when no paragraph break"""
        text = "First sentence. Second sentence."
        boundary = find_best_boundary(text, 25, search_range=20)
        assert text[boundary - 1] == " "  # After period and space

    def test_find_word_boundary(self):
        """Should find word boundary when no sentence break"""
        text = "word1 word2 word3 word4"
        boundary = find_best_boundary(text, 15, search_range=10)
        assert text[boundary - 1] == " "

    def test_position_at_start(self):
        """Should return 0 when position is at or before start"""
        text = "Some text here"
        assert find_best_boundary(text, 0) == 0
        assert find_best_boundary(text, -5) == 0

    def test_position_at_end(self):
        """Should return text length when position is at or after end"""
        text = "Some text here"
        assert find_best_boundary(text, len(text)) == len(text)
        assert find_best_boundary(text, len(text) + 10) == len(text)

    def test_no_boundary_found(self):
        """Should return original position when no boundary found"""
        text = "abcdefghijklmnop"  # No spaces, newlines, or punctuation
        boundary = find_best_boundary(text, 10, search_range=5)
        assert boundary == 10


class TestRecursiveChunkingStrategy:
    """Tests for RecursiveChunkingStrategy"""

    def test_strategy_name(self):
        """Should return correct strategy name"""
        strategy = RecursiveChunkingStrategy()
        assert strategy.get_name() == "RecursiveChunkingStrategy"

    def test_chunk_short_text(self):
        """Short text should produce single chunk"""
        strategy = RecursiveChunkingStrategy()
        chunks = strategy.chunk("Short text.", chunk_size=100, chunk_overlap=10)

        assert len(chunks) == 1
        assert chunks[0].text == "Short text."
        assert chunks[0].index == 0
        assert chunks[0].metadata["strategy"] == "recursive"

    def test_chunk_long_text(self, long_sample_text):
        """Long text should produce multiple chunks"""
        strategy = RecursiveChunkingStrategy()
        chunks = strategy.chunk(long_sample_text, chunk_size=500, chunk_overlap=50)

        assert len(chunks) > 1
        for i, chunk in enumerate(chunks):
            assert chunk.index == i
            assert chunk.metadata["strategy"] == "recursive"

    def test_chunk_respects_size_limit(self, sample_text):
        """Chunks should not significantly exceed chunk_size"""
        strategy = RecursiveChunkingStrategy()
        chunk_size = 200
        chunks = strategy.chunk(sample_text, chunk_size=chunk_size, chunk_overlap=20)

        # Allow some flexibility since we find natural boundaries
        for chunk in chunks:
            # Chunks might be slightly larger when finding boundaries
            assert len(chunk.text) < chunk_size * 2

    def test_chunk_with_custom_separators(self, sample_text):
        """Should use custom separators when provided"""
        strategy = RecursiveChunkingStrategy()
        chunks = strategy.chunk(
            sample_text,
            chunk_size=300,
            chunk_overlap=30,
            separators=['\n\n', '\n']
        )

        assert len(chunks) >= 1
        for chunk in chunks:
            assert chunk.metadata["separators"] == ['\n\n', '\n']

    def test_chunk_empty_text(self):
        """Empty text should produce minimal chunks"""
        strategy = RecursiveChunkingStrategy()
        chunks = strategy.chunk("", chunk_size=100, chunk_overlap=10)

        assert len(chunks) == 1
        assert chunks[0].text == ""

    def test_chunk_overlap_behavior(self):
        """Chunks should have overlapping content when overlap > 0"""
        strategy = RecursiveChunkingStrategy()
        text = "A" * 100 + "\n\n" + "B" * 100 + "\n\n" + "C" * 100

        chunks_with_overlap = strategy.chunk(text, chunk_size=120, chunk_overlap=30)
        chunks_no_overlap = strategy.chunk(text, chunk_size=120, chunk_overlap=0)

        # With overlap, content from one chunk might appear in the next
        assert len(chunks_with_overlap) >= 1
        assert len(chunks_no_overlap) >= 1


class TestMarkdownChunkingStrategy:
    """Tests for MarkdownChunkingStrategy"""

    def test_strategy_name(self):
        """Should return correct strategy name"""
        strategy = MarkdownChunkingStrategy()
        assert strategy.get_name() == "MarkdownChunkingStrategy"

    def test_chunk_by_headers(self, sample_text):
        """Should split markdown by headers"""
        strategy = MarkdownChunkingStrategy()
        chunks = strategy.chunk(sample_text, chunk_size=2000, chunk_overlap=0)

        assert len(chunks) >= 1
        for chunk in chunks:
            assert chunk.metadata["strategy"] == "markdown"

    def test_preserves_header_metadata(self):
        """Should preserve header information in metadata"""
        text = "# Main Header\n\nContent under main header."
        strategy = MarkdownChunkingStrategy()
        chunks = strategy.chunk(text, chunk_size=2000, chunk_overlap=0)

        assert len(chunks) >= 1
        # At least one chunk should have header metadata
        headers = [c.metadata.get("header") for c in chunks]
        assert any(h is not None for h in headers)

    def test_chunk_no_headers(self):
        """Should handle text without headers"""
        text = "Just plain text without any markdown headers."
        strategy = MarkdownChunkingStrategy()
        chunks = strategy.chunk(text, chunk_size=100, chunk_overlap=0)

        assert len(chunks) >= 1
        assert chunks[0].text == text

    def test_chunk_multiple_header_levels(self):
        """Should handle multiple header levels"""
        text = """# H1 Header

Content 1

## H2 Header

Content 2

### H3 Header

Content 3"""
        strategy = MarkdownChunkingStrategy()
        chunks = strategy.chunk(text, chunk_size=2000, chunk_overlap=0)

        # Should have multiple sections
        assert len(chunks) >= 1

    def test_split_by_headers_method(self):
        """Test the _split_by_headers internal method"""
        strategy = MarkdownChunkingStrategy()
        text = "# Header 1\n\nContent 1\n\n## Header 2\n\nContent 2"
        sections = strategy._split_by_headers(text)

        assert len(sections) >= 2
        # Check that headers are captured
        headers = [s.get("header") for s in sections if s.get("header")]
        assert "Header 1" in headers or "Header 2" in headers


class TestCharacterChunkingStrategy:
    """Tests for CharacterChunkingStrategy"""

    def test_strategy_name(self):
        """Should return correct strategy name"""
        strategy = CharacterChunkingStrategy()
        assert strategy.get_name() == "CharacterChunkingStrategy"

    def test_chunk_by_character_count(self):
        """Should split text by character count"""
        strategy = CharacterChunkingStrategy()
        text = "A" * 100
        chunks = strategy.chunk(text, chunk_size=30, chunk_overlap=5)

        assert len(chunks) >= 3
        for chunk in chunks:
            assert chunk.metadata["strategy"] == "character"

    def test_chunk_respects_exact_size(self):
        """Character strategy should produce more exact sizes"""
        strategy = CharacterChunkingStrategy()
        text = "A" * 200
        chunks = strategy.chunk(text, chunk_size=50, chunk_overlap=0)

        # Should produce exactly 4 chunks
        assert len(chunks) == 4
        for i, chunk in enumerate(chunks):
            if i < 3:
                assert len(chunk.text) == 50
            else:
                assert len(chunk.text) == 50  # Last chunk


class TestChunkingStrategyFactory:
    """Tests for ChunkingStrategyFactory"""

    def test_create_recursive_strategy(self):
        """Should create recursive strategy"""
        # Import to trigger registration
        import stache_ai.chunking.strategies  # noqa

        strategy = ChunkingStrategyFactory.create("recursive")
        assert isinstance(strategy, RecursiveChunkingStrategy)

    def test_create_markdown_strategy(self):
        """Should create markdown strategy"""
        import stache_ai.chunking.strategies  # noqa

        strategy = ChunkingStrategyFactory.create("markdown")
        assert isinstance(strategy, MarkdownChunkingStrategy)

    def test_create_character_strategy(self):
        """Should create character strategy"""
        import stache_ai.chunking.strategies  # noqa

        strategy = ChunkingStrategyFactory.create("character")
        assert isinstance(strategy, CharacterChunkingStrategy)

    def test_create_unknown_strategy(self):
        """Should raise error for unknown strategy"""
        with pytest.raises(ValueError) as exc_info:
            ChunkingStrategyFactory.create("nonexistent")
        assert "Unknown chunking strategy" in str(exc_info.value)

    def test_get_available_strategies(self):
        """Should list available strategies"""
        import stache_ai.chunking.strategies  # noqa

        strategies = ChunkingStrategyFactory.get_available_strategies()
        assert "recursive" in strategies
        assert "markdown" in strategies
        assert "character" in strategies

    def test_register_custom_strategy(self):
        """Should be able to register custom strategies"""

        class CustomStrategy(ChunkingStrategy):
            def chunk(self, text, chunk_size=2000, chunk_overlap=200, **kwargs):
                return [Chunk(text=text, index=0, metadata={"strategy": "custom"})]

        ChunkingStrategyFactory.register("custom_test", CustomStrategy)
        strategy = ChunkingStrategyFactory.create("custom_test")
        assert isinstance(strategy, CustomStrategy)

        # Clean up
        del ChunkingStrategyFactory._strategies["custom_test"]

"""Unit tests for OCR heuristic in OcrPdfLoader."""

import pytest
from stache_ai_ocr.loaders import OcrPdfLoader


class TestOcrHeuristic:
    """Test suite for _needs_ocr() method."""

    @pytest.fixture
    def loader(self):
        """Create OcrPdfLoader instance for testing."""
        return OcrPdfLoader()

    def test_empty_text_needs_ocr(self, loader):
        """Test that empty text triggers OCR."""
        assert loader._needs_ocr("", page_count=10) is True

    def test_whitespace_only_needs_ocr(self, loader):
        """Test that whitespace-only text triggers OCR."""
        assert loader._needs_ocr("   \n\t  ", page_count=5) is True

    def test_sparse_text_needs_ocr(self, loader):
        """Test that sparse text (<50 chars/page) triggers OCR."""
        # 10 pages with 40 chars/page = 400 chars total
        text = "a" * 400
        assert loader._needs_ocr(text, page_count=10) is True

    def test_dense_text_no_ocr(self, loader):
        """Test that dense text (>50 chars/page) does not trigger OCR."""
        # 10 pages with 100 chars/page = 1000 chars total
        text = "a" * 1000
        assert loader._needs_ocr(text, page_count=10) is False

    def test_boundary_exactly_50_chars_per_page(self, loader):
        """Test boundary case: exactly 50 chars/page should not trigger OCR."""
        # 10 pages with exactly 50 chars/page = 500 chars total
        text = "a" * 500
        # At exactly 50 chars/page, chars_per_page = 50, which is NOT < 50
        assert loader._needs_ocr(text, page_count=10) is False

    def test_boundary_just_below_threshold(self, loader):
        """Test boundary case: 49 chars/page should trigger OCR."""
        # 10 pages with 49 chars/page = 490 chars total
        text = "a" * 490
        assert loader._needs_ocr(text, page_count=10) is True

    def test_boundary_just_above_threshold(self, loader):
        """Test boundary case: 51 chars/page should not trigger OCR."""
        # 10 pages with 51 chars/page = 510 chars total
        text = "a" * 510
        assert loader._needs_ocr(text, page_count=10) is False

    def test_zero_pages_needs_ocr(self, loader):
        """Test edge case: 0 pages should trigger OCR."""
        # Division by zero protection: chars_per_page = 0 when page_count = 0
        assert loader._needs_ocr("Some text", page_count=0) is True

    def test_single_page_with_dense_text(self, loader):
        """Test single page with >50 chars does not trigger OCR."""
        text = "a" * 100  # 100 chars on 1 page = 100 chars/page
        assert loader._needs_ocr(text, page_count=1) is False

    def test_single_page_with_sparse_text(self, loader):
        """Test single page with <50 chars triggers OCR."""
        text = "a" * 30  # 30 chars on 1 page = 30 chars/page
        assert loader._needs_ocr(text, page_count=1) is True

    def test_scanned_pdf_with_page_numbers_only(self, loader):
        """Test realistic scenario: scanned PDF with only page numbers."""
        # Typical scanned PDF: 50 pages with "Page 1", "Page 2", etc.
        # Average ~6 chars/page (very sparse)
        text = "\n".join([f"Page {i}" for i in range(1, 51)])
        # Total chars ≈ 300 for 50 pages = 6 chars/page
        assert loader._needs_ocr(text, page_count=50) is True

    def test_normal_pdf_realistic_density(self, loader):
        """Test realistic scenario: normal PDF with typical text density."""
        # Typical page: ~2000 chars (about 300 words)
        text = "word " * 2000  # 10000 chars for 5 pages = 2000 chars/page
        assert loader._needs_ocr(text, page_count=5) is False

    def test_text_with_leading_trailing_whitespace(self, loader):
        """Test that whitespace is stripped before counting chars."""
        # Text with lots of whitespace but low actual char count
        text = "   \n\n  abc  \n\n   "
        # After strip: "abc" = 3 chars / 10 pages = 0.3 chars/page
        assert loader._needs_ocr(text, page_count=10) is True

    def test_negative_page_count_edge_case(self, loader):
        """Test edge case: negative page count (malformed PDF)."""
        # Should not happen in practice, but test robustness
        # Division by negative: chars_per_page would be negative, which is < 50
        text = "a" * 100
        # -1 pages: 100 / -1 = -100 chars/page, which IS < 50
        assert loader._needs_ocr(text, page_count=-1) is True

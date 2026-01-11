"""Integration tests for OcrPdfLoader with test corpus PDFs.

Tests the full OCR pipeline against a representative set of real PDF files
covering text-based, empty, single-page, scanned, multi-page, and hybrid PDFs.

Each test validates that:
1. The PDF loads without errors
2. Metadata is calculated correctly
3. OCR is applied/skipped as expected
4. The system gracefully handles missing ocrmypdf binary
"""

import pytest
from pathlib import Path

from stache_ai_ocr.loaders import OcrPdfLoader
from stache_ai_ocr.types import OcrLoadResult


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "pdfs"


class TestIntegrationWithTestCorpus:
    """Integration tests with actual PDF test corpus."""

    @pytest.fixture
    def loader(self):
        """Create loader with default timeout."""
        return OcrPdfLoader(timeout=300)

    def test_corpus_pdfs_exist(self):
        """Verify all test corpus PDFs are present."""
        expected_pdfs = [
            "01-text-based.pdf",
            "02-empty.pdf",
            "03-single-page.pdf",
            "04-scanned.pdf",
            "05-large-multipage.pdf",
            "06-hybrid.pdf",
        ]
        for pdf in expected_pdfs:
            pdf_path = FIXTURES_DIR / pdf
            assert pdf_path.exists(), f"Test corpus PDF not found: {pdf}"

    @pytest.mark.parametrize(
        "pdf_file,expected_ocr,min_chars,max_chars,page_count",
        [
            # (filename, should_use_ocr, min_expected_chars, max_expected_chars, pages)
            ("01-text-based.pdf", False, 900, 1000, 1),
            ("02-empty.pdf", True, 0, 100, 1),  # Empty - may have whitespace
            ("03-single-page.pdf", False, 150, 200, 1),
            ("04-scanned.pdf", True, 0, 100, 1),  # OCR attempted (may fail if binary missing)
            ("05-large-multipage.pdf", False, 6000, 7000, 11),
            ("06-hybrid.pdf", False, 300, 500, 2),
        ],
    )
    @pytest.mark.integration
    def test_load_with_test_corpus(
        self, loader, pdf_file, expected_ocr, min_chars, max_chars, page_count
    ):
        """Test load_with_metadata() against test corpus PDFs.

        Validates:
        - Correct page count detection
        - Character count within expected range
        - OCR used as expected
        - Metadata calculations are accurate
        """
        pdf_path = FIXTURES_DIR / pdf_file
        assert pdf_path.exists(), f"PDF file not found: {pdf_path}"

        result = loader.load_with_metadata(str(pdf_path))

        # Verify result type
        assert isinstance(result, OcrLoadResult), f"Expected OcrLoadResult, got {type(result)}"

        # Verify page count
        assert result.page_count == page_count, (
            f"{pdf_file}: Expected {page_count} pages, got {result.page_count}"
        )

        # Verify character count is in expected range
        assert (
            min_chars <= result.char_count <= max_chars
        ), f"{pdf_file}: char_count {result.char_count} outside range [{min_chars}, {max_chars}]"

        # Verify OCR usage (accounting for ocrmypdf binary availability)
        if expected_ocr:
            # OCR was expected to be triggered
            assert result.ocr_used is True, (
                f"{pdf_file}: OCR was expected to be used, but ocr_used={result.ocr_used}"
            )

            # ocrmypdf might not be installed, but should have been attempted
            if result.ocr_failed:
                # If ocrmypdf is missing, we expect a specific error message
                assert (
                    "not found" in result.error_reason
                    or "Timeout" in result.error_reason
                    or result.error_reason is not None
                ), f"{pdf_file}: Expected failure reason but got: {result.error_reason}"
        else:
            # OCR should not have been used
            assert result.ocr_used is False, (
                f"{pdf_file}: OCR should not be used, but ocr_used={result.ocr_used}"
            )
            assert result.ocr_failed is False
            assert result.ocr_method is None

        # Verify chars_per_page calculation is reasonable
        expected_chars_per_page = result.char_count / page_count if page_count > 0 else 0
        assert abs(result.chars_per_page - expected_chars_per_page) < 0.01, (
            f"{pdf_file}: chars_per_page mismatch: "
            f"expected {expected_chars_per_page}, got {result.chars_per_page}"
        )

        # Verify text is not None
        assert result.text is not None, f"{pdf_file}: text should not be None"

    @pytest.mark.integration
    def test_01_text_based_no_ocr(self, loader):
        """Test 01-text-based.pdf: Born-digital PDF without OCR."""
        pdf_path = FIXTURES_DIR / "01-text-based.pdf"
        result = loader.load_with_metadata(str(pdf_path))

        assert result.page_count == 1
        assert result.char_count >= 900  # Multiple paragraphs
        assert result.ocr_used is False
        assert result.ocr_failed is False
        assert result.ocr_method is None
        assert result.error_reason is None
        assert len(result.text) >= 900

    @pytest.mark.integration
    def test_02_empty_triggers_ocr(self, loader):
        """Test 02-empty.pdf: Blank page triggers OCR attempt."""
        pdf_path = FIXTURES_DIR / "02-empty.pdf"
        result = loader.load_with_metadata(str(pdf_path))

        assert result.page_count == 1
        # Empty PDF - may extract some whitespace or nothing
        assert result.char_count < 100
        # Should attempt OCR for empty document
        assert result.ocr_used is True

    @pytest.mark.integration
    def test_03_single_page_baseline(self, loader):
        """Test 03-single-page.pdf: Single page baseline."""
        pdf_path = FIXTURES_DIR / "03-single-page.pdf"
        result = loader.load_with_metadata(str(pdf_path))

        assert result.page_count == 1
        assert 150 <= result.char_count <= 200  # Title + brief content
        assert result.ocr_used is False
        assert result.chars_per_page == result.char_count

    @pytest.mark.integration
    def test_04_scanned_ocr_attempt(self, loader):
        """Test 04-scanned.pdf: Scanned document triggers OCR."""
        pdf_path = FIXTURES_DIR / "04-scanned.pdf"
        result = loader.load_with_metadata(str(pdf_path))

        assert result.page_count == 1
        # Scanned PDF should attempt OCR
        assert result.ocr_used is True

        # If ocrmypdf is installed, expect extracted text
        # If not installed, expect failure message
        if result.ocr_failed:
            assert "not found" in result.error_reason or "Timeout" in result.error_reason
        else:
            # OCR succeeded - expect some extracted text
            assert result.char_count > 0

    @pytest.mark.integration
    def test_05_large_multipage_performance(self, loader):
        """Test 05-large-multipage.pdf: 11-page document."""
        pdf_path = FIXTURES_DIR / "05-large-multipage.pdf"
        result = loader.load_with_metadata(str(pdf_path))

        assert result.page_count == 11
        assert result.char_count >= 6000  # 11 pages of lorem ipsum
        assert result.ocr_used is False
        assert result.chars_per_page >= 500  # Multiple paragraphs per page

    @pytest.mark.integration
    def test_06_hybrid_mixed_content(self, loader):
        """Test 06-hybrid.pdf: Page 1 text, Page 2 scanned."""
        pdf_path = FIXTURES_DIR / "06-hybrid.pdf"
        result = loader.load_with_metadata(str(pdf_path))

        assert result.page_count == 2
        # Page 1 has sufficient text to avoid OCR
        assert result.ocr_used is False
        assert 300 <= result.char_count <= 500

    @pytest.mark.integration
    def test_metadata_to_dict_serialization(self, loader):
        """Test OcrLoadResult.to_dict() serialization."""
        pdf_path = FIXTURES_DIR / "01-text-based.pdf"
        result = loader.load_with_metadata(str(pdf_path))

        result_dict = result.to_dict()

        assert isinstance(result_dict, dict)
        assert "text" in result_dict
        assert "page_count" in result_dict
        assert "char_count" in result_dict
        assert "chars_per_page" in result_dict
        assert "ocr_used" in result_dict
        assert "ocr_failed" in result_dict
        assert "ocr_method" in result_dict
        assert "error_reason" in result_dict

    @pytest.mark.integration
    def test_backward_compatibility_load_method(self, loader):
        """Test backward compatibility: load() delegates to load_with_metadata().text."""
        pdf_path = FIXTURES_DIR / "01-text-based.pdf"

        # Old method
        text = loader.load(str(pdf_path))
        # New method
        result = loader.load_with_metadata(str(pdf_path))

        # Should return same text
        assert text == result.text
        assert isinstance(text, str)
        assert len(text) > 0


class TestOcrBinaryHandling:
    """Test behavior when ocrmypdf binary is unavailable."""

    @pytest.fixture
    def loader(self):
        """Create loader for OCR tests."""
        return OcrPdfLoader(timeout=300)

    @pytest.mark.integration
    def test_missing_ocrmypdf_graceful_failure(self, loader):
        """Test graceful handling when ocrmypdf binary is missing.

        For scanned PDFs, if ocrmypdf is not installed, should:
        1. Still return original (sparse) text
        2. Mark ocr_used=True (attempted)
        3. Mark ocr_failed=True (failed)
        4. Include descriptive error message
        """
        pdf_path = FIXTURES_DIR / "04-scanned.pdf"
        result = loader.load_with_metadata(str(pdf_path))

        # If ocrmypdf is not installed, we should see failure metadata
        if result.ocr_failed:
            assert result.ocr_method == "ocrmypdf"
            assert result.error_reason is not None
            assert len(result.error_reason) > 0

        # Regardless, should have page count
        assert result.page_count == 1

        # Should have some text (either from initial extraction or error handling)
        assert result.text is not None

        # Result should be serializable
        result_dict = result.to_dict()
        assert isinstance(result_dict, dict)


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.fixture
    def loader(self):
        """Create loader."""
        return OcrPdfLoader(timeout=300)

    @pytest.mark.integration
    def test_all_pdfs_load_without_exception(self, loader):
        """Regression test: all PDFs should load without raising exceptions."""
        pdfs = list(FIXTURES_DIR.glob("*.pdf"))
        assert len(pdfs) == 6, "Expected 6 test PDFs"

        for pdf_path in sorted(pdfs):
            # Should not raise any exception
            result = loader.load_with_metadata(str(pdf_path))
            assert isinstance(result, OcrLoadResult)

    @pytest.mark.integration
    def test_all_pdfs_have_valid_metadata(self, loader):
        """Verify all PDFs produce valid metadata."""
        pdfs = list(FIXTURES_DIR.glob("*.pdf"))

        for pdf_path in sorted(pdfs):
            result = loader.load_with_metadata(str(pdf_path))

            # Check all required fields are present
            assert result.text is not None
            assert result.page_count > 0
            assert result.char_count >= 0
            assert result.chars_per_page >= 0
            assert isinstance(result.ocr_used, bool)
            assert isinstance(result.ocr_failed, bool)

            # If OCR used, should have method info
            if result.ocr_used:
                assert result.ocr_method == "ocrmypdf"

            # If OCR failed, should have error reason
            if result.ocr_failed:
                assert result.error_reason is not None

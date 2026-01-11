"""Unit tests for OcrLoadResult dataclass."""

import pytest
from stache_ai_ocr.types import OcrLoadResult


class TestOcrLoadResult:
    """Test suite for OcrLoadResult dataclass."""

    def test_instantiation_with_all_fields(self):
        """Test creating OcrLoadResult with all fields specified."""
        result = OcrLoadResult(
            text="Extracted content from PDF",
            page_count=10,
            ocr_used=True,
            ocr_failed=False,
            ocr_method="ocrmypdf",
            char_count=2500,
            chars_per_page=250.0,
        )

        assert result.text == "Extracted content from PDF"
        assert result.page_count == 10
        assert result.ocr_used is True
        assert result.ocr_failed is False
        assert result.ocr_method == "ocrmypdf"
        assert result.char_count == 2500
        assert result.chars_per_page == 250.0

    def test_default_values(self):
        """Test that ocr_failed defaults to False and ocr_method/error_reason to None."""
        result = OcrLoadResult(
            text="Simple text",
            page_count=5,
            ocr_used=False,
            char_count=1000,
            chars_per_page=200.0,
        )

        assert result.ocr_failed is False
        assert result.ocr_method is None
        assert result.error_reason is None

    def test_ocr_failed_scenario(self):
        """Test OcrLoadResult for failed OCR scenario."""
        result = OcrLoadResult(
            text="Partial extraction before failure",
            page_count=20,
            ocr_used=True,
            ocr_failed=True,
            ocr_method="ocrmypdf",
            char_count=150,
            chars_per_page=7.5,
        )

        assert result.ocr_failed is True
        assert result.ocr_used is True
        assert result.chars_per_page == 7.5  # Low value indicates scanned

    def test_to_dict_serialization(self):
        """Test to_dict() produces correct dictionary."""
        result = OcrLoadResult(
            text="Test content",
            page_count=3,
            ocr_used=True,
            ocr_method="tesseract",
            char_count=900,
            chars_per_page=300.0,
        )

        result_dict = result.to_dict()

        expected = {
            "text": "Test content",
            "page_count": 3,
            "ocr_used": True,
            "ocr_failed": False,
            "ocr_method": "tesseract",
            "error_reason": None,
            "char_count": 900,
            "chars_per_page": 300.0,
        }

        assert result_dict == expected

    def test_to_dict_with_none_method(self):
        """Test to_dict() when ocr_method is None."""
        result = OcrLoadResult(
            text="Direct extraction",
            page_count=2,
            ocr_used=False,
            char_count=500,
            chars_per_page=250.0,
        )

        result_dict = result.to_dict()

        assert result_dict["ocr_method"] is None
        assert result_dict["ocr_used"] is False

    def test_empty_text(self):
        """Test OcrLoadResult with empty text (complete failure)."""
        result = OcrLoadResult(
            text="",
            page_count=1,
            ocr_used=True,
            ocr_failed=True,
            ocr_method="ocrmypdf",
            char_count=0,
            chars_per_page=0.0,
        )

        assert result.text == ""
        assert result.char_count == 0
        assert result.chars_per_page == 0.0
        assert result.ocr_failed is True

    def test_scanned_pdf_heuristic_low_density(self):
        """Test chars_per_page heuristic for scanned PDF detection."""
        # Scanned PDF: low chars per page
        scanned_result = OcrLoadResult(
            text="abc",
            page_count=5,
            ocr_used=True,
            ocr_method="ocrmypdf",
            char_count=50,
            chars_per_page=10.0,
        )

        assert scanned_result.chars_per_page < 100  # Heuristic threshold

    def test_native_pdf_heuristic_high_density(self):
        """Test chars_per_page heuristic for native (text-based) PDF."""
        # Native PDF: high chars per page
        native_result = OcrLoadResult(
            text="A" * 5000,
            page_count=10,
            ocr_used=False,
            char_count=5000,
            chars_per_page=500.0,
        )

        assert native_result.chars_per_page > 100  # Well above threshold

    def test_type_hints_validation(self):
        """Test that type hints are correct (Python 3.9+ union syntax)."""
        # This test verifies the structure exists and is valid
        # Type checking is done by mypy/static analyzers, but we verify instantiation
        result_with_none = OcrLoadResult(
            text="test",
            page_count=1,
            ocr_used=False,
            char_count=4,
            chars_per_page=4.0,
            ocr_method=None,  # Explicitly None
        )

        result_with_string = OcrLoadResult(
            text="test",
            page_count=1,
            ocr_used=True,
            char_count=4,
            chars_per_page=4.0,
            ocr_method="ocrmypdf",  # String value
        )

        assert result_with_none.ocr_method is None
        assert result_with_string.ocr_method == "ocrmypdf"

    def test_error_reason_on_success(self):
        """Test that error_reason is None when OCR succeeds."""
        result = OcrLoadResult(
            text="Successfully extracted text",
            page_count=5,
            ocr_used=True,
            ocr_failed=False,
            ocr_method="ocrmypdf",
            char_count=1000,
            chars_per_page=200.0,
            error_reason=None,  # No error on success
        )

        assert result.ocr_failed is False
        assert result.error_reason is None
        assert result.ocr_method == "ocrmypdf"

    def test_error_reason_on_timeout(self):
        """Test error_reason captures timeout failures."""
        result = OcrLoadResult(
            text="Partial text before timeout",
            page_count=100,
            ocr_used=True,
            ocr_failed=True,
            ocr_method="ocrmypdf",
            error_reason="Timeout exceeded: 300s",
            char_count=50,
            chars_per_page=0.5,
        )

        assert result.ocr_failed is True
        assert result.error_reason == "Timeout exceeded: 300s"
        assert "Timeout" in result.error_reason

    def test_error_reason_on_missing_binary(self):
        """Test error_reason captures missing binary failures."""
        result = OcrLoadResult(
            text="Fallback extraction without OCR",
            page_count=10,
            ocr_used=True,
            ocr_failed=True,
            ocr_method=None,  # No method used since binary missing
            error_reason="ocrmypdf binary not found in PATH",
            char_count=100,
            chars_per_page=10.0,
        )

        assert result.ocr_failed is True
        assert result.error_reason == "ocrmypdf binary not found in PATH"
        assert "binary not found" in result.error_reason
        assert result.ocr_method is None

    def test_error_reason_in_to_dict(self):
        """Test that error_reason is included in to_dict() output."""
        result = OcrLoadResult(
            text="Error scenario",
            page_count=1,
            ocr_used=True,
            ocr_failed=True,
            ocr_method="tesseract",
            error_reason="Unsupported PDF encryption",
            char_count=0,
            chars_per_page=0.0,
        )

        result_dict = result.to_dict()

        assert "error_reason" in result_dict
        assert result_dict["error_reason"] == "Unsupported PDF encryption"
        assert result_dict["ocr_failed"] is True

    def test_error_reason_default_none(self):
        """Test that error_reason defaults to None when not specified."""
        result = OcrLoadResult(
            text="Normal extraction",
            page_count=3,
            ocr_used=False,
            char_count=300,
            chars_per_page=100.0,
        )

        assert result.error_reason is None
        assert result.to_dict()["error_reason"] is None

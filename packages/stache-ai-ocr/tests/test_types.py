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
        )

        assert result.text == "Extracted content from PDF"
        assert result.page_count == 10
        assert result.ocr_used is True
        assert result.ocr_failed is False
        assert result.ocr_method == "ocrmypdf"

    def test_default_values(self):
        """Test that ocr_failed defaults to False and ocr_method/error_reason to None."""
        result = OcrLoadResult(
            text="Simple text",
            page_count=5,
            ocr_used=False,
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
        )

        assert result.ocr_failed is True
        assert result.ocr_used is True

    def test_to_dict_serialization(self):
        """Test to_dict() produces correct dictionary."""
        result = OcrLoadResult(
            text="Test content",
            page_count=3,
            ocr_used=True,
            ocr_method="tesseract",
        )

        result_dict = result.to_dict()

        expected = {
            "text": "Test content",
            "page_count": 3,
            "ocr_used": True,
            "ocr_failed": False,
            "ocr_method": "tesseract",
            "error_reason": None,
        }

        assert result_dict == expected

    def test_to_dict_with_none_method(self):
        """Test to_dict() when ocr_method is None."""
        result = OcrLoadResult(
            text="Direct extraction",
            page_count=2,
            ocr_used=False,
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
        )

        assert result.text == ""
        assert result.ocr_failed is True

    def test_type_hints_validation(self):
        """Test that type hints are correct (Python 3.9+ union syntax)."""
        result_with_none = OcrLoadResult(
            text="test",
            page_count=1,
            ocr_used=False,
            ocr_method=None,
        )

        result_with_string = OcrLoadResult(
            text="test",
            page_count=1,
            ocr_used=True,
            ocr_method="ocrmypdf",
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
            error_reason=None,
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
            ocr_method=None,
            error_reason="ocrmypdf binary not found in PATH",
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
        )

        assert result.error_reason is None
        assert result.to_dict()["error_reason"] is None

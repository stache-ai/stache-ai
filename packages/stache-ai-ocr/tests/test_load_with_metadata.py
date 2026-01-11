"""Tests for OcrPdfLoader.load_with_metadata() method."""

import subprocess
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest

from stache_ai_ocr.loaders import OcrPdfLoader
from stache_ai_ocr.types import OcrLoadResult


class TestLoadWithMetadata:
    """Test suite for load_with_metadata() method."""

    @pytest.fixture
    def loader(self):
        """Create loader with default timeout."""
        return OcrPdfLoader(timeout=300)

    @pytest.fixture
    def mock_pdf(self):
        """Create mock PDF with configurable pages."""
        def _create_mock(pages_text: list[str]):
            mock_pdf = MagicMock()
            mock_pdf.pages = []
            for text in pages_text:
                page = MagicMock()
                page.extract_text.return_value = text
                mock_pdf.pages.append(page)
            # Make it work as context manager
            mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
            mock_pdf.__exit__ = MagicMock(return_value=False)
            return mock_pdf
        return _create_mock

    def test_text_based_pdf_no_ocr(self, loader, mock_pdf):
        """Test text-based PDF with sufficient text density (no OCR needed)."""
        # 100 chars per page - well above threshold
        page_text = "A" * 100
        mock_pdf_obj = mock_pdf([page_text, page_text, page_text])

        with patch("pdfplumber.open", return_value=mock_pdf_obj):
            result = loader.load_with_metadata("test.pdf")

        assert isinstance(result, OcrLoadResult)
        expected_text = f"{page_text}\n\n{page_text}\n\n{page_text}"
        assert result.text == expected_text
        assert result.page_count == 3
        # char_count includes the \n\n separators (4 chars total between 3 pages)
        assert result.char_count == len(expected_text.strip())
        assert result.chars_per_page == pytest.approx(101.33, rel=0.01)
        assert result.ocr_used is False
        assert result.ocr_failed is False
        assert result.ocr_method is None
        assert result.error_reason is None

    def test_scanned_pdf_ocr_success(self, loader, mock_pdf):
        """Test scanned PDF where OCR succeeds."""
        # Sparse text: only 10 chars per page (below threshold)
        sparse_text = "A" * 10
        ocr_text = "OCR extracted text " * 50  # ~950 chars per page

        mock_initial_pdf = mock_pdf([sparse_text, sparse_text])
        mock_ocr_pdf = mock_pdf([ocr_text, ocr_text])

        with patch("pdfplumber.open") as mock_open:
            # First call: initial extraction
            # Second call: after OCR
            mock_open.side_effect = [mock_initial_pdf, mock_ocr_pdf]

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = Mock(returncode=0, stderr="")

                result = loader.load_with_metadata("test.pdf")

        expected_ocr_text = f"{ocr_text}\n\n{ocr_text}"
        assert result.text == expected_ocr_text
        assert result.page_count == 2
        assert result.char_count == len(expected_ocr_text.strip())
        assert result.chars_per_page == pytest.approx(950.5, rel=0.01)
        assert result.ocr_used is True
        assert result.ocr_failed is False
        assert result.ocr_method == "ocrmypdf"
        assert result.error_reason is None

    def test_empty_pdf_ocr_success(self, loader, mock_pdf):
        """Test completely empty PDF where OCR succeeds."""
        ocr_text = "OCR extracted text"
        mock_initial_pdf = mock_pdf(["", ""])
        mock_ocr_pdf = mock_pdf([ocr_text, ocr_text])

        with patch("pdfplumber.open") as mock_open:
            mock_open.side_effect = [mock_initial_pdf, mock_ocr_pdf]

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = Mock(returncode=0, stderr="")

                result = loader.load_with_metadata("test.pdf")

        assert result.text == f"{ocr_text}\n\n{ocr_text}"
        assert result.ocr_used is True
        assert result.ocr_failed is False

    def test_ocr_timeout(self, loader, mock_pdf):
        """Test OCR timeout returns original text with error metadata."""
        sparse_text = "A" * 10
        mock_pdf_obj = mock_pdf([sparse_text, sparse_text])

        with patch("pdfplumber.open", return_value=mock_pdf_obj):
            with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(
                cmd="ocrmypdf", timeout=300
            )):
                result = loader.load_with_metadata("test.pdf")

        # Should return original sparse text when OCR times out
        expected_text = f"{sparse_text}\n\n{sparse_text}"
        assert result.text == expected_text
        assert result.page_count == 2
        assert result.char_count == len(expected_text.strip())
        assert result.chars_per_page == pytest.approx(11.0, rel=0.01)
        assert result.ocr_used is True
        assert result.ocr_failed is True
        assert result.ocr_method == "ocrmypdf"
        assert "Timeout after 300s" in result.error_reason

    def test_ocr_binary_not_found(self, loader, mock_pdf):
        """Test missing ocrmypdf binary returns error metadata."""
        sparse_text = "A" * 10
        mock_pdf_obj = mock_pdf([sparse_text])

        with patch("pdfplumber.open", return_value=mock_pdf_obj):
            with patch("subprocess.run", side_effect=FileNotFoundError(
                "[Errno 2] No such file or directory: 'ocrmypdf'"
            )):
                result = loader.load_with_metadata("test.pdf")

        assert result.text == sparse_text
        assert result.ocr_used is True
        assert result.ocr_failed is True
        assert result.ocr_method == "ocrmypdf"
        assert "not found" in result.error_reason
        assert "apt install ocrmypdf" in result.error_reason

    def test_ocr_subprocess_error(self, loader, mock_pdf):
        """Test OCR subprocess failure with non-zero exit code."""
        sparse_text = "A" * 10
        mock_initial_pdf = mock_pdf([sparse_text])

        with patch("pdfplumber.open", return_value=mock_initial_pdf):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = Mock(
                    returncode=1,
                    stderr="Error: Unsupported PDF encryption"
                )

                result = loader.load_with_metadata("test.pdf")

        # Non-zero return code means OCR failed but didn't raise
        # Should return original text with failure flag
        assert result.text == sparse_text
        assert result.ocr_used is True
        assert result.ocr_failed is True
        assert result.error_reason == "OCR process completed but returned no text"

    def test_ocr_generic_exception(self, loader, mock_pdf):
        """Test generic OCR exception handling."""
        sparse_text = "A" * 10
        mock_pdf_obj = mock_pdf([sparse_text])

        with patch("pdfplumber.open", return_value=mock_pdf_obj):
            with patch("subprocess.run", side_effect=RuntimeError("Unexpected error")):
                result = loader.load_with_metadata("test.pdf")

        assert result.text == sparse_text
        assert result.ocr_used is True
        assert result.ocr_failed is True
        assert result.error_reason == "Unexpected error"

    def test_metadata_accuracy_single_page(self, loader, mock_pdf):
        """Test metadata calculations for single-page PDF."""
        text = "Hello world"  # 11 chars
        mock_pdf_obj = mock_pdf([text])

        with patch("pdfplumber.open", return_value=mock_pdf_obj):
            result = loader.load_with_metadata("test.pdf")

        assert result.page_count == 1
        assert result.char_count == 11
        assert result.chars_per_page == 11.0

    def test_metadata_accuracy_multi_page(self, loader, mock_pdf):
        """Test metadata calculations for multi-page PDF."""
        page1 = "A" * 100
        page2 = "B" * 200
        page3 = "C" * 300
        mock_pdf_obj = mock_pdf([page1, page2, page3])

        with patch("pdfplumber.open", return_value=mock_pdf_obj):
            result = loader.load_with_metadata("test.pdf")

        # Total: 600 chars of content + 4 chars for \n\n separators
        expected_text = f"{page1}\n\n{page2}\n\n{page3}"
        assert result.page_count == 3
        assert result.char_count == len(expected_text.strip())
        assert result.chars_per_page == pytest.approx(201.33, rel=0.01)

    def test_backward_compatibility_load_delegates(self, loader, mock_pdf):
        """Test that load() method delegates to load_with_metadata().text."""
        text = "Test content"
        mock_pdf_obj = mock_pdf([text])

        with patch("pdfplumber.open", return_value=mock_pdf_obj):
            # Call old load() method
            result_text = loader.load("test.pdf")
            # Call new method directly
            result_obj = loader.load_with_metadata("test.pdf")

        # Should return same text
        assert result_text == result_obj.text
        assert result_text == text

    def test_custom_timeout_used(self, mock_pdf):
        """Test that custom timeout is passed to subprocess."""
        loader = OcrPdfLoader(timeout=60)
        sparse_text = "A" * 10
        mock_pdf_obj = mock_pdf([sparse_text])

        with patch("pdfplumber.open", return_value=mock_pdf_obj):
            with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(
                cmd="ocrmypdf", timeout=60
            )) as mock_run:
                result = loader.load_with_metadata("test.pdf")

        # Verify custom timeout was used
        assert "Timeout after 60s" in result.error_reason

    def test_to_dict_serialization(self, loader, mock_pdf):
        """Test that OcrLoadResult can be serialized to dict."""
        # Use text with sufficient density to avoid OCR (>50 chars/page)
        text = "A" * 100
        mock_pdf_obj = mock_pdf([text])

        with patch("pdfplumber.open", return_value=mock_pdf_obj):
            result = loader.load_with_metadata("test.pdf")

        result_dict = result.to_dict()

        assert isinstance(result_dict, dict)
        assert result_dict["text"] == text
        assert result_dict["page_count"] == 1
        assert result_dict["ocr_used"] is False
        assert result_dict["ocr_failed"] is False

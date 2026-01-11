"""Unit tests for OCR timeout functionality."""

import os
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

import pytest

from stache_ai_ocr.loaders import OcrPdfLoader


class TestOcrTimeout:
    """Test suite for OCR timeout functionality."""

    def test_default_timeout_300_seconds(self):
        """Test that default timeout is 300 seconds when not specified."""
        loader = OcrPdfLoader()
        assert loader.timeout == 300

    def test_custom_timeout_via_constructor(self):
        """Test setting custom timeout via constructor."""
        loader = OcrPdfLoader(timeout=120)
        assert loader.timeout == 120

    @patch.dict(os.environ, {"STACHE_OCR_TIMEOUT": "600"})
    def test_timeout_from_env_var(self):
        """Test reading timeout from STACHE_OCR_TIMEOUT environment variable."""
        loader = OcrPdfLoader()
        assert loader.timeout == 600

    @patch.dict(os.environ, {"STACHE_OCR_TIMEOUT": "600"})
    def test_constructor_overrides_env_var(self):
        """Test that constructor timeout overrides environment variable."""
        loader = OcrPdfLoader(timeout=180)
        assert loader.timeout == 180

    @patch("stache_ai_ocr.loaders.subprocess.run")
    def test_timeout_passed_to_subprocess(self, mock_run):
        """Test that timeout is passed to subprocess.run() call."""
        # Mock pdfplumber within the function scope (lazy import)
        with patch("pdfplumber.open") as mock_pdfplumber_open:
            # Mock PDF with no text (triggers OCR)
            mock_pdf = MagicMock()
            mock_pdf.pages = [MagicMock()]
            mock_pdf.pages[0].extract_text.return_value = ""
            mock_pdfplumber_open.return_value.__enter__.return_value = mock_pdf

            # Mock successful OCR
            mock_run.return_value = MagicMock(returncode=0, stderr="")

            loader = OcrPdfLoader(timeout=45)

            with patch("builtins.open", mock_open(read_data=b"fake pdf")):
                loader.load("/fake/path.pdf")

            # Verify subprocess.run was called with correct timeout
            assert mock_run.called
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["timeout"] == 45

    @patch("stache_ai_ocr.loaders.subprocess.run")
    def test_timeout_exceeded_returns_empty_text(self, mock_run):
        """Test that TimeoutExpired exception returns empty text gracefully."""
        with patch("pdfplumber.open") as mock_pdfplumber_open:
            # Mock PDF with no text (triggers OCR)
            mock_pdf = MagicMock()
            mock_pdf.pages = [MagicMock()]
            mock_pdf.pages[0].extract_text.return_value = ""
            mock_pdfplumber_open.return_value.__enter__.return_value = mock_pdf

            # Mock timeout exception
            mock_run.side_effect = subprocess.TimeoutExpired(
                cmd=["ocrmypdf"], timeout=60
            )

            loader = OcrPdfLoader(timeout=60)

            with patch("builtins.open", mock_open(read_data=b"fake pdf")):
                result = loader.load("/fake/path.pdf")

            # Should return empty string (no text extracted due to timeout)
            assert result == ""

    @patch("stache_ai_ocr.loaders.logger")
    @patch("stache_ai_ocr.loaders.subprocess.run")
    def test_timeout_logs_warning(self, mock_run, mock_logger):
        """Test that timeout exception logs appropriate info message when OCR is triggered."""
        with patch("pdfplumber.open") as mock_pdfplumber_open:
            # Mock PDF with no text (triggers OCR)
            mock_pdf = MagicMock()
            mock_pdf.pages = [MagicMock()]
            mock_pdf.pages[0].extract_text.return_value = ""
            mock_pdfplumber_open.return_value.__enter__.return_value = mock_pdf

            # Mock timeout exception
            mock_run.side_effect = subprocess.TimeoutExpired(
                cmd=["ocrmypdf"], timeout=90
            )

            loader = OcrPdfLoader(timeout=90)

            with patch("builtins.open", mock_open(read_data=b"fake pdf")):
                result = loader.load("/fake/path.pdf")

            # Verify info message was logged when OCR was triggered
            # (timeout is caught silently and returned via metadata)
            assert mock_logger.info.called
            info_msg = mock_logger.info.call_args[0][0]
            assert "OCR" in info_msg or "ocr" in info_msg.lower()
            # Result should be empty since original PDF had no text
            assert result == ""

    @patch("stache_ai_ocr.loaders.subprocess.run")
    def test_successful_ocr_within_timeout(self, mock_run):
        """Test that successful OCR within timeout returns extracted text."""
        with patch("pdfplumber.open") as mock_pdfplumber_open:
            # Mock PDF with no text (triggers OCR)
            mock_initial_pdf = MagicMock()
            mock_initial_pdf.pages = [MagicMock()]
            mock_initial_pdf.pages[0].extract_text.return_value = ""

            # Mock OCR'd PDF with text
            mock_ocr_pdf = MagicMock()
            mock_ocr_pdf.pages = [MagicMock()]
            mock_ocr_pdf.pages[0].extract_text.return_value = "OCR extracted text"

            mock_pdfplumber_open.return_value.__enter__.side_effect = [
                mock_initial_pdf,
                mock_ocr_pdf
            ]

            # Mock successful OCR (no timeout)
            mock_run.return_value = MagicMock(returncode=0, stderr="")

            loader = OcrPdfLoader(timeout=120)

            with patch("builtins.open", mock_open(read_data=b"fake pdf")):
                result = loader.load("/fake/path.pdf")

            # Should return OCR extracted text
            assert result == "OCR extracted text"

    @patch("stache_ai_ocr.loaders.subprocess.run")
    def test_timeout_with_partial_text_before_ocr(self, mock_run):
        """Test timeout when PDF has some text but OCR is triggered for low density.

        Task 1.3 implementation: Preserves original text when OCR fails.
        """
        with patch("pdfplumber.open") as mock_pdfplumber_open:
            # Mock PDF with low text density (triggers OCR)
            mock_initial_pdf = MagicMock()
            mock_initial_pdf.pages = [MagicMock()]
            mock_initial_pdf.pages[0].extract_text.return_value = "a"  # 1 char, triggers OCR

            mock_pdfplumber_open.return_value.__enter__.return_value = mock_initial_pdf

            # Mock timeout exception
            mock_run.side_effect = subprocess.TimeoutExpired(
                cmd=["ocrmypdf"], timeout=150
            )

            loader = OcrPdfLoader(timeout=150)

            with patch("builtins.open", mock_open(read_data=b"fake pdf")):
                result = loader.load("/fake/path.pdf")

            # Task 1.3: Preserves original text when OCR fails
            assert result == "a"

    @patch.dict(os.environ, {}, clear=True)
    def test_timeout_env_var_not_set_uses_default(self):
        """Test that missing env var falls back to 300s default."""
        # Ensure env var is not set
        if "STACHE_OCR_TIMEOUT" in os.environ:
            del os.environ["STACHE_OCR_TIMEOUT"]

        loader = OcrPdfLoader()
        assert loader.timeout == 300

    def test_zero_timeout_rejected(self):
        """Test that zero timeout is rejected with clear error."""
        with pytest.raises(ValueError, match="Timeout must be positive, got 0"):
            OcrPdfLoader(timeout=0)

    def test_negative_timeout_rejected(self):
        """Test that negative timeout is rejected with clear error."""
        with pytest.raises(ValueError, match="Timeout must be positive, got -10"):
            OcrPdfLoader(timeout=-10)

    def test_negative_timeout_from_env_rejected(self):
        """Test that negative timeout from env is rejected with clear error."""
        with patch.dict(os.environ, {"STACHE_OCR_TIMEOUT": "-10"}):
            with pytest.raises(ValueError, match="STACHE_OCR_TIMEOUT must be positive, got -10"):
                OcrPdfLoader()

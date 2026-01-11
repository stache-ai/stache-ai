"""PDF loader with OCR fallback for scanned documents"""

import logging
import os
import subprocess
import tempfile
from pathlib import Path

from stache_ai.loaders.base import DocumentLoader
from .types import OcrLoadResult

logger = logging.getLogger(__name__)


class OcrPdfLoader(DocumentLoader):
    """PDF loader with OCR fallback for scanned documents

    Requires ocrmypdf system binary: apt install ocrmypdf
    """

    def __init__(self, timeout: int | None = None):
        """Initialize OCR PDF loader.

        Args:
            timeout: Maximum time in seconds for OCR processing.
                    Defaults to STACHE_OCR_TIMEOUT env var or 300 seconds.
                    Must be positive (>0).

        Raises:
            ValueError: If timeout is negative or zero
        """
        if timeout is not None:
            if timeout <= 0:
                raise ValueError(f"Timeout must be positive, got {timeout}")
            self.timeout = timeout
        else:
            env_timeout = int(os.getenv("STACHE_OCR_TIMEOUT", "300"))
            if env_timeout <= 0:
                raise ValueError(f"STACHE_OCR_TIMEOUT must be positive, got {env_timeout}")
            self.timeout = env_timeout

    @property
    def extensions(self) -> list[str]:
        return ['pdf']

    @property
    def priority(self) -> int:
        return 10  # Override basic PdfLoader (priority 0)

    def _needs_ocr(self, text: str, page_count: int) -> bool:
        """Determine if PDF needs OCR based on text density.

        Uses a heuristic of <50 chars/page to detect scanned documents.
        This catches both completely empty PDFs and sparse-text PDFs
        (e.g., scanned docs with only page numbers).

        Args:
            text: Extracted text from PDF
            page_count: Number of pages in PDF

        Returns:
            True if OCR should be applied, False otherwise
        """
        if not text.strip():
            return True  # Empty text definitely needs OCR

        char_count = len(text.strip())
        chars_per_page = char_count / page_count if page_count > 0 else 0

        # Threshold: <50 chars/page suggests scanned document
        return chars_per_page < 50

    def load_with_metadata(self, file_path: str) -> OcrLoadResult:
        """Load PDF with rich metadata about OCR process.

        This method provides detailed information about text extraction,
        including whether OCR was applied, why it was needed, and any
        failures that occurred.

        Args:
            file_path: Path to the PDF file

        Returns:
            OcrLoadResult with extracted text and metadata

        Example:
            >>> loader = OcrPdfLoader(timeout=300)
            >>> result = loader.load_with_metadata("document.pdf")
            >>> print(f"Extracted {result.char_count} chars")
            >>> if result.ocr_used:
            ...     print(f"Used OCR: {result.ocr_method}")
            >>> if result.ocr_failed:
            ...     print(f"OCR failed: {result.error_reason}")
        """
        # Lazy import
        import pdfplumber

        # Try normal extraction first
        text_parts = []
        page_count = 0
        with pdfplumber.open(file_path) as pdf:
            page_count = len(pdf.pages)
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    text_parts.append(text)

        extracted_text = "\n\n".join(text_parts)
        char_count = len(extracted_text.strip())
        chars_per_page = char_count / page_count if page_count > 0 else 0

        # Check if OCR is needed based on text density
        if not self._needs_ocr(extracted_text, page_count):
            # No OCR needed - direct extraction successful
            return OcrLoadResult(
                text=extracted_text,
                page_count=page_count,
                char_count=char_count,
                chars_per_page=chars_per_page,
                ocr_used=False,
                ocr_failed=False,
                ocr_method=None,
                error_reason=None
            )

        # OCR is needed
        logger.info(f"Low text density detected, attempting OCR: {file_path}")

        try:
            ocr_text_parts = self._ocr_extract(file_path)
            ocr_text = "\n\n".join(ocr_text_parts)

            if ocr_text.strip():
                # OCR succeeded
                ocr_char_count = len(ocr_text.strip())
                ocr_chars_per_page = ocr_char_count / page_count if page_count > 0 else 0
                return OcrLoadResult(
                    text=ocr_text,
                    page_count=page_count,
                    char_count=ocr_char_count,
                    chars_per_page=ocr_chars_per_page,
                    ocr_used=True,
                    ocr_failed=False,
                    ocr_method="ocrmypdf",
                    error_reason=None
                )
            else:
                # OCR returned empty - treat as failure
                return OcrLoadResult(
                    text=extracted_text,
                    page_count=page_count,
                    char_count=char_count,
                    chars_per_page=chars_per_page,
                    ocr_used=True,
                    ocr_failed=True,
                    ocr_method="ocrmypdf",
                    error_reason="OCR process completed but returned no text"
                )

        except subprocess.TimeoutExpired:
            return OcrLoadResult(
                text=extracted_text,
                page_count=page_count,
                char_count=char_count,
                chars_per_page=chars_per_page,
                ocr_used=True,
                ocr_failed=True,
                ocr_method="ocrmypdf",
                error_reason=f"Timeout after {self.timeout}s"
            )
        except FileNotFoundError:
            return OcrLoadResult(
                text=extracted_text,
                page_count=page_count,
                char_count=char_count,
                chars_per_page=chars_per_page,
                ocr_used=True,
                ocr_failed=True,
                ocr_method="ocrmypdf",
                error_reason="ocrmypdf binary not found (install with: apt install ocrmypdf)"
            )
        except Exception as e:
            return OcrLoadResult(
                text=extracted_text,
                page_count=page_count,
                char_count=char_count,
                chars_per_page=chars_per_page,
                ocr_used=True,
                ocr_failed=True,
                ocr_method="ocrmypdf",
                error_reason=str(e)
            )

    def load(self, file_path: str) -> str:
        """Load PDF and extract text (backward compatible).

        This method maintains backward compatibility by returning only text.
        For rich metadata about the extraction process, use load_with_metadata().

        Args:
            file_path: Path to the PDF file

        Returns:
            Extracted text as string
        """
        return self.load_with_metadata(file_path).text

    def _ocr_extract(self, file_path: str) -> list[str]:
        """Run OCR on PDF and extract text.

        Raises:
            subprocess.TimeoutExpired: If OCR exceeds timeout
            FileNotFoundError: If ocrmypdf binary not found
            Exception: Any other OCR processing errors
        """
        import pdfplumber

        text_parts = []
        tmp_path = None

        try:
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
                tmp_path = tmp.name

            # This can raise TimeoutExpired or FileNotFoundError
            result = subprocess.run(
                ['ocrmypdf', '--skip-text', '--quiet', file_path, tmp_path],
                capture_output=True,
                text=True,
                timeout=self.timeout
            )

            if result.returncode != 0:
                logger.warning(f"OCR failed: {result.stderr}")
                return []

            with pdfplumber.open(tmp_path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        text_parts.append(text)

            return text_parts

        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)

"""PDF loader with OCR fallback for scanned documents"""

import logging
import subprocess
import tempfile
from pathlib import Path

from stache_ai.loaders.base import DocumentLoader

logger = logging.getLogger(__name__)


class OcrPdfLoader(DocumentLoader):
    """PDF loader with OCR fallback for scanned documents

    Requires ocrmypdf system binary: apt install ocrmypdf
    """

    @property
    def extensions(self) -> list[str]:
        return ['pdf']

    @property
    def priority(self) -> int:
        return 10  # Override basic PdfLoader (priority 0)

    def load(self, file_path: str) -> str:
        # Lazy import
        import pdfplumber

        # Try normal extraction first
        text_parts = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    text_parts.append(text)

        # If no text found, try OCR
        if not text_parts:
            logger.info(f"No text in PDF, attempting OCR: {file_path}")
            text_parts = self._ocr_extract(file_path)

        return "\n\n".join(text_parts)

    def _ocr_extract(self, file_path: str) -> list[str]:
        """Run OCR on PDF and extract text"""
        import pdfplumber

        text_parts = []
        tmp_path = None

        try:
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
                tmp_path = tmp.name

            result = subprocess.run(
                ['ocrmypdf', '--skip-text', '--quiet', file_path, tmp_path],
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                logger.warning(f"OCR failed: {result.stderr}")
                return []

            with pdfplumber.open(tmp_path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        text_parts.append(text)

        except FileNotFoundError:
            logger.warning(
                "ocrmypdf not installed (install with: apt install ocrmypdf), "
                "skipping OCR"
            )
        except Exception as e:
            logger.warning(f"OCR error: {e}")
        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)

        return text_parts

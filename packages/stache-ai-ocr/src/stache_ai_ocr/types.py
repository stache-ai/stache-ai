"""Type definitions for stache-ai-ocr."""

from dataclasses import dataclass, asdict


@dataclass
class OcrLoadResult:
    """Result of OCR-enhanced PDF loading.

    This dataclass provides essential metadata about the OCR process.

    Attributes:
        text: Extracted text content from the PDF. Empty string if extraction
            completely failed.
        page_count: Number of pages in the PDF document.
        ocr_used: Whether OCR was applied to extract text. True if the PDF
            was detected as scanned (low text density) and OCR was performed.
        ocr_failed: Whether the OCR process failed. Default False. If True,
            the text field may contain partial results from direct extraction.
        ocr_method: Name of OCR method used (e.g., "ocrmypdf", "tesseract").
            None if OCR was not used or failed before method selection.
        error_reason: Human-readable reason why OCR failed. None if OCR succeeded
            or was not attempted. Examples: "Timeout after 300s", "ocrmypdf binary
            not found", "Unsupported PDF encryption".

    Example:
        >>> result = OcrLoadResult(
        ...     text="Extracted content",
        ...     page_count=5,
        ...     ocr_used=True,
        ...     ocr_method="ocrmypdf"
        ... )
        >>> result.to_dict()
        {
            'text': 'Extracted content',
            'page_count': 5,
            'ocr_used': True,
            'ocr_failed': False,
            'ocr_method': 'ocrmypdf',
            'error_reason': None
        }
    """

    text: str
    page_count: int
    ocr_used: bool
    ocr_failed: bool = False
    ocr_method: str | None = None
    error_reason: str | None = None

    def to_dict(self) -> dict:
        """Convert result to dictionary for serialization.

        Returns:
            Dictionary with all fields. Useful for JSON serialization,
            logging, or passing to external systems.
        """
        return asdict(self)

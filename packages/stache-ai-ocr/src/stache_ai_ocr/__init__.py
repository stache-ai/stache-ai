"""OCR support for Stache AI document loaders"""

from .types import OcrLoadResult
from .loaders import OcrPdfLoader

__version__ = "0.1.1"
__all__ = ["OcrLoadResult", "OcrPdfLoader"]

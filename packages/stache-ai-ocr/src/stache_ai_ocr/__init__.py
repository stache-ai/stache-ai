"""OCR support for Stache AI document loaders"""

from .types import OcrLoadResult
from .loaders import OcrPdfLoader

try:
    from importlib.metadata import version
    __version__ = version("stache-ai-ocr")
except Exception:
    __version__ = "0.1.3"  # Fallback for development
__all__ = ["OcrLoadResult", "OcrPdfLoader"]

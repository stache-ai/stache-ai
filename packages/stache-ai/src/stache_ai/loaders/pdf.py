"""PDF document loader"""

from .base import DocumentLoader


class PdfLoader(DocumentLoader):
    """Basic PDF loader using pdfplumber (no OCR)"""

    @property
    def extensions(self) -> list[str]:
        return ['pdf']

    def load(self, file_path: str) -> str:
        # Lazy import - only fails if this loader is actually used
        import pdfplumber

        text_parts = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    text_parts.append(text)

        return "\n\n".join(text_parts)

"""DOCX (Word) document loader"""

from stache_ai.loaders.base import DocumentLoader


class DocxLoader(DocumentLoader):
    """Loader for Microsoft Word (.docx) documents"""

    @property
    def extensions(self) -> list[str]:
        return ['docx']

    def load(self, file_path: str) -> str:
        # Lazy import
        from docx import Document

        doc = Document(file_path)
        text_parts = [para.text for para in doc.paragraphs if para.text.strip()]

        return "\n\n".join(text_parts)

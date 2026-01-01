"""Text and markdown document loader"""

from .base import DocumentLoader


class TextLoader(DocumentLoader):
    """Loader for plain text and markdown files"""

    @property
    def extensions(self) -> list[str]:
        return ['txt', 'md']

    def load(self, file_path: str) -> str:
        with open(file_path, encoding='utf-8') as f:
            return f.read()

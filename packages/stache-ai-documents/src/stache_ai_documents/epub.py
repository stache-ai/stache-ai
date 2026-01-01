"""EPUB document loader"""

from stache_ai.loaders.base import DocumentLoader


class EpubLoader(DocumentLoader):
    """Loader for EPUB eBook files"""

    @property
    def extensions(self) -> list[str]:
        return ['epub']

    def load(self, file_path: str) -> str:
        # Lazy imports
        import ebooklib
        from bs4 import BeautifulSoup
        from ebooklib import epub

        book = epub.read_epub(file_path)
        text_parts = []

        for item in book.get_items():
            if item.get_type() == ebooklib.ITEM_DOCUMENT:
                soup = BeautifulSoup(item.get_content(), 'html.parser')
                text = soup.get_text()
                if text.strip():
                    text_parts.append(text)

        return "\n\n".join(text_parts)

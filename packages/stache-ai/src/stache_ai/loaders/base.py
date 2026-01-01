"""Base class for document loaders"""

from abc import ABC, abstractmethod


class DocumentLoader(ABC):
    """Base class for document loaders

    All optional dependencies MUST be imported inside methods, not at module level.
    This ensures loaders with missing dependencies are silently skipped during discovery.
    """

    @property
    @abstractmethod
    def extensions(self) -> list[str]:
        """File extensions this loader handles (without dots, lowercase)

        Use canonical forms only. Extension aliases are handled by the factory.
        Example: return ['md'] not ['md', 'markdown']
        """
        pass

    @abstractmethod
    def load(self, file_path: str) -> str:
        """Load document and extract text

        Args:
            file_path: Path to the document file

        Returns:
            Extracted text content

        Raises:
            ValueError: If file cannot be loaded
            ImportError: If required dependency is missing
        """
        pass

    @property
    def priority(self) -> int:
        """Priority for extension conflicts (higher wins)

        Default: 0 (built-in loaders)
        Override packages should use priority > 0 (e.g., 10 for OCR)

        Tie-breaking: When priorities are equal, first-discovered wins.
        """
        return 0

    @property
    def name(self) -> str:
        """Loader name for logging/debugging"""
        return self.__class__.__name__

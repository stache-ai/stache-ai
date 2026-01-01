"""Document loader factory with entry point discovery

Uses the centralized plugin_loader for consistency with provider patterns.
"""

import logging
from pathlib import Path

from stache_ai.providers import plugin_loader

from .base import DocumentLoader

logger = logging.getLogger(__name__)

# Extension aliases - normalized to canonical form
EXTENSION_ALIASES = {
    'markdown': 'md',
    'htm': 'html',
    'jpeg': 'jpg',
}


class DocumentLoaderFactory:
    """Factory for document loaders with entry point discovery

    Uses the centralized plugin_loader pattern for consistency.
    Loaders are discovered via 'stache.loader' entry point group.
    """

    # Cache: extension -> loader instance (not class)
    _loaders: dict[str, DocumentLoader] = {}
    _discovered: bool = False

    @classmethod
    def load_document(cls, file_path: str, filename: str | None = None) -> str:
        """Load document using appropriate loader

        Args:
            file_path: Path to the document file
            filename: Original filename for extension detection (optional)

        Returns:
            Extracted text content

        Raises:
            ValueError: If no loader available for file type
        """
        cls._ensure_discovered()
        ext = cls._get_extension(file_path, filename)
        loader = cls._loaders.get(ext)

        if not loader:
            available = ', '.join(sorted(cls._loaders.keys()))
            raise ValueError(
                f"No loader for extension: .{ext}. "
                f"Available: {available or 'none'}"
            )

        logger.info(f"Loading {filename or file_path} with {loader.name}")
        return loader.load(file_path)

    @classmethod
    def _ensure_discovered(cls):
        """Discover loaders from entry points if not already done"""
        if cls._discovered:
            return

        # Use centralized plugin_loader for discovery
        loader_classes = plugin_loader.get_providers('loader')

        for name, loader_class in loader_classes.items():
            try:
                loader = loader_class()
                cls._register_loader(loader)
            except Exception as e:
                logger.warning(f"Failed to instantiate loader {name}: {e}")

        cls._discovered = True
        logger.info(f"Discovered {len(cls._loaders)} document loaders for extensions: {sorted(cls._loaders.keys())}")

    @classmethod
    def _register_loader(cls, loader: DocumentLoader):
        """Register a loader for its extensions"""
        for ext in loader.extensions:
            ext = ext.lower()
            existing = cls._loaders.get(ext)
            if not existing or loader.priority > existing.priority:
                cls._loaders[ext] = loader
                logger.debug(
                    f"Registered {loader.name} for .{ext} "
                    f"(priority={loader.priority})"
                )

    @classmethod
    def _get_extension(cls, file_path: str, filename: str | None) -> str:
        """Extract and normalize file extension"""
        name = filename or Path(file_path).name
        ext = name.lower().rsplit('.', 1)[-1] if '.' in name else ''
        # Apply aliases
        return EXTENSION_ALIASES.get(ext, ext)

    @classmethod
    def get_supported_extensions(cls) -> list[str]:
        """Get list of supported file extensions"""
        cls._ensure_discovered()
        return sorted(cls._loaders.keys())

    @classmethod
    def get_loader_info(cls) -> dict[str, str]:
        """Get mapping of extensions to loader names (for diagnostics)"""
        cls._ensure_discovered()
        return {ext: loader.name for ext, loader in cls._loaders.items()}

    @classmethod
    def register(cls, loader: DocumentLoader):
        """Manual registration for testing

        Manually registered loaders are NOT overwritten by discovery.
        Call this AFTER reset() but BEFORE any load_document() calls.
        """
        cls._register_loader(loader)

    @classmethod
    def reset(cls):
        """Reset factory state (for testing)

        Clears all cached loaders and marks discovery as not done.
        """
        cls._loaders.clear()
        cls._discovered = False
        logger.debug("DocumentLoaderFactory cache reset")

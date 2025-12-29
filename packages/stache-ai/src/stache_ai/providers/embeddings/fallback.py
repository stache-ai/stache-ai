"""Fallback embedding provider - tries primary, falls back to secondary"""

import logging

from stache_ai.config import Settings
from stache_ai.providers.base import EmbeddingProvider
from stache_ai.providers.factories import EmbeddingProviderFactory

logger = logging.getLogger(__name__)


class FallbackEmbeddingProvider(EmbeddingProvider):
    """
    Fallback embedding provider that tries primary provider first,
    then falls back to secondary if primary fails.

    IMPORTANT: Both providers MUST have the same embedding dimensions!
    Mixing dimensions will corrupt your vector database.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._primary = None
        self._secondary = None
        self._primary_name = settings.embedding_fallback_primary
        self._secondary_name = settings.embedding_fallback_secondary

        # Validate dimensions match
        self._validate_dimensions()

    def _validate_dimensions(self):
        """Ensure primary and secondary have matching dimensions"""
        # Get dimension info from config
        dimension_map = {
            "openai": {"text-embedding-3-small": 1536, "text-embedding-3-large": 3072},
            "cohere": {"embed-english-v3.0": 1024},
            "ollama": {
                "mxbai-embed-large": 1024,
                "nomic-embed-text": 768,
                "all-minilm": 384,
            },
            "mixedbread": {
                "mxbai-embed-large-v1": 1024,
                "deepset-mxbai-embed-de-large-v1": 1024,
                "mxbai-embed-2d-large-v1": 1024,
            },
        }

        # Get the model for each provider
        def get_model_for_provider(provider_name):
            if provider_name == "ollama":
                return self.settings.ollama_embedding_model
            elif provider_name == "mixedbread":
                return self.settings.mixedbread_model
            elif provider_name == "openai":
                return "text-embedding-3-small"
            elif provider_name == "cohere":
                return "embed-english-v3.0"
            return self.settings.get_embedding_model()

        primary_model = get_model_for_provider(self._primary_name)
        secondary_model = get_model_for_provider(self._secondary_name)

        primary_dims = dimension_map.get(self._primary_name, {})
        secondary_dims = dimension_map.get(self._secondary_name, {})

        primary_dim = primary_dims.get(primary_model, self.settings.embedding_dimension)
        secondary_dim = secondary_dims.get(secondary_model, self.settings.embedding_dimension)

        if primary_dim != secondary_dim:
            logger.warning(
                f"Embedding dimension mismatch! Primary ({self._primary_name}/{primary_model}): {primary_dim}, "
                f"Secondary ({self._secondary_name}/{secondary_model}): {secondary_dim}. "
                f"This may cause issues with your vector database."
            )
        else:
            logger.info(
                f"Embedding fallback configured: {self._primary_name}/{primary_model} -> "
                f"{self._secondary_name}/{secondary_model} (both {primary_dim} dimensions)"
            )

    @property
    def primary(self) -> EmbeddingProvider:
        """Lazy-load primary provider"""
        if self._primary is None:
            logger.info(f"Initializing primary embedding provider: {self._primary_name}")
            # Temporarily change the setting to create the right provider
            original = self.settings.embedding_provider
            self.settings.embedding_provider = self._primary_name
            try:
                self._primary = EmbeddingProviderFactory.create(self.settings)
            finally:
                self.settings.embedding_provider = original
        return self._primary

    @property
    def secondary(self) -> EmbeddingProvider:
        """Lazy-load secondary provider"""
        if self._secondary is None:
            logger.info(f"Initializing secondary embedding provider: {self._secondary_name}")
            original = self.settings.embedding_provider
            self.settings.embedding_provider = self._secondary_name
            try:
                self._secondary = EmbeddingProviderFactory.create(self.settings)
            finally:
                self.settings.embedding_provider = original
        return self._secondary

    def embed(self, text: str) -> list[float]:
        """Generate embedding, with fallback"""
        try:
            return self.primary.embed(text)
        except Exception as e:
            logger.warning(f"Primary embedding provider failed: {e}, trying secondary")
            return self.secondary.embed(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for batch, with fallback"""
        try:
            return self.primary.embed_batch(texts)
        except Exception as e:
            logger.warning(f"Primary embedding provider failed: {e}, trying secondary")
            return self.secondary.embed_batch(texts)

    def get_dimensions(self) -> int:
        """Get embedding dimensions (from primary)"""
        return self.primary.get_dimensions()

    def get_name(self) -> str:
        """Get provider name"""
        return f"fallback({self._primary_name}->{self._secondary_name})"

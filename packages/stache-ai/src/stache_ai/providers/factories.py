"""Provider factories - Factory pattern with entry point discovery

All factories use the plugin_loader to discover providers via entry points.
This provides a unified mechanism for both built-in and external providers.
"""

import logging

from stache_ai.config import Settings

from . import plugin_loader
from .base import (
    DocumentIndexProvider,
    EmbeddingProvider,
    LLMProvider,
    NamespaceProvider,
    VectorDBProvider,
)
from .reranker.base import RerankerProvider

logger = logging.getLogger(__name__)


class EmbeddingProviderFactory:
    """Factory for creating embedding providers

    Providers are discovered via entry points in the 'stache.embeddings' group.

    Available providers (when dependencies installed):
        - openai: OpenAI embeddings
        - bedrock: AWS Bedrock (Cohere/Titan)
        - cohere: Cohere embeddings
        - ollama: Local Ollama embeddings
        - mixedbread: Mixedbread AI embeddings
        - fallback: Simple hash-based fallback
    """

    @classmethod
    def create(cls, settings: Settings) -> EmbeddingProvider:
        """Create embedding provider based on settings

        Args:
            settings: Application settings with embedding_provider configured

        Returns:
            Embedding provider instance

        Raises:
            ValueError: If provider not found or dependencies missing
        """
        provider_name = settings.embedding_provider
        provider_class = plugin_loader.get_provider_class('embeddings', provider_name)

        if not provider_class:
            available = ', '.join(cls.get_available_providers())
            raise ValueError(
                f"Unknown embedding provider: {provider_name}. "
                f"Available: {available or 'none (check dependencies)'}"
            )

        logger.info(f"Creating embedding provider: {provider_name}")
        return provider_class(settings)

    @classmethod
    def get_available_providers(cls) -> list[str]:
        """Get list of available embedding providers"""
        return plugin_loader.get_available_providers('embeddings')

    @classmethod
    def register(cls, name: str, provider_class: type[EmbeddingProvider]) -> None:
        """Manually register a provider (for testing)"""
        plugin_loader.register_provider('embeddings', name, provider_class)


class LLMProviderFactory:
    """Factory for creating LLM providers

    Providers are discovered via entry points in the 'stache.llm' group.

    Available providers (when dependencies installed):
        - anthropic: Anthropic Claude
        - openai: OpenAI GPT
        - bedrock: AWS Bedrock (Claude/Llama)
        - ollama: Local Ollama models
        - fallback: Echo fallback for testing
    """

    @classmethod
    def create(cls, settings: Settings) -> LLMProvider:
        """Create LLM provider based on settings

        Args:
            settings: Application settings with llm_provider configured

        Returns:
            LLM provider instance

        Raises:
            ValueError: If provider not found or dependencies missing
        """
        provider_name = settings.llm_provider
        provider_class = plugin_loader.get_provider_class('llm', provider_name)

        if not provider_class:
            available = ', '.join(cls.get_available_providers())
            raise ValueError(
                f"Unknown LLM provider: {provider_name}. "
                f"Available: {available or 'none (check dependencies)'}"
            )

        logger.info(f"Creating LLM provider: {provider_name}")
        return provider_class(settings)

    @classmethod
    def get_available_providers(cls) -> list[str]:
        """Get list of available LLM providers"""
        return plugin_loader.get_available_providers('llm')

    @classmethod
    def register(cls, name: str, provider_class: type[LLMProvider]) -> None:
        """Manually register a provider (for testing)"""
        plugin_loader.register_provider('llm', name, provider_class)


class VectorDBProviderFactory:
    """Factory for creating vector database providers

    Providers are discovered via entry points in the 'stache.vectordb' group.

    Available providers (when dependencies installed):
        - qdrant: Qdrant vector database
        - pinecone: Pinecone managed vector DB
        - chroma: ChromaDB
        - s3vectors: AWS S3 Vectors

    Note: s3vectors uses S3VectorsProviderFactory for multi-index support.
    """

    @classmethod
    def create(cls, settings: Settings) -> VectorDBProvider:
        """Create vector DB provider based on settings

        Args:
            settings: Application settings with vectordb_provider configured

        Returns:
            Vector DB provider instance

        Raises:
            ValueError: If provider not found or dependencies missing
        """
        provider_name = settings.vectordb_provider

        # Special handling for s3vectors multi-index support
        if provider_name == "s3vectors":
            return S3VectorsProviderFactory.get_provider(settings, "documents")

        provider_class = plugin_loader.get_provider_class('vectordb', provider_name)

        if not provider_class:
            available = ', '.join(cls.get_available_providers())
            raise ValueError(
                f"Unknown vector DB provider: {provider_name}. "
                f"Available: {available or 'none (check dependencies)'}"
            )

        logger.info(f"Creating vector DB provider: {provider_name}")
        return provider_class(settings)

    @classmethod
    def get_available_providers(cls) -> list[str]:
        """Get list of available vector DB providers"""
        return plugin_loader.get_available_providers('vectordb')

    @classmethod
    def register(cls, name: str, provider_class: type[VectorDBProvider]) -> None:
        """Manually register a provider (for testing)"""
        plugin_loader.register_provider('vectordb', name, provider_class)


class S3VectorsProviderFactory:
    """Factory for creating S3Vectors provider instances with multiple indexes

    Implements singleton caching per index_type to support separate indexes for
    documents, summaries, and insights. Each index_type gets its own cached
    provider instance.

    Note: This factory exists because S3Vectors requires different index names
    for different content types, while other vector DBs use namespaces within
    a single index.

    **Thread Safety Warning**: The _instances class variable is not thread-safe.
    In multi-threaded environments, consider adding synchronization or using
    thread-local storage. This is typically not an issue in Lambda (single-threaded)
    but may affect local development or future deployment changes.
    """

    _instances: dict[str, VectorDBProvider] = {}

    @classmethod
    def get_provider(cls, settings: Settings, index_type: str) -> VectorDBProvider:
        """Get or create a cached S3VectorsProvider for the specified index type

        Args:
            settings: Application settings
            index_type: Type of index ('documents', 'summaries', 'insights')

        Returns:
            Cached S3VectorsProvider instance for this index type
        """
        if index_type in cls._instances:
            logger.debug(f"Returning cached S3VectorsProvider for index_type={index_type}")
            return cls._instances[index_type]

        index_name = cls._get_index_name(settings, index_type)

        # Get the S3VectorsProvider class via entry points
        provider_class = plugin_loader.get_provider_class('vectordb', 's3vectors')
        if not provider_class:
            raise ValueError(
                "s3vectors provider not available. "
                "Ensure boto3 is installed and the package is properly installed."
            )

        provider = provider_class(settings, index_name=index_name)
        cls._instances[index_type] = provider
        logger.info(f"Created and cached S3VectorsProvider for index_type={index_type}")

        return provider

    @classmethod
    def _get_index_name(cls, settings: Settings, index_type: str) -> str:
        """Map index_type to setting name with backward compatibility fallback

        Args:
            settings: Application settings
            index_type: Type of index ('documents', 'summaries', 'insights')

        Returns:
            Index name to use for this type

        Raises:
            ValueError: If no valid index name can be determined
        """
        # Try to get index name from new specific settings first
        if index_type == "documents":
            if settings.s3vectors_documents_index:
                return settings.s3vectors_documents_index
        elif index_type == "summaries":
            if settings.s3vectors_summaries_index:
                return settings.s3vectors_summaries_index
        elif index_type == "insights":
            if settings.s3vectors_insights_index:
                return settings.s3vectors_insights_index
        else:
            raise ValueError(f"Unknown index_type: {index_type}")

        # Fallback to deprecated s3vectors_index for backward compatibility
        if settings.s3vectors_index:
            logger.warning(
                f"Using deprecated s3vectors_index setting for {index_type} index. "
                f"Please set S3VECTORS_{index_type.upper()}_INDEX environment variable."
            )
            return settings.s3vectors_index

        raise ValueError(
            f"No index configured for index_type={index_type}. "
            f"Set S3VECTORS_{index_type.upper()}_INDEX environment variable."
        )

    @classmethod
    def reset(cls) -> None:
        """Clear all cached provider instances (for testing)"""
        cls._instances.clear()
        logger.info("S3VectorsProviderFactory cache cleared")


class NamespaceProviderFactory:
    """Factory for creating namespace registry providers

    Providers are discovered via entry points in the 'stache.namespace' group.

    Available providers (when dependencies installed):
        - sqlite: Local SQLite database
        - redis: Redis key-value store
        - dynamodb: AWS DynamoDB
        - mongodb: MongoDB
    """

    @classmethod
    def create(cls, settings: Settings) -> NamespaceProvider:
        """Create namespace provider based on settings

        Args:
            settings: Application settings with namespace_provider configured

        Returns:
            Namespace provider instance

        Raises:
            ValueError: If provider not found or dependencies missing
        """
        provider_name = settings.namespace_provider
        provider_class = plugin_loader.get_provider_class('namespace', provider_name)

        if not provider_class:
            available = ', '.join(cls.get_available_providers())
            raise ValueError(
                f"Unknown namespace provider: {provider_name}. "
                f"Available: {available or 'none (check dependencies)'}"
            )

        logger.info(f"Creating namespace provider: {provider_name}")
        return provider_class(settings)

    @classmethod
    def get_available_providers(cls) -> list[str]:
        """Get list of available namespace providers"""
        return plugin_loader.get_available_providers('namespace')

    @classmethod
    def register(cls, name: str, provider_class: type[NamespaceProvider]) -> None:
        """Manually register a provider (for testing)"""
        plugin_loader.register_provider('namespace', name, provider_class)


class RerankerProviderFactory:
    """Factory for creating reranker providers

    Providers are discovered via entry points in the 'stache.reranker' group.

    Available providers (when dependencies installed):
        - simple: Simple local reranker (no external deps)
        - cohere: Cohere Rerank API
        - ollama: Local Ollama for reranking

    Special handling:
        - 'none' disables reranking and returns None
        - Cohere falls back to simple if API key not set
    """

    @classmethod
    def create(cls, settings: Settings) -> RerankerProvider | None:
        """Create reranker provider based on settings

        Args:
            settings: Application settings with reranker_provider configured

        Returns:
            Reranker provider instance, or None if disabled

        Raises:
            ValueError: If provider not found or dependencies missing
        """
        provider_name = settings.reranker_provider

        # Disable reranking
        if provider_name == "none":
            logger.info("Reranking disabled")
            return None

        provider_class = plugin_loader.get_provider_class('reranker', provider_name)

        if not provider_class:
            available = ', '.join(cls.get_available_providers())
            raise ValueError(
                f"Unknown reranker provider: {provider_name}. "
                f"Available: {available or 'none (check dependencies)'}"
            )

        # Special handling for different reranker types
        if provider_name == "simple":
            logger.info("Creating simple local reranker")
            return provider_class(dedupe_threshold=settings.reranker_dedupe_threshold)

        if provider_name == "ollama":
            logger.info(f"Creating Ollama reranker with model {settings.reranker_model}")
            return provider_class(config=settings, model=settings.reranker_model)

        if provider_name == "cohere":
            if not settings.cohere_api_key:
                logger.warning("Cohere API key not set, falling back to simple reranker")
                simple_class = plugin_loader.get_provider_class('reranker', 'simple')
                if simple_class:
                    return simple_class(dedupe_threshold=settings.reranker_dedupe_threshold)
                raise ValueError("Cohere API key not set and simple reranker not available")
            logger.info("Creating Cohere reranker")
            return provider_class(api_key=settings.cohere_api_key)

        # Default: pass settings to constructor
        logger.info(f"Creating reranker provider: {provider_name}")
        return provider_class(settings)

    @classmethod
    def get_available_providers(cls) -> list[str]:
        """Get list of available reranker providers"""
        return plugin_loader.get_available_providers('reranker')

    @classmethod
    def register(cls, name: str, provider_class: type[RerankerProvider]) -> None:
        """Manually register a provider (for testing)"""
        plugin_loader.register_provider('reranker', name, provider_class)


class DocumentIndexProviderFactory:
    """Factory for creating document index providers

    Providers are discovered via entry points in the 'stache.document_index' group.

    Available providers (when dependencies installed):
        - dynamodb: AWS DynamoDB
        - mongodb: MongoDB
    """

    @classmethod
    def create(cls, settings: Settings) -> DocumentIndexProvider:
        """Create document index provider based on settings

        Args:
            settings: Application settings with document_index_provider configured

        Returns:
            Document index provider instance

        Raises:
            ValueError: If provider not found or dependencies missing
        """
        provider_name = settings.document_index_provider
        provider_class = plugin_loader.get_provider_class('document_index', provider_name)

        if not provider_class:
            available = ', '.join(cls.get_available_providers())
            raise ValueError(
                f"Unknown document index provider: {provider_name}. "
                f"Available: {available or 'none (check dependencies)'}"
            )

        logger.info(f"Creating document index provider: {provider_name}")
        return provider_class(settings)

    @classmethod
    def get_available_providers(cls) -> list[str]:
        """Get list of available document index providers"""
        return plugin_loader.get_available_providers('document_index')

    @classmethod
    def register(cls, name: str, provider_class: type[DocumentIndexProvider]) -> None:
        """Manually register a provider (for testing)"""
        plugin_loader.register_provider('document_index', name, provider_class)

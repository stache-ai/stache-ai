"""Base provider interfaces - Abstract base classes for all providers"""

import builtins
from abc import ABC, abstractmethod
from typing import Any


class EmbeddingProvider(ABC):
    """Abstract base class for embedding providers"""

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """
        Generate embedding for a single text

        Args:
            text: Input text to embed

        Returns:
            List of floats representing the embedding vector
        """
        pass

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for multiple texts

        Args:
            texts: List of input texts

        Returns:
            List of embedding vectors
        """
        pass

    @abstractmethod
    def get_dimensions(self) -> int:
        """
        Get the dimension size of embeddings

        Returns:
            Number of dimensions in embedding vectors
        """
        pass

    def embed_query(self, text: str) -> list[float]:
        """
        Generate embedding for a search query.

        Some embedding models (e.g., Cohere) use different parameters for
        queries vs documents. Override this method if your provider needs
        different behavior for query embeddings.

        Args:
            text: Query text to embed

        Returns:
            List of floats representing the embedding vector
        """
        return self.embed(text)

    def get_name(self) -> str:
        """Get provider name"""
        return self.__class__.__name__


class ModelInfo:
    """Information about an available model"""

    def __init__(
        self,
        id: str,
        name: str,
        provider: str,
        tier: str = "balanced",
        description: str = ""
    ):
        self.id = id
        self.name = name
        self.provider = provider
        self.tier = tier  # "fast", "balanced", "premium"
        self.description = description

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "provider": self.provider,
            "tier": self.tier,
            "description": self.description
        }


class LLMProvider(ABC):
    """Abstract base class for LLM providers"""

    @abstractmethod
    def generate(self, prompt: str, **kwargs) -> str:
        """
        Generate text from a prompt

        Args:
            prompt: Input prompt
            **kwargs: Provider-specific parameters

        Returns:
            Generated text
        """
        pass

    @abstractmethod
    def generate_with_context(
        self,
        query: str,
        context: list[dict[str, Any]],
        **kwargs
    ) -> str:
        """
        Generate answer given query and context

        Args:
            query: User query
            context: List of context chunks with metadata
            **kwargs: Provider-specific parameters

        Returns:
            Generated answer
        """
        pass

    def get_available_models(self) -> list[ModelInfo]:
        """
        Get list of models available for this provider.

        Returns:
            List of ModelInfo objects describing available models.
            Empty list means no model selection is available (use default only).
        """
        return []

    def get_default_model(self) -> str:
        """
        Get the default model ID for this provider.

        Returns:
            Model ID string
        """
        return ""

    def generate_with_model(
        self,
        prompt: str,
        model_id: str,
        **kwargs
    ) -> str:
        """
        Generate text using a specific model.

        Override this method if your provider supports model selection.
        Default implementation falls back to generate() with default model.

        Args:
            prompt: Input prompt
            model_id: Model ID to use
            **kwargs: Provider-specific parameters

        Returns:
            Generated text
        """
        # Default: ignore model_id and use configured model
        return self.generate(prompt, **kwargs)

    def generate_with_context_and_model(
        self,
        query: str,
        context: list[dict[str, Any]],
        model_id: str,
        **kwargs
    ) -> str:
        """
        Generate answer with context using a specific model.

        Override this method if your provider supports model selection.
        Default implementation falls back to generate_with_context() with default model.

        Args:
            query: User query
            context: List of context chunks with metadata
            model_id: Model ID to use
            **kwargs: Provider-specific parameters

        Returns:
            Generated answer
        """
        # Default: ignore model_id and use configured model
        return self.generate_with_context(query, context, **kwargs)

    def get_name(self) -> str:
        """Get provider name"""
        return self.__class__.__name__


class NamespaceProvider(ABC):
    """Abstract base class for namespace registry providers"""

    @abstractmethod
    def create(
        self,
        id: str,
        name: str,
        description: str = "",
        parent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        filter_keys: list[str] | None = None
    ) -> dict[str, Any]:
        """
        Create a new namespace

        Args:
            id: Unique namespace ID (slug, e.g., 'mba/finance/corporate-finance')
            name: Display name (e.g., 'Corporate Finance')
            description: What belongs in this namespace
            parent_id: Parent namespace ID for hierarchy
            metadata: Additional metadata (tags, icon, color, etc.)
            filter_keys: Optional list of metadata keys that can be used for filtering
                        searches in this namespace (e.g., ['source', 'date', 'author']).
                        These are informational only and not enforced on search queries.

        Returns:
            Created namespace record including filter_keys (defaults to [])
        """
        pass

    @abstractmethod
    def get(self, id: str) -> dict[str, Any] | None:
        """
        Get a namespace by ID

        Args:
            id: Namespace ID

        Returns:
            Namespace record or None if not found
        """
        pass

    @abstractmethod
    def list(
        self,
        parent_id: str | None = None,
        include_children: bool = False
    ) -> list[dict[str, Any]]:
        """
        List namespaces

        Args:
            parent_id: Filter by parent (None for root namespaces)
            include_children: If True, recursively include children

        Returns:
            List of namespace records
        """
        pass

    @abstractmethod
    def update(
        self,
        id: str,
        name: str | None = None,
        description: str | None = None,
        parent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        filter_keys: builtins.list[str] | None = None
    ) -> dict[str, Any] | None:
        """
        Update a namespace

        Args:
            id: Namespace ID to update
            name: New display name (if provided)
            description: New description (if provided)
            parent_id: New parent ID (if provided)
            metadata: New metadata (merged with existing if provided)
            filter_keys: Complete replacement list of filter keys (if provided).
                        Unlike metadata which merges, filter_keys replaces entirely.

        Returns:
            Updated namespace record or None if not found
        """
        pass

    @abstractmethod
    def delete(self, id: str, cascade: bool = False) -> bool:
        """
        Delete a namespace

        Args:
            id: Namespace ID to delete
            cascade: If True, delete children; if False, fail if children exist

        Returns:
            True if deleted, False if not found
        """
        pass

    @abstractmethod
    def get_tree(self, root_id: str | None = None) -> builtins.list[dict[str, Any]]:
        """
        Get namespace hierarchy as a tree

        Args:
            root_id: Start from this namespace (None for full tree)

        Returns:
            List of namespaces with nested 'children' arrays
        """
        pass

    @abstractmethod
    def exists(self, id: str) -> bool:
        """
        Check if a namespace exists

        Args:
            id: Namespace ID

        Returns:
            True if exists
        """
        pass

    def get_name(self) -> str:
        """Get provider name"""
        return self.__class__.__name__


class VectorDBProvider(ABC):
    """Abstract base class for vector database providers"""

    @abstractmethod
    def insert(
        self,
        vectors: list[list[float]],
        texts: list[str],
        metadatas: list[dict[str, Any]] | None = None,
        ids: list[str] | None = None,
        namespace: str | None = None
    ) -> list[str]:
        """
        Insert vectors into the database

        Args:
            vectors: List of embedding vectors
            texts: Corresponding text chunks
            metadatas: Optional metadata for each vector
            ids: Optional IDs for each vector (generated if not provided)
            namespace: Optional namespace for isolation (multi-user/multi-project)

        Returns:
            List of inserted vector IDs
        """
        pass

    @abstractmethod
    def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        filter: dict[str, Any] | None = None,
        namespace: str | None = None
    ) -> list[dict[str, Any]]:
        """
        Search for similar vectors

        Args:
            query_vector: Query embedding vector
            top_k: Number of results to return
            filter: Optional metadata filter
            namespace: Optional namespace to search within

        Returns:
            List of results with text, metadata, and scores
        """
        pass

    @abstractmethod
    def delete(self, ids: list[str], namespace: str | None = None) -> bool:
        """
        Delete vectors by IDs

        Args:
            ids: List of vector IDs to delete
            namespace: Optional namespace to delete from

        Returns:
            True if successful
        """
        pass

    @abstractmethod
    def get_collection_info(self) -> dict[str, Any]:
        """
        Get information about the collection

        Returns:
            Dictionary with collection stats
        """
        pass

    def delete_by_metadata(self, field: str, value: str, namespace: str | None = None) -> dict[str, Any]:
        """
        Delete vectors by metadata field value

        Args:
            field: Metadata field name (e.g., 'filename')
            value: Value to match
            namespace: Optional namespace filter

        Returns:
            Dictionary with deleted count and IDs
        """
        raise NotImplementedError("delete_by_metadata not implemented for this provider")

    def search_summaries(
        self,
        query_vector: list[float],
        top_k: int = 10,
        namespace: str | None = None
    ) -> list[dict[str, Any]]:
        """
        Search document summaries (for document discovery)

        Unlike search() which excludes summaries, this method ONLY searches
        document summaries (_type=document_summary).

        Args:
            query_vector: Query embedding vector
            top_k: Number of results to return
            namespace: Optional namespace to search within (supports wildcards)

        Returns:
            List of results with document metadata and scores
        """
        raise NotImplementedError("search_summaries not implemented for this provider")

    def count_by_filter(self, filter: dict[str, Any]) -> int:
        """
        Count vectors matching a filter

        Args:
            filter: Dictionary of field:value pairs to match

        Returns:
            Count of matching vectors
        """
        raise NotImplementedError("count_by_filter not implemented for this provider")

    def list_by_filter(
        self,
        filter: dict[str, Any],
        fields: list[str] | None = None,
        limit: int = 1000
    ) -> list[dict[str, Any]]:
        """
        List vectors matching a filter with their metadata

        Args:
            filter: Dictionary of field:value pairs to match
            fields: Optional list of metadata fields to return (None = all)
            limit: Maximum number of vectors to return

        Returns:
            List of dictionaries with vector metadata
        """
        raise NotImplementedError("list_by_filter not implemented for this provider")

    def get_by_ids(
        self,
        ids: list[str],
        fields: list[str] | None = None,
        namespace: str | None = None
    ) -> list[dict[str, Any]]:
        """Retrieve vectors by IDs with their metadata

        Args:
            ids: List of vector IDs to retrieve
            fields: Optional list of metadata fields to return (None = all)
            namespace: Optional namespace filter (validation only)

        Returns:
            List of dictionaries with vector metadata and text
            Format: [{"id": str, "text": str, **metadata}, ...]
        """
        raise NotImplementedError("get_by_ids not implemented for this provider")

    def get_name(self) -> str:
        """Get provider name"""
        return self.__class__.__name__

    @property
    def capabilities(self) -> set[str]:
        """Return set of supported operations

        Override this property in provider implementations to declare
        which optional operations are supported.

        Returns:
            Set of capability strings. Common capabilities:
            - "metadata_scan": Can scan full collection with metadata filters
            - "server_side_filtering": Supports server-side metadata filtering
            - "export": Supports database export
        """
        return set()


class DocumentIndexProvider(ABC):
    """Abstract base class for document metadata index providers

    DocumentIndexProvider implementations manage document-level metadata
    independently from vector embeddings. This enables efficient metadata-only
    queries, filtering by namespace, and document discovery without requiring
    a full vector search.

    The document index stores:
    - Document metadata (filename, namespace, creation date)
    - Document summaries and summaries' embedding IDs
    - List of chunk IDs that belong to the document
    - Custom metadata and document structure (headings)

    This is complementary to VectorDBProvider which stores the actual embeddings
    and chunk text. Together they enable the dual-write pattern.
    """

    @abstractmethod
    def create_document(
        self,
        doc_id: str,
        filename: str,
        namespace: str,
        chunk_ids: list[str],
        summary: str | None = None,
        summary_embedding_id: str | None = None,
        headings: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        file_type: str | None = None,
        file_size: int | None = None
    ) -> dict[str, Any]:
        """
        Create a new document index entry

        Args:
            doc_id: Unique document identifier (typically UUID)
            filename: Original filename of the document
            namespace: Namespace/partition for the document
            chunk_ids: List of chunk IDs from vector database
            summary: Optional AI-generated summary of document
            summary_embedding_id: ID of the summary embedding in vector DB
            headings: Optional list of extracted headings from document
            metadata: Optional custom metadata dictionary
            file_type: Optional file type (pdf, epub, txt, md, etc.)
            file_size: Optional original file size in bytes

        Returns:
            Dictionary containing the created document record with all fields
        """
        pass

    @abstractmethod
    def get_document(
        self,
        doc_id: str,
        namespace: str | None = None
    ) -> dict[str, Any] | None:
        """
        Retrieve a document by ID

        Args:
            doc_id: Document identifier to retrieve
            namespace: Optional namespace for the document (may be required for some providers)

        Returns:
            Dictionary with document metadata if found, None otherwise
        """
        pass

    @abstractmethod
    def list_documents(
        self,
        namespace: str | None = None,
        limit: int = 100,
        last_evaluated_key: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        List documents with pagination support

        Supports listing documents within a namespace or across all namespaces.
        Results are typically sorted by creation date (most recent first).

        Args:
            namespace: Optional namespace to filter by (None = all namespaces)
            limit: Maximum number of documents to return (default 100)
            last_evaluated_key: Pagination token from previous response

        Returns:
            Dictionary with structure:
            {
                "documents": List[Dict[str, Any]],  # List of document records
                "next_key": Optional[Dict[str, Any]]  # Pagination token if more results exist
            }
        """
        pass

    @abstractmethod
    def delete_document(
        self,
        doc_id: str,
        namespace: str | None = None
    ) -> bool:
        """
        Delete a document index entry

        Args:
            doc_id: Document identifier to delete
            namespace: Optional namespace for the document

        Returns:
            True if document was deleted, False if not found
        """
        pass

    @abstractmethod
    def update_document_summary(
        self,
        doc_id: str,
        summary: str,
        summary_embedding_id: str,
        namespace: str | None = None
    ) -> bool:
        """
        Update the summary and summary embedding ID for a document

        This is used when a summary is generated after initial ingestion,
        or when a summary is regenerated.

        Args:
            doc_id: Document identifier to update
            summary: New summary text
            summary_embedding_id: ID of the summary embedding in vector database
            namespace: Optional namespace for the document

        Returns:
            True if update was successful, False if document not found
        """
        pass

    @abstractmethod
    def get_chunk_ids(
        self,
        doc_id: str,
        namespace: str | None = None
    ) -> list[str]:
        """
        Retrieve all chunk IDs for a document

        This is used to get the list of vector IDs that belong to a document,
        typically for deletion or processing.

        Args:
            doc_id: Document identifier
            namespace: Optional namespace for the document

        Returns:
            List of chunk IDs from the vector database
        """
        pass

    @abstractmethod
    def document_exists(
        self,
        filename: str,
        namespace: str
    ) -> bool:
        """
        Check if a document with the given filename already exists in namespace

        Used for duplicate detection before ingesting a new document.

        Args:
            filename: Filename to check
            namespace: Namespace to search in

        Returns:
            True if a document with this filename exists in the namespace
        """
        pass

    @abstractmethod
    def get_name(self) -> str:
        """
        Get the provider name

        Returns:
            Name of the document index provider (typically the class name)
        """
        pass

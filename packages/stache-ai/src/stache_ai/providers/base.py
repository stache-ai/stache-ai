"""Base provider interfaces - Abstract base classes for all providers"""

import builtins
from abc import ABC, abstractmethod
from typing import Any, Dict, TYPE_CHECKING

from stache_ai.providers.tool_types import ToolSpec, ToolCall, ToolUseResult, Message

if TYPE_CHECKING:
    from stache_ai.middleware.context import RequestContext


class EmbeddingProvider(ABC):
    """Abstract base class for embedding providers"""

    @abstractmethod
    def embed(self, text: str, *, context: "RequestContext | None" = None) -> list[float]:
        """
        Generate embedding for a single text

        Args:
            text: Input text to embed
            context: optional request context (caller identity / correlation);
                keyword-only. Core and first-party providers ignore it — a
                provider may read it to route or observe per caller.

        Returns:
            List of floats representing the embedding vector
        """
        pass

    @abstractmethod
    def embed_batch(self, texts: list[str], *, context: "RequestContext | None" = None) -> list[list[float]]:
        """
        Generate embeddings for multiple texts

        Args:
            texts: List of input texts
            context: optional request context (caller identity / correlation);
                keyword-only. Core and first-party providers ignore it.

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

    def embed_query(self, text: str, *, context: "RequestContext | None" = None) -> list[float]:
        """
        Generate embedding for a search query.

        Some embedding models (e.g., Cohere) use different parameters for
        queries vs documents. Override this method if your provider needs
        different behavior for query embeddings.

        Args:
            text: Query text to embed
            context: optional request context (caller identity / correlation);
                keyword-only. Forwarded to embed(); core providers ignore it.

        Returns:
            List of floats representing the embedding vector
        """
        return self.embed(text, context=context)

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
    def generate(self, prompt: str, *, context: "RequestContext | None" = None, **kwargs) -> str:
        """
        Generate text from a prompt

        Args:
            prompt: Input prompt
            context: optional request context (caller identity / correlation);
                keyword-only. Core and first-party providers ignore it.
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
        *,
        request_context: "RequestContext | None" = None,
        **kwargs
    ) -> str:
        """
        Generate answer given query and context

        Args:
            query: User query
            context: List of context chunks with metadata (the RAG chunks)
            request_context: optional request context (caller identity /
                correlation); keyword-only. Named ``request_context`` here
                because ``context`` already denotes the RAG chunk list. Core
                and first-party providers ignore it.
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
        *,
        context: "RequestContext | None" = None,
        **kwargs
    ) -> str:
        """
        Generate text using a specific model.

        Override this method if your provider supports model selection.
        Default implementation falls back to generate() with default model.

        Args:
            prompt: Input prompt
            model_id: Model ID to use
            context: optional request context (caller identity / correlation);
                keyword-only, forwarded to generate(). Core providers ignore it.
            **kwargs: Provider-specific parameters

        Returns:
            Generated text
        """
        # Default: ignore model_id and use configured model
        return self.generate(prompt, context=context, **kwargs)

    def generate_with_context_and_model(
        self,
        query: str,
        context: list[dict[str, Any]],
        model_id: str,
        *,
        request_context: "RequestContext | None" = None,
        **kwargs
    ) -> str:
        """
        Generate answer with context using a specific model.

        Override this method if your provider supports model selection.
        Default implementation falls back to generate_with_context() with default model.

        Args:
            query: User query
            context: List of context chunks with metadata (the RAG chunks)
            model_id: Model ID to use
            request_context: optional request context (caller identity /
                correlation); keyword-only, forwarded to
                generate_with_context(). Core providers ignore it.
            **kwargs: Provider-specific parameters

        Returns:
            Generated answer
        """
        # Default: ignore model_id and use configured model
        return self.generate_with_context(query, context, request_context=request_context, **kwargs)

    def get_name(self) -> str:
        """Get provider name"""
        return self.__class__.__name__

    def generate_structured(
        self,
        prompt: str,
        schema: dict,
        max_tokens: int = 2048,
        temperature: float = 0.0,
        *,
        context: "RequestContext | None" = None,
        **kwargs
    ) -> dict:
        """Generate JSON output matching schema (synchronous).

        Use asyncio.to_thread() when calling from async contexts.

        Args:
            prompt: Input prompt
            schema: JSON schema defining output structure
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0.0 = deterministic)
            **kwargs: Provider-specific parameters

        Returns:
            Parsed JSON dict matching schema

        Raises:
            NotImplementedError: If provider doesn't support structured output
            ValueError: If output doesn't match schema
            RuntimeError: On API errors
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support structured output. "
            "Override generate_structured() in subclass."
        )

    def generate_with_tools(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
        system_prompt: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        *,
        context: "RequestContext | None" = None,
        **kwargs
    ) -> ToolUseResult:
        """Generate response with tool use capability (synchronous).

        Call via asyncio.to_thread() from async code.

        Args:
            messages: Conversation history
            tools: Available tools the LLM can call
            system_prompt: Optional system instructions
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            **kwargs: Provider-specific parameters

        Returns:
            ToolUseResult with either:
            - stop_reason="end_turn", text=response (task complete)
            - stop_reason="tool_use", tool_calls=[...] (tools to execute)

        Raises:
            NotImplementedError: If provider doesn't support tool use
            RuntimeError: On API errors
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support tool use. "
            "Override generate_with_tools() in subclass."
        )

    @property
    def capabilities(self) -> set[str]:
        """Return set of supported operations.

        Override in subclasses to declare capabilities.

        Returns:
            Set of capability strings. Common capabilities:
            - "structured_output": Supports generate_structured()
            - "tool_use": Supports function calling
            - "streaming": Supports streaming responses
        """
        return set()


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
        filter_keys: list[str] | None = None,
        context: "RequestContext | None" = None
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
            context: optional request context (caller identity); implementations
                may scope behavior on it, core providers ignore it.

        Returns:
            Created namespace record including filter_keys (defaults to [])
        """
        pass

    @abstractmethod
    def get(self, id: str, context: "RequestContext | None" = None) -> dict[str, Any] | None:
        """
        Get a namespace by ID

        Args:
            id: Namespace ID
            context: optional request context (caller identity); implementations
                may scope behavior on it, core providers ignore it.

        Returns:
            Namespace record or None if not found
        """
        pass

    @abstractmethod
    def list(
        self,
        parent_id: str | None = None,
        include_children: bool = False,
        context: "RequestContext | None" = None
    ) -> list[dict[str, Any]]:
        """
        List namespaces

        Args:
            parent_id: Filter by parent (None for root namespaces)
            include_children: If True, recursively include children
            context: optional request context (caller identity); implementations
                may scope behavior on it, core providers ignore it.

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
        filter_keys: builtins.list[str] | None = None,
        context: "RequestContext | None" = None
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
            context: optional request context (caller identity); implementations
                may scope behavior on it, core providers ignore it.

        Returns:
            Updated namespace record or None if not found
        """
        pass

    @abstractmethod
    def delete(self, id: str, cascade: bool = False, context: "RequestContext | None" = None) -> bool:
        """
        Delete a namespace

        Args:
            id: Namespace ID to delete
            cascade: If True, delete children; if False, fail if children exist
            context: optional request context (caller identity); implementations
                may scope behavior on it, core providers ignore it.

        Returns:
            True if deleted, False if not found
        """
        pass

    @abstractmethod
    def get_tree(self, root_id: str | None = None, context: "RequestContext | None" = None) -> builtins.list[dict[str, Any]]:
        """
        Get namespace hierarchy as a tree

        Args:
            root_id: Start from this namespace (None for full tree)
            context: optional request context (caller identity); implementations
                may scope behavior on it, core providers ignore it.

        Returns:
            List of namespaces with nested 'children' arrays
        """
        pass

    @abstractmethod
    def exists(self, id: str, context: "RequestContext | None" = None) -> bool:
        """
        Check if a namespace exists

        Args:
            id: Namespace ID
            context: optional request context (caller identity); implementations
                may scope behavior on it, core providers ignore it.

        Returns:
            True if exists
        """
        pass

    def get_ancestors(self, id: str, context: "RequestContext | None" = None) -> builtins.list[dict[str, Any]]:
        """Get all ancestor namespaces, root first.

        Default implementation walks parent links via ``get``. Providers may
        override with a more efficient lookup; overrides must accept and
        forward ``context`` like every other data method.
        """
        ancestors: builtins.list[dict[str, Any]] = []
        current = self.get(id, context=context)
        while current and current.get("parent_id"):
            parent = self.get(current["parent_id"], context=context)
            if not parent:
                break
            ancestors.append(parent)
            current = parent
        return list(reversed(ancestors))

    def get_path(self, id: str, context: "RequestContext | None" = None) -> str:
        """Get the display path of a namespace (e.g. 'A > B > C')."""
        current = self.get(id, context=context)
        if not current:
            return ""
        ancestors = self.get_ancestors(id, context=context)
        return " > ".join([a["name"] for a in ancestors] + [current["name"]])

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
        namespace: str | None = None,
        context: "RequestContext | None" = None
    ) -> list[str]:
        """
        Insert vectors into the database

        Args:
            vectors: List of embedding vectors
            texts: Corresponding text chunks
            metadatas: Optional metadata for each vector
            ids: Optional IDs for each vector (generated if not provided)
            namespace: Optional namespace for isolation (multi-user/multi-project)
            context: optional request context (caller identity); implementations
                may scope behavior on it, core providers ignore it.

        Returns:
            List of inserted vector IDs

        **CRITICAL**: Implementations MUST set status="active" on all new vectors:

        ```python
        for metadata in metadatas:
            if "status" not in metadata:
                metadata["status"] = "active"
        ```

        This ensures new vectors are searchable by default.
        """
        pass

    @abstractmethod
    def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        filter: dict[str, Any] | None = None,
        namespace: str | None = None,
        context: "RequestContext | None" = None
    ) -> list[dict[str, Any]]:
        """
        Search for similar vectors

        Args:
            query_vector: Query embedding vector
            top_k: Number of results to return
            filter: Optional metadata filter
            namespace: Optional namespace to search within
            context: optional request context (caller identity); implementations
                may scope behavior on it, core providers ignore it.

        Returns:
            List of results with text, metadata, and scores

        **CRITICAL**: Implementations MUST filter out soft-deleted vectors.

        **Status Filtering Logic**:
        Include vectors where:
        - status field doesn't exist (legacy vectors), OR
        - status == "active"

        Exclude vectors where:
        - status == "deleting", OR
        - status == "purging", OR
        - status == "purged"

        **Provider-Specific Implementations**:

        S3 Vectors (MongoDB-like syntax):
        ```python
        status_filter = {
            "$or": [
                {"status": {"$exists": False}},
                {"status": "active"}
            ]
        }
        combined = {"$and": [status_filter, user_filter]} if user_filter else status_filter
        ```

        Qdrant:
        ```python
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        status_filter = Filter(
            should=[
                FieldCondition(key="status", match=MatchValue(value="active")),
                # No way to check field non-existence in Qdrant - requires migration
            ]
        )
        ```

        Pinecone:
        ```python
        status_filter = {"status": {"$in": ["active"]}}
        # Pinecone requires migration to add status="active" to legacy vectors
        ```

        **Legacy Vector Handling**:
        - If provider supports "field doesn't exist" filtering: include legacy vectors
        - If not: requires one-time migration to backfill status="active"
        """
        pass

    @abstractmethod
    def delete(self, ids: list[str], namespace: str | None = None, context: "RequestContext | None" = None) -> bool:
        """
        Delete vectors by IDs

        Args:
            ids: List of vector IDs to delete
            namespace: Optional namespace to delete from
            context: optional request context (caller identity); implementations
                may scope behavior on it, core providers ignore it.

        Returns:
            True if successful
        """
        pass

    def update_status(
        self,
        ids: list[str],
        namespace: str,
        status: str,
        context: "RequestContext | None" = None
    ) -> int:
        """
        Update status field for multiple vectors (for soft delete).

        Args:
            ids: Vector IDs to update
            namespace: Target namespace
            status: New status value ("deleting", "purging", "purged", "active")
            context: optional request context (caller identity); implementations
                may scope behavior on it, core providers ignore it.

        Returns:
            Count of vectors updated

        **Implementation Notes**:
        - S3 Vectors: Batch update via update_vectors()
        - Qdrant: points.update_vectors() with payload
        - Pinecone: update() in batches
        - PostgreSQL pgvector: UPDATE vectors SET metadata = ... WHERE id IN (...)

        **Atomicity**: Best-effort batch update. Partial failures are acceptable
        (cleanup job can retry missed vectors).

        **Default Implementation**: Returns 0 and logs warning. Providers that don't
        support status-based soft delete will have vectors remain searchable after
        soft delete operations.
        """
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(
            f"{self.__class__.__name__} does not support status filtering. "
            f"Soft-deleted vectors will remain searchable until permanently deleted."
        )
        return 0

    @abstractmethod
    def get_collection_info(self, context: "RequestContext | None" = None) -> dict[str, Any]:
        """
        Get information about the collection

        Returns:
            Dictionary with collection stats

        context: optional request context (caller identity); implementations
            may scope behavior on it, core providers ignore it.
        """
        pass

    def delete_by_metadata(self, field: str, value: str, namespace: str | None = None, context: "RequestContext | None" = None) -> dict[str, Any]:
        """
        Delete vectors by metadata field value

        Args:
            field: Metadata field name (e.g., 'filename')
            value: Value to match
            namespace: Optional namespace filter
            context: optional request context (caller identity); implementations
                may scope behavior on it, core providers ignore it.

        Returns:
            Dictionary with deleted count and IDs
        """
        raise NotImplementedError("delete_by_metadata not implemented for this provider")

    def search_summaries(
        self,
        query_vector: list[float],
        top_k: int = 10,
        namespace: str | None = None,
        context: "RequestContext | None" = None
    ) -> list[dict[str, Any]]:
        """
        Search document summaries (for document discovery)

        Unlike search() which excludes summaries, this method ONLY searches
        document summaries (_type=document_summary).

        Args:
            query_vector: Query embedding vector
            top_k: Number of results to return
            namespace: Optional namespace to search within (supports wildcards)
            context: optional request context (caller identity); implementations
                may scope behavior on it, core providers ignore it.

        Returns:
            List of results with document metadata and scores
        """
        raise NotImplementedError("search_summaries not implemented for this provider")

    def count_by_filter(self, filter: dict[str, Any], context: "RequestContext | None" = None) -> int:
        """
        Count vectors matching a filter

        Args:
            filter: Dictionary of field:value pairs to match
            context: optional request context (caller identity); implementations
                may scope behavior on it, core providers ignore it.

        Returns:
            Count of matching vectors
        """
        raise NotImplementedError("count_by_filter not implemented for this provider")

    def list_by_filter(
        self,
        filter: dict[str, Any],
        fields: list[str] | None = None,
        limit: int = 1000,
        context: "RequestContext | None" = None
    ) -> list[dict[str, Any]]:
        """
        List vectors matching a filter with their metadata

        Args:
            filter: Dictionary of field:value pairs to match
            fields: Optional list of metadata fields to return (None = all)
            limit: Maximum number of vectors to return
            context: optional request context (caller identity); implementations
                may scope behavior on it, core providers ignore it.

        Returns:
            List of dictionaries with vector metadata
        """
        raise NotImplementedError("list_by_filter not implemented for this provider")

    def scan_by_metadata(
        self,
        filter: dict[str, Any] | None = None,
        fields: list[str] | None = None,
        namespace: str | None = None,
        context: "RequestContext | None" = None
    ) -> list[dict[str, Any]]:
        """
        Scan ALL vectors matching an exact-match metadata filter (full scan).

        Unlike list_by_filter, this walks the entire collection without a limit
        and includes vectors missing the filtered fields when filter is None.
        Used by legacy maintenance operations (orphaned-chunk cleanup, summary
        migration). Only meaningful for providers that advertise the
        "metadata_scan" capability.

        Args:
            filter: Optional dictionary of field:value pairs to match (None = all)
            fields: Optional list of metadata fields to return (None = all)
            namespace: Optional namespace to restrict the scan to
            context: optional request context (caller identity); implementations
                may scope behavior on it, core providers ignore it.

        Returns:
            List of dictionaries with the vector "id" plus requested payload fields
        """
        raise NotImplementedError("scan_by_metadata not implemented for this provider")

    def get_by_ids(
        self,
        ids: list[str],
        fields: list[str] | None = None,
        namespace: str | None = None,
        context: "RequestContext | None" = None
    ) -> list[dict[str, Any]]:
        """Retrieve vectors by IDs with their metadata

        Args:
            ids: List of vector IDs to retrieve
            fields: Optional list of metadata fields to return (None = all)
            namespace: Optional namespace filter (validation only)
            context: optional request context (caller identity); implementations
                may scope behavior on it, core providers ignore it.

        Returns:
            List of dictionaries with vector metadata and text
            Format: [{"id": str, "text": str, **metadata}, ...]
        """
        raise NotImplementedError("get_by_ids not implemented for this provider")

    def get_vectors_with_embeddings(
        self,
        ids: list[str],
        namespace: str | None = None,
        context: "RequestContext | None" = None
    ) -> list[dict[str, Any]]:
        """Retrieve vectors by IDs with embeddings and metadata

        Unlike get_by_ids which only returns metadata, this method
        includes the full embedding vectors needed for re-writing.

        Args:
            ids: List of vector IDs to retrieve
            namespace: Optional namespace filter (validation only)
            context: optional request context (caller identity); implementations
                may scope behavior on it, core providers ignore it.

        Returns:
            List of dicts with standardized structure:
            {
                "id": str,              # Vector ID
                "vector": List[float],  # Embedding vector
                "metadata": Dict[str, Any]  # All metadata fields
            }

            CRITICAL: Return vectors in their STORED format (normalized or unnormalized).
            The caller (rerank middleware) will normalize S3 Vectors results and pass
            through other providers' results unchanged. S3 Vectors is the only provider
            that stores denormalized vectors - all others store normalized.
        """
        raise NotImplementedError("get_vectors_with_embeddings not implemented for this provider")

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

    @property
    def max_batch_size(self) -> int:
        """Maximum number of vectors that can be retrieved in a single batch

        Providers with smaller batch size limits (e.g., S3 Vectors' 100-vector limit
        for get_vectors) must override this property. Middleware that needs to fetch
        vectors in batches (like rerank) will use this value to chunk requests.

        Returns:
            Maximum batch size (default: 1000)
        """
        return 1000


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
        file_size: int | None = None,
        blob_key: str | None = None,
        content_type: str | None = None,
        context: "RequestContext | None" = None
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
            blob_key: Optional storage key of the retained original blob (the
                location the download endpoint presigns). None when no original
                was retained (e.g. pasted text or the inline tier).
            content_type: Optional MIME type of the retained original.
            context: optional request context (caller identity); implementations
                may scope behavior on it, core providers ignore it.

        Returns:
            Dictionary containing the created document record with all fields
        """
        pass

    @abstractmethod
    def get_document(
        self,
        doc_id: str,
        namespace: str | None = None,
        context: "RequestContext | None" = None
    ) -> dict[str, Any] | None:
        """
        Retrieve a document by ID

        Args:
            doc_id: Document identifier to retrieve
            namespace: Optional namespace for the document (may be required for some providers)
            context: optional request context (caller identity); implementations
                may scope behavior on it, core providers ignore it.

        Returns:
            Dictionary with document metadata if found, None otherwise
        """
        pass

    @abstractmethod
    def list_documents(
        self,
        namespace: str | None = None,
        limit: int = 100,
        last_evaluated_key: dict[str, Any] | None = None,
        context: "RequestContext | None" = None
    ) -> dict[str, Any]:
        """
        List documents with pagination support

        Supports listing documents within a namespace or across all namespaces.
        Results are typically sorted by creation date (most recent first).

        Args:
            namespace: Optional namespace to filter by (None = all namespaces)
            limit: Maximum number of documents to return (default 100)
            last_evaluated_key: Pagination token from previous response
            context: optional request context (caller identity); implementations
                may scope behavior on it, core providers ignore it.

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
        namespace: str | None = None,
        context: "RequestContext | None" = None
    ) -> bool:
        """
        Delete a document index entry

        Args:
            doc_id: Document identifier to delete
            namespace: Optional namespace for the document
            context: optional request context (caller identity); implementations
                may scope behavior on it, core providers ignore it.

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
        namespace: str | None = None,
        context: "RequestContext | None" = None
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
            context: optional request context (caller identity); implementations
                may scope behavior on it, core providers ignore it.

        Returns:
            True if update was successful, False if document not found
        """
        pass

    @abstractmethod
    def update_document_metadata(
        self,
        doc_id: str,
        namespace: str,
        updates: dict[str, Any],
        context: "RequestContext | None" = None
    ) -> bool:
        """
        Update document metadata fields atomically

        Supports updating:
        - namespace: Move document to new namespace (updates GSI1PK)
        - filename: Rename document (updates GSI2PK)
        - metadata: Update custom metadata dict
        - headings: Update extracted headings list

        Does NOT update:
        - doc_id: Immutable
        - chunk_ids: Managed by system
        - created_at: Immutable
        - chunk_count: Derived from chunk_ids
        - summary/summary_embedding_id: Use update_document_summary

        Args:
            doc_id: Document identifier
            namespace: Current namespace (for lookup)
            updates: Dict with fields to update. Keys:
                - "namespace": str (new namespace)
                - "filename": str (new filename)
                - "metadata": dict (replaces existing metadata)
                - "headings": list[str] (replaces existing headings)
            context: optional request context (caller identity); implementations
                may scope behavior on it, core providers ignore it.

        Returns:
            True if update was successful, False if document not found

        Raises:
            ValueError: If updates contains invalid fields
        """
        pass

    @abstractmethod
    def get_chunk_ids(
        self,
        doc_id: str,
        namespace: str | None = None,
        context: "RequestContext | None" = None
    ) -> list[str]:
        """
        Retrieve all chunk IDs for a document

        This is used to get the list of vector IDs that belong to a document,
        typically for deletion or processing.

        Args:
            doc_id: Document identifier
            namespace: Optional namespace for the document
            context: optional request context (caller identity); implementations
                may scope behavior on it, core providers ignore it.

        Returns:
            List of chunk IDs from the vector database
        """
        pass

    @abstractmethod
    def document_exists(
        self,
        filename: str,
        namespace: str,
        context: "RequestContext | None" = None
    ) -> bool:
        """
        Check if a document with the given filename already exists in namespace

        Used for duplicate detection before ingesting a new document.

        Args:
            filename: Filename to check
            namespace: Namespace to search in
            context: optional request context (caller identity); implementations
                may scope behavior on it, core providers ignore it.

        Returns:
            True if a document with this filename exists in the namespace
        """
        pass

    def count_by_namespace(self, namespace: str, context: "RequestContext | None" = None) -> dict[str, int]:
        """
        Get document and chunk counts for a namespace

        This provides an efficient way to get namespace statistics without
        scanning the vector database. Implementations should use indexed
        queries where possible.

        Args:
            namespace: Namespace to count documents for
            context: optional request context (caller identity); implementations
                may scope behavior on it, core providers ignore it.

        Returns:
            Dictionary with:
            {
                "doc_count": int,    # Number of documents
                "chunk_count": int   # Total chunks across all documents
            }

        Note:
            Default implementation returns zeros. Override in subclasses
            that support efficient counting.
        """
        return {"doc_count": 0, "chunk_count": 0}

    # ==================== Deduplication Methods ====================

    @abstractmethod
    def reserve_identifier(
        self,
        content_hash: str,
        filename: str,
        namespace: str,
        doc_id: str,
        source_path: str | None = None,
        file_size: int | None = None,
        file_modified_at: str | None = None,
        metadata: dict[str, Any] | None = None,
        context: "RequestContext | None" = None
    ) -> bool:
        """
        Atomically reserve a document identifier.

        Returns True if reservation succeeded, False if identifier already exists.

        **Atomicity Requirement**: MUST use provider-native atomic operations:
        - DynamoDB: conditional put with attribute_not_exists(PK)
        - PostgreSQL: INSERT ... ON CONFLICT DO NOTHING with UNIQUE constraint
        - MongoDB: insertOne with unique index on identifier

        **Implementation Notes**:
        - Compute identifier using _compute_identifier() logic
        - Store pending reservation with status="pending"
        - On conflict, return False (identifier already reserved)

        context: optional request context (caller identity); implementations
            may scope behavior on it, core providers ignore it.
        """
        pass

    @abstractmethod
    def get_document_by_identifier(
        self,
        content_hash: str,
        filename: str,
        namespace: str,
        source_path: str | None = None,
        context: "RequestContext | None" = None
    ) -> dict[str, Any] | None:
        """
        Retrieve document by identifier (strongly consistent).

        Returns document metadata if identifier exists and status="complete", else None.

        **Consistency Requirement**: MUST use strongly consistent reads:
        - DynamoDB: ConsistentRead=True
        - PostgreSQL: SELECT (default serializable)
        - MongoDB: Read concern "linearizable" or "majority"

        **Returns**:
        {
            "doc_id": str,
            "namespace": str,
            "identifier_type": "source_path" | "fingerprint",
            "content_hash": str,
            "filename": str,
            "source_path": str | None,
            "file_size": int | None,
            "file_modified_at": str | None,
            "ingested_at": str,
            "version": int,
        }

        context: optional request context (caller identity); implementations
            may scope behavior on it, core providers ignore it.
        """
        pass

    def get_document_by_source_path(
        self,
        namespace: str,
        source_path: str | None = None,
        filename: str | None = None,
        context: "RequestContext | None" = None
    ) -> dict[str, Any] | None:
        """
        Find active document by source_path or filename.

        Used for deduplication: checks if document already exists at this path.
        Uses GSI2 index in DynamoDB for efficient lookup.

        Default implementation falls back to get_document_by_identifier for
        backward compatibility with providers that haven't implemented this yet.

        Args:
            namespace: Namespace to search in
            source_path: Source path from CLI ingestion (preferred identifier)
            filename: Fallback filename for web uploads
            context: optional request context (caller identity); implementations
                may scope behavior on it, core providers ignore it.

        Returns:
            Document metadata if found and active, None otherwise:
            {
                "doc_id": str,
                "namespace": str,
                "filename": str | None,
                "source_path": str | None,
                "content_hash": str | None,
                "chunk_ids": list[str],
                "created_at": str,
            }
        """
        # Default: fall back to identifier lookup for backward compatibility
        # Subclasses should override for GSI2-based lookup
        return self.get_document_by_identifier(
            content_hash="",  # Not used in GSI2 lookup
            filename=filename or "",
            namespace=namespace,
            source_path=source_path,
            context=context,
        )

    @abstractmethod
    def complete_identifier_reservation(
        self,
        content_hash: str,
        filename: str,
        namespace: str,
        doc_id: str,
        chunk_count: int,
        source_path: str | None = None,
        context: "RequestContext | None" = None
    ) -> None:
        """
        Mark identifier reservation as complete after successful ingestion.

        Updates reservation status from "pending" to "complete".

        context: optional request context (caller identity); implementations
            may scope behavior on it, core providers ignore it.
        """
        pass

    @abstractmethod
    def release_identifier(
        self,
        content_hash: str,
        filename: str,
        namespace: str,
        source_path: str | None = None,
        context: "RequestContext | None" = None
    ) -> None:
        """
        Release identifier reservation on ingestion failure (cleanup).

        Deletes the pending reservation to allow retries.

        context: optional request context (caller identity); implementations
            may scope behavior on it, core providers ignore it.
        """
        pass

    # ==================== Soft Delete / Trash Methods ====================

    @abstractmethod
    def soft_delete_document(
        self,
        doc_id: str,
        namespace: str,
        deleted_by: str | None = None,
        delete_reason: str = "user_initiated",
        context: "RequestContext | None" = None
    ) -> dict[str, Any]:
        """
        Soft delete document (move to trash).

        **Atomicity Recommendation**: Update document status and create trash entry
        in a single transaction where supported:
        - DynamoDB: transact_write_items (2 writes: update DOC, put TRASH)
        - PostgreSQL: BEGIN; UPDATE docs; INSERT trash; COMMIT;
        - MongoDB: multi-document transaction with session

        **If transactions not available**: Best-effort (update doc, then create trash).
        Race conditions are acceptable - worst case is trash entry without doc update
        (cleanup job handles orphaned trash entries).

        **Returns**:
        {
            "doc_id": str,
            "namespace": str,
            "chunk_ids": list[str],
            "filename": str,
            "deleted_at": str (ISO8601),
            "purge_after": str (ISO8601, deleted_at + 30 days),
        }

        context: optional request context (caller identity); implementations
            may scope behavior on it, core providers ignore it.
        """
        pass

    @abstractmethod
    def restore_document(
        self,
        doc_id: str,
        namespace: str,
        deleted_at_ms: int,  # NEW: identifies specific trash entry
        restored_by: str | None = None,
        context: "RequestContext | None" = None
    ) -> dict[str, Any]:
        """
        Restore document from trash.

        Args:
            doc_id: Document UUID
            namespace: Document namespace
            deleted_at_ms: Timestamp (milliseconds) from trash entry PK
            restored_by: User ID who restored
            context: optional request context (caller identity); implementations
                may scope behavior on it, core providers ignore it.

        **Atomicity Recommendation**: Use transactions to:
        1. Update document status from "deleting" to "active"
        2. Delete specific trash entry (by deleted_at_ms)

        **Returns**:
        {
            "doc_id": str,
            "namespace": str,
            "status": "active",
            "restored_at": str (ISO8601),
            "chunk_ids": list[str],  # Needed for vector status restoration
            "chunk_count": int,
        }
        """
        pass

    @abstractmethod
    def list_trash(
        self,
        namespace: str | None = None,
        limit: int = 50,
        next_key: str | None = None,
        context: "RequestContext | None" = None
    ) -> dict[str, Any]:
        """
        List documents in trash.

        **Optimization Notes**:
        - DynamoDB: Use GSI on TRASH entries, query by namespace
        - PostgreSQL: Index on (namespace, deleted_at) for fast filtering
        - MongoDB: Compound index on {namespace: 1, deleted_at: -1}

        **Returns**:
        {
            "documents": [
                {
                    "doc_id": str,
                    "namespace": str,
                    "filename": str,
                    "deleted_at": str (ISO8601),
                    "deleted_at_ms": int (for restore operation),
                    "deleted_by": str | None,
                    "delete_reason": str,
                    "chunk_count": int,
                    "days_until_purge": int,
                    "purge_after": str (ISO8601),
                }
            ],
            "next_key": str | None,
        }

        context: optional request context (caller identity); implementations
            may scope behavior on it, core providers ignore it.
        """
        pass

    @abstractmethod
    def permanently_delete_document(
        self,
        doc_id: str,
        namespace: str,
        deleted_at_ms: int,  # NEW: identifies specific trash entry
        deleted_by: str | None = None,
        filename: str | None = None,  # Filename from trash entry (ensures correct trash PK),
        context: "RequestContext | None" = None
    ) -> dict[str, Any]:
        """
        Permanently delete document from trash (triggers vector cleanup).

        Creates cleanup job for async worker to delete vectors.

        Args:
            doc_id: Document UUID
            namespace: Document namespace
            deleted_at_ms: Timestamp (milliseconds) from trash entry
            deleted_by: User ID who initiated permanent delete
            filename: Filename from trash entry (uses doc metadata if not provided)
            context: optional request context (caller identity); implementations
                may scope behavior on it, core providers ignore it.

        **Returns**:
        {
            "doc_id": str,
            "namespace": str,
            "chunk_ids": list[str],
            "chunk_count": int,
            "cleanup_job_id": str,
        }
        """
        pass

    @abstractmethod
    def complete_permanent_delete(
        self,
        doc_id: str,
        namespace: str,
        deleted_at_ms: int,  # NEW: identifies specific trash entry
        filename: str,  # NEW: required for providers that use filename in trash PK,
        context: "RequestContext | None" = None
    ) -> None:
        """
        Complete permanent delete after vector cleanup succeeds.

        Updates document status to "purged" (tombstone) and deletes trash entry.

        Args:
            doc_id: Document UUID
            namespace: Document namespace
            deleted_at_ms: Deletion timestamp (for trash entry identification)
            filename: Document filename (required for providers using filename in trash PK)
            context: optional request context (caller identity); implementations
                may scope behavior on it, core providers ignore it.
        """
        pass

    @abstractmethod
    def list_cleanup_jobs(self, limit: int = 10, context: "RequestContext | None" = None) -> list[dict[str, Any]]:
        """
        List pending cleanup jobs for background worker.

        **Returns**:
        [
            {
                "cleanup_job_id": str,
                "doc_id": str,
                "namespace": str,
                "deleted_at_ms": int,
                "chunk_ids": list[str],
                "created_at": str (ISO8601),
                "retry_count": int,
                "max_retries": int,
            }
        ]

        context: optional request context (caller identity); implementations
            may scope behavior on it, core providers ignore it.
        """
        pass

    @abstractmethod
    def delete_cleanup_job(self, cleanup_job_id: str, context: "RequestContext | None" = None) -> None:
        """
        Delete completed cleanup job.

        Args:
            cleanup_job_id: Cleanup job ID to delete
            context: optional request context (caller identity); implementations
                may scope behavior on it, core providers ignore it.
        """
        pass

    @abstractmethod
    def mark_cleanup_job_failed(
        self,
        cleanup_job_id: str,
        error: str,
        context: "RequestContext | None" = None
    ) -> None:
        """
        Mark cleanup job as failed (increments retry count or moves to DLQ).

        If retry_count >= max_retries, move to DLQ for manual intervention.

        context: optional request context (caller identity); implementations
            may scope behavior on it, core providers ignore it.
        """
        pass

    @abstractmethod
    def list_expired_trash(self, limit: int = 100, context: "RequestContext | None" = None) -> list[dict[str, Any]]:
        """
        List trash entries past their purge_after date (for scheduled cleanup).

        **Returns**:
        [
            {
                "doc_id": str,
                "namespace": str,
                "deleted_at_ms": int,
                "purge_after": str (ISO8601),
            }
        ]

        context: optional request context (caller identity); implementations
            may scope behavior on it, core providers ignore it.
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

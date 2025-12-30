"""
RAG Pipeline - Using Factory Pattern

Extensible RAG pipeline using the factory pattern.
Allows swapping providers via configuration without code changes.
"""

import logging
import threading
import uuid
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from stache_ai.middleware.context import RequestContext

import stache_ai.chunking.strategies  # noqa

# Auto-register providers
import stache_ai.providers.embeddings  # noqa
import stache_ai.providers.llm  # noqa
import stache_ai.providers.vectordb  # noqa
from stache_ai.chunking import ChunkingStrategyFactory
from stache_ai.config import Settings, settings
from stache_ai.providers import (
    DocumentIndexProviderFactory,
    EmbeddingProviderFactory,
    LLMProviderFactory,
    RerankerProviderFactory,
    S3VectorsProviderFactory,
    VectorDBProviderFactory,
)
from stache_ai.rag.embedding_resilience import (
    AutoSplitEmbeddingWrapper,
    BedrockErrorClassifier,
    OllamaErrorClassifier,
)

logger = logging.getLogger(__name__)

# Auto-select chunking strategy based on file extension
CHUNKING_BY_EXTENSION = {
    'docx': 'hierarchical',
    'pdf': 'hierarchical',
    'pptx': 'hierarchical',
    'xlsx': 'hierarchical',
    'md': 'markdown',
    'markdown': 'markdown',
    'txt': 'recursive',
    'vtt': 'transcript',
    'srt': 'transcript',
    'epub': 'hierarchical',
}


def get_chunking_strategy_for_file(filename: str) -> str:
    """
    Get the best chunking strategy for a file based on extension.

    Args:
        filename: Name of the file

    Returns:
        Chunking strategy name (hierarchical, markdown, recursive, transcript)
    """
    ext = Path(filename).suffix.lower().lstrip('.')
    return CHUNKING_BY_EXTENSION.get(ext, 'recursive')


class RAGPipeline:
    """
    Extensible RAG pipeline using factory pattern

    Supports:
    - Multiple embedding providers (OpenAI, Cohere, etc.)
    - Multiple LLM providers (Anthropic, OpenAI, etc.)
    - Multiple vector DBs (Qdrant, Pinecone, Chroma, etc.)
    - Swappable via environment variables
    """

    def __init__(self, config: Settings | None = None):
        self.config = config or settings
        self._embedding_provider = None
        self._llm_provider = None
        self._vectordb_provider = None
        self._reranker_provider = None
        self._reranker_initialized = False
        self._document_index_provider = None
        self._documents_provider = None
        self._summaries_provider = None
        self._insights_provider = None
        # Middleware
        self._enrichers = None
        self._chunk_observers = None
        self._query_processors = None
        self._result_processors = None
        self._delete_observers = None
        # Thread-safe locks for middleware lazy initialization
        self._enrichers_lock = threading.Lock()
        self._chunk_observers_lock = threading.Lock()
        self._query_processors_lock = threading.Lock()
        self._result_processors_lock = threading.Lock()
        self._delete_observers_lock = threading.Lock()

    @property
    def embedding_provider(self):
        """Lazy-load embedding provider"""
        if self._embedding_provider is None:
            self._embedding_provider = EmbeddingProviderFactory.create(self.config)
            logger.info(f"Initialized embedding provider: {self._embedding_provider.get_name()}")
        return self._embedding_provider

    @property
    def llm_provider(self):
        """Lazy-load LLM provider"""
        if self._llm_provider is None:
            self._llm_provider = LLMProviderFactory.create(self.config)
            logger.info(f"Initialized LLM provider: {self._llm_provider.get_name()}")
        return self._llm_provider

    @property
    def vectordb_provider(self):
        """Lazy-load vector DB provider"""
        if self._vectordb_provider is None:
            self._vectordb_provider = VectorDBProviderFactory.create(self.config)
            logger.info(f"Initialized vector DB provider: {self._vectordb_provider.get_name()}")
        return self._vectordb_provider

    @property
    def documents_provider(self):
        """Lazy-load documents vector DB provider (S3Vectors if available, else fallback to vectordb_provider)"""
        if self._documents_provider is None:
            if self.config.vectordb_provider == "s3vectors":
                self._documents_provider = S3VectorsProviderFactory.get_provider(self.config, "documents")
                logger.info(f"Initialized documents provider: {self._documents_provider.get_name()}")
            else:
                self._documents_provider = self.vectordb_provider
        return self._documents_provider

    @property
    def summaries_provider(self):
        """Lazy-load summaries vector DB provider (S3Vectors if available, else fallback to vectordb_provider)"""
        if self._summaries_provider is None:
            if self.config.vectordb_provider == "s3vectors":
                self._summaries_provider = S3VectorsProviderFactory.get_provider(self.config, "summaries")
                logger.info(f"Initialized summaries provider: {self._summaries_provider.get_name()}")
            else:
                self._summaries_provider = self.vectordb_provider
        return self._summaries_provider

    @property
    def insights_provider(self):
        """Lazy-load insights vector DB provider (S3Vectors if available, else fallback to vectordb_provider)"""
        if self._insights_provider is None:
            if self.config.vectordb_provider == "s3vectors":
                self._insights_provider = S3VectorsProviderFactory.get_provider(self.config, "insights")
                logger.info(f"Initialized insights provider: {self._insights_provider.get_name()}")
            else:
                self._insights_provider = self.vectordb_provider
        return self._insights_provider

    @property
    def reranker_provider(self):
        """Lazy-load reranker provider (can be None if disabled)"""
        if not self._reranker_initialized:
            self._reranker_provider = RerankerProviderFactory.create(self.config)
            self._reranker_initialized = True
            if self._reranker_provider:
                logger.info(f"Initialized reranker provider: {self._reranker_provider.get_name()}")
        return self._reranker_provider

    @property
    def document_index_provider(self):
        """Lazy-load document index provider"""
        if self._document_index_provider is None:
            self._document_index_provider = DocumentIndexProviderFactory.create(self.config)
            logger.info(f"Initialized document index provider: {self._document_index_provider.get_name()}")
        return self._document_index_provider

    @property
    def enrichers(self):
        """Lazy-load enrichment middleware"""
        if self._enrichers is None:
            with self._enrichers_lock:
                if self._enrichers is None:  # Double-check pattern
                    from stache_ai.providers.plugin_loader import get_providers
                    enricher_classes = get_providers('enrichment')
                    self._enrichers = [cls() for cls in enricher_classes.values()]
                    # Sort by phase (extract -> transform -> enrich), then by priority
                    phase_order = {'extract': 0, 'transform': 1, 'enrich': 2}
                    self._enrichers.sort(key=lambda e: (phase_order.get(e.phase, 2), e.priority))
                    logger.info(f"Loaded {len(self._enrichers)} enrichers")
        return self._enrichers

    @property
    def chunk_observers(self):
        """Lazy-load chunk observer middleware"""
        if self._chunk_observers is None:
            with self._chunk_observers_lock:
                if self._chunk_observers is None:  # Double-check pattern
                    from stache_ai.providers.plugin_loader import get_providers
                    observer_classes = get_providers('chunk_observer')
                    self._chunk_observers = [cls() for cls in observer_classes.values()]
                    self._chunk_observers.sort(key=lambda o: o.priority)
                    logger.info(f"Loaded {len(self._chunk_observers)} chunk observers")
        return self._chunk_observers

    @property
    def query_processors(self):
        """Lazy-load query processor middleware"""
        if self._query_processors is None:
            with self._query_processors_lock:
                if self._query_processors is None:  # Double-check pattern
                    from stache_ai.providers.plugin_loader import get_providers
                    processor_classes = get_providers('query_processor')
                    self._query_processors = [cls() for cls in processor_classes.values()]
                    self._query_processors.sort(key=lambda p: p.priority)
                    logger.info(f"Loaded {len(self._query_processors)} query processors")
        return self._query_processors

    @property
    def result_processors(self):
        """Lazy-load result processor middleware"""
        if self._result_processors is None:
            with self._result_processors_lock:
                if self._result_processors is None:  # Double-check pattern
                    from stache_ai.providers.plugin_loader import get_providers
                    processor_classes = get_providers('result_processor')
                    self._result_processors = [cls() for cls in processor_classes.values()]
                    self._result_processors.sort(key=lambda p: p.priority)
                    logger.info(f"Loaded {len(self._result_processors)} result processors")
        return self._result_processors

    @property
    def delete_observers(self):
        """Lazy-load delete observer middleware"""
        if self._delete_observers is None:
            with self._delete_observers_lock:
                if self._delete_observers is None:  # Double-check pattern
                    from stache_ai.providers.plugin_loader import get_providers
                    observer_classes = get_providers('delete_observer')
                    self._delete_observers = [cls() for cls in observer_classes.values()]
                    self._delete_observers.sort(key=lambda o: o.priority)
                    logger.info(f"Loaded {len(self._delete_observers)} delete observers")
        return self._delete_observers

    async def ingest_text(
        self,
        text: str,
        metadata: dict[str, Any] | None = None,
        chunking_strategy: str = "recursive",
        namespace: str | None = None,
        prepend_metadata: list[str] | None = None,
        context: "RequestContext | None" = None
    ) -> dict[str, Any]:
        """
        Ingest text into the knowledge base

        Args:
            text: Text to ingest
            metadata: Optional metadata
            chunking_strategy: Strategy for chunking (recursive, markdown, etc.)
            namespace: Optional namespace for isolation (multi-user/multi-project)
            prepend_metadata: List of metadata keys to prepend to each chunk text.
                              This embeds the metadata into the vector for better semantic search.
                              Example: ["speaker", "topic"] would prepend "Speaker: X\nTopic: Y\n\n"
            context: Optional request context for middleware (created if not provided)

        Returns:
            Result dictionary with chunks_created count
        """
        logger.info(f"Ingesting text (length: {len(text)}, strategy: {chunking_strategy}, namespace: {namespace})")

        # Create request context if not provided
        if context is None:
            from datetime import datetime, timezone
            from uuid import uuid4
            from stache_ai.middleware.context import RequestContext
            context = RequestContext(
                request_id=str(uuid4()),
                timestamp=datetime.now(timezone.utc),
                namespace=namespace or self.config.default_namespace,
                source="api"
            )

        # Apply enrichment middleware before chunking
        current_text = text
        current_metadata = metadata or {}
        for enricher in self.enrichers:
            from stache_ai.middleware.chain import MiddlewareRejection
            result = await enricher.process(current_text, current_metadata, context)
            if result.action == "reject":
                raise MiddlewareRejection(enricher.__class__.__name__, result.reason)
            if result.action == "transform":
                current_text = result.content or current_text
                if result.metadata is not None:
                    current_metadata = {**current_metadata, **result.metadata}

        # Use enriched content and metadata
        text = current_text
        metadata = current_metadata

        # Build metadata prefix first so we can account for its size during chunking
        metadata_prefix = ""
        if prepend_metadata and metadata:
            prefix_lines = []
            for key in prepend_metadata:
                if key in metadata:
                    # Convert key to title case for readability (e.g., "speaker" -> "Speaker")
                    label = key.replace("_", " ").title()
                    prefix_lines.append(f"{label}: {metadata[key]}")
            if prefix_lines:
                metadata_prefix = "\n".join(prefix_lines) + "\n\n"
                logger.info(f"Prepending metadata to chunks: {prepend_metadata}")

        # Calculate effective chunk size accounting for metadata prefix
        prefix_len = len(metadata_prefix)
        if prefix_len > 0:
            # Reduce chunk size to leave room for metadata prefix
            effective_chunk_size = min(
                self.config.chunk_size,
                self.config.chunk_max_size - prefix_len
            )
            # Warn if prefix is larger than reserved space
            if prefix_len > self.config.chunk_metadata_reserve:
                logger.warning(
                    f"Metadata prefix ({prefix_len} chars) exceeds reserved space "
                    f"({self.config.chunk_metadata_reserve} chars). Consider increasing "
                    f"CHUNK_METADATA_RESERVE or reducing metadata."
                )
        else:
            effective_chunk_size = self.config.chunk_size

        # Use chunking strategy factory with adjusted size
        strategy = ChunkingStrategyFactory.create(chunking_strategy)
        chunk_objects = strategy.chunk(
            text,
            chunk_size=effective_chunk_size,
            chunk_overlap=self.config.chunk_overlap
        )

        # Extract text from chunk objects
        chunks = [chunk.text for chunk in chunk_objects]

        logger.info(f"Created {len(chunks)} chunks (effective size: {effective_chunk_size})")

        # Prepend metadata to each chunk for embedding
        chunks_for_embedding = [metadata_prefix + chunk for chunk in chunks] if metadata_prefix else chunks

        # Prepare base metadata before embedding (needed for expansion later)
        from datetime import datetime, timezone
        metadata = metadata or {}
        doc_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        base_metadata = {
            **metadata,
            "doc_id": doc_id,
            "created_at": created_at
        }
        metadatas = [
            {
                **base_metadata,
                "chunk_index": i,
                "total_chunks": len(chunks),
            }
            for i, _ in enumerate(chunks)
        ]

        # Wrap embedding provider with auto-split if enabled
        split_count = 0
        if self.config.embedding_auto_split_enabled:
            # Choose error classifier based on provider
            provider_name = self.embedding_provider.get_name().lower()
            if 'ollama' in provider_name:
                error_classifier = OllamaErrorClassifier()
            elif 'bedrock' in provider_name:
                error_classifier = BedrockErrorClassifier()
            else:
                error_classifier = None  # Use default

            wrapper = AutoSplitEmbeddingWrapper(
                provider=self.embedding_provider,
                max_split_depth=self.config.embedding_auto_split_max_depth,
                error_classifier=error_classifier,
                enabled=True
            )

            # Use wrapper for embedding
            results, split_count = wrapper.embed_batch_with_splits(chunks_for_embedding)

            # Extract embeddings and texts
            embeddings = [r.embedding for r in results]
            texts_to_store = [r.text for r in results]

            # Expand metadata for splits
            expanded_metadatas = []
            for r in results:
                # Start with metadata from original chunk
                if r.parent_index is not None and r.parent_index < len(metadatas):
                    meta = {**metadatas[r.parent_index]}
                else:
                    meta = {**base_metadata, "chunk_index": 0, "total_chunks": len(chunks)}

                # Add split metadata if this chunk was split
                if r.was_split:
                    meta['_split'] = True
                    meta['_split_index'] = r.split_index
                    meta['_split_total'] = r.split_total
                    meta['_parent_chunk_index'] = r.parent_index

                expanded_metadatas.append(meta)

            metadatas = expanded_metadatas
            chunks_for_embedding = texts_to_store
        else:
            # Auto-split disabled, use standard embed_batch
            embeddings = self.embedding_provider.embed_batch(chunks_for_embedding)

        # Use provided namespace or default from config
        ns = namespace or self.config.default_namespace

        # Insert into vector DB (store enriched chunks if metadata was prepended)
        ids = self.documents_provider.insert(
            vectors=embeddings,
            texts=chunks_for_embedding,
            metadatas=metadatas,
            namespace=ns
        )

        # Call chunk observers after storage (advisory only)
        for observer in self.chunk_observers:
            from stache_ai.middleware.base import StorageResult
            storage_result = StorageResult(
                vector_ids=ids,
                namespace=ns,
                index="documents",
                doc_id=doc_id,
                chunk_count=len(chunks_for_embedding),
                embedding_model=self.embedding_provider.get_name()
            )
            # Prepare chunks as (text, metadata) tuples
            chunk_tuples = list(zip(chunks_for_embedding, metadatas))
            try:
                result = await observer.on_chunks_stored(chunk_tuples, storage_result, context)
                if result.action == "reject":
                    logger.warning(
                        f"Chunk observer {observer.__class__.__name__} rejected storage: {result.reason}. "
                        "This is advisory only - chunks were already stored."
                    )
            except Exception as e:
                logger.error(f"Chunk observer {observer.__class__.__name__} failed: {e}")

        # Create document summary for catalog/discovery
        # Generate a readable filename if not provided
        if metadata and metadata.get("filename"):
            filename = metadata["filename"]
        else:
            # Create timestamp-based filename with text preview for captures
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            preview = text[:30].replace("\n", " ").strip()
            if len(text) > 30:
                preview += "..."
            filename = f"Capture {timestamp} - {preview}"
        summary_text, headings, summary_id = self._create_document_summary(
            doc_id=doc_id,
            filename=filename,
            namespace=ns,
            chunks=chunks,
            chunk_metadatas=metadatas,
            created_at=created_at,
            metadata=metadata
        )

        # Create document index entry for efficient metadata queries (dual-write pattern)
        # This is wrapped in try/except to prevent ingestion failure if index write fails
        if self.document_index_provider:
            try:
                # Text ingestion - file_type is "text", file_size is the text byte size
                file_size = len(text.encode('utf-8'))

                self.document_index_provider.create_document(
                    doc_id=doc_id,
                    filename=filename,
                    namespace=ns,
                    chunk_ids=ids,
                    summary=summary_text,
                    summary_embedding_id=summary_id,
                    headings=headings,
                    metadata=metadata,
                    file_type="text",
                    file_size=file_size
                )
                logger.info(f"Created document index entry for {filename} (doc_id: {doc_id})")
            except Exception as e:
                # Log error but continue - document is in vector DB and searchable
                logger.error(f"Failed to create document index for {filename}: {e}")

        # Build result
        result = {
            "chunks_created": len(chunks),
            "success": True,
            "ids": ids,
            "namespace": ns,
            "doc_id": doc_id,
        }

        # Add split info if any occurred
        if split_count > 0:
            result["splits_created"] = split_count
            result["info"] = [
                f"{split_count} chunk(s) were auto-split due to embedding token limits"
            ]

        return result

    async def ingest_file(
        self,
        file_path: str,
        metadata: dict[str, Any] | None = None,
        chunking_strategy: str = "auto",
        namespace: str | None = None,
        prepend_metadata: list[str] | None = None,
        context: "RequestContext | None" = None
    ) -> dict[str, Any]:
        """
        Ingest a file into the knowledge base with structure-aware processing.

        Uses Docling for hierarchical chunking when appropriate, preserving
        document structure like headings and sections.

        Args:
            file_path: Path to the document file
            metadata: Optional metadata
            chunking_strategy: Strategy for chunking. Use "auto" to select
                              based on file type, or specify explicitly.
            namespace: Optional namespace for isolation
            prepend_metadata: List of metadata keys to prepend to chunks
            context: Optional request context for middleware (created if not provided)

        Returns:
            Result dictionary with chunks_created count
        """
        path = Path(file_path)
        filename = path.name

        # Auto-select chunking strategy based on file type
        if chunking_strategy == "auto":
            chunking_strategy = get_chunking_strategy_for_file(filename)
            logger.info(f"Auto-selected chunking strategy: {chunking_strategy} for {filename}")

        logger.info(f"Ingesting file: {filename} (strategy: {chunking_strategy}, namespace: {namespace})")

        # Create request context if not provided
        if context is None:
            from datetime import datetime, timezone
            from uuid import uuid4
            from stache_ai.middleware.context import RequestContext
            context = RequestContext(
                request_id=str(uuid4()),
                timestamp=datetime.now(timezone.utc),
                namespace=namespace or self.config.default_namespace,
                source="api"
            )

        # Load file content for enrichment
        from stache_ai.loaders import load_document
        text = load_document(str(path), filename)

        # Apply enrichment middleware before chunking
        current_text = text
        current_metadata = metadata or {}
        for enricher in self.enrichers:
            from stache_ai.middleware.chain import MiddlewareRejection
            result = await enricher.process(current_text, current_metadata, context)
            if result.action == "reject":
                raise MiddlewareRejection(enricher.__class__.__name__, result.reason)
            if result.action == "transform":
                current_text = result.content or current_text
                if result.metadata is not None:
                    current_metadata = {**current_metadata, **result.metadata}

        # Use enriched content and metadata
        text = current_text
        metadata = current_metadata

        # Build metadata prefix
        metadata_prefix = ""
        if prepend_metadata and metadata:
            prefix_lines = []
            for key in prepend_metadata:
                if key in metadata:
                    label = key.replace("_", " ").title()
                    prefix_lines.append(f"{label}: {metadata[key]}")
            if prefix_lines:
                metadata_prefix = "\n".join(prefix_lines) + "\n\n"
                logger.info(f"Prepending metadata to chunks: {prepend_metadata}")

        # Calculate effective chunk size
        prefix_len = len(metadata_prefix)
        if prefix_len > 0:
            effective_chunk_size = min(
                self.config.chunk_size,
                self.config.chunk_max_size - prefix_len
            )
        else:
            effective_chunk_size = self.config.chunk_size

        # Use chunking strategy factory
        strategy = ChunkingStrategyFactory.create(chunking_strategy)

        # For hierarchical chunking, pass the file path directly
        # For other strategies, use the enriched text
        if chunking_strategy == "hierarchical":
            chunk_objects = strategy.chunk(
                "",  # Empty text, file_path is used
                chunk_size=effective_chunk_size,
                chunk_overlap=self.config.chunk_overlap,
                file_path=str(path)
            )
        else:
            chunk_objects = strategy.chunk(
                text,
                chunk_size=effective_chunk_size,
                chunk_overlap=self.config.chunk_overlap
            )

        # Extract text and merge chunk-level metadata
        chunks = []
        chunk_metadatas = []
        for chunk in chunk_objects:
            chunks.append(chunk.text)
            # Include any heading metadata from hierarchical chunking
            chunk_metadatas.append(chunk.metadata)

        logger.info(f"Created {len(chunks)} chunks from {filename}")

        # Prepend metadata to chunks for embedding
        chunks_for_embedding = [metadata_prefix + chunk for chunk in chunks] if metadata_prefix else chunks

        # Prepare base metadata
        from datetime import datetime, timezone
        metadata = metadata or {}
        doc_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()

        base_metadatas = []
        for i, chunk_meta in enumerate(chunk_metadatas):
            meta = {
                **metadata,
                **chunk_meta,  # Include heading info from hierarchical chunking
                "doc_id": doc_id,
                "chunk_index": i,
                "total_chunks": len(chunks),
                "created_at": created_at,
                "filename": filename,
            }
            base_metadatas.append(meta)

        # Generate embeddings with auto-split if enabled
        if self.config.embedding_auto_split_enabled:
            # Choose error classifier based on provider
            provider_name = self.embedding_provider.get_name().lower()
            if 'ollama' in provider_name:
                error_classifier = OllamaErrorClassifier()
            elif 'bedrock' in provider_name:
                error_classifier = BedrockErrorClassifier()
            else:
                error_classifier = None  # Use default

            wrapper = AutoSplitEmbeddingWrapper(
                provider=self.embedding_provider,
                max_split_depth=self.config.embedding_auto_split_max_depth,
                error_classifier=error_classifier,
                enabled=True
            )

            # Use wrapper for embedding
            results, split_count = wrapper.embed_batch_with_splits(chunks_for_embedding)

            # Extract embeddings and texts
            embeddings = [r.embedding for r in results]
            texts_to_store = [r.text for r in results]

            # Expand metadata for splits
            metadatas = []
            for r in results:
                # Start with metadata from original chunk
                if r.parent_index is not None and r.parent_index < len(base_metadatas):
                    meta = {**base_metadatas[r.parent_index]}
                else:
                    meta = {
                        **metadata,
                        "doc_id": doc_id,
                        "created_at": created_at,
                        "filename": filename,
                    }

                # Add split metadata if this chunk was split
                if r.was_split:
                    meta['_split'] = True
                    meta['_split_index'] = r.split_index
                    meta['_split_total'] = r.split_total
                    meta['_parent_chunk_index'] = r.parent_index

                metadatas.append(meta)

            chunks_for_embedding = texts_to_store
        else:
            # Auto-split disabled, use standard embed_batch
            embeddings = self.embedding_provider.embed_batch(chunks_for_embedding)
            metadatas = base_metadatas
            split_count = 0

        # Use provided namespace or default from config
        ns = namespace or self.config.default_namespace

        # Insert into vector DB
        ids = self.documents_provider.insert(
            vectors=embeddings,
            texts=chunks_for_embedding,
            metadatas=metadatas,
            namespace=ns
        )

        # Call chunk observers after storage (advisory only)
        for observer in self.chunk_observers:
            from stache_ai.middleware.base import StorageResult
            storage_result = StorageResult(
                vector_ids=ids,
                namespace=ns,
                index="documents",
                doc_id=doc_id,
                chunk_count=len(chunks_for_embedding),
                embedding_model=self.embedding_provider.get_name()
            )
            # Prepare chunks as (text, metadata) tuples
            chunk_tuples = list(zip(chunks_for_embedding, metadatas))
            try:
                result = await observer.on_chunks_stored(chunk_tuples, storage_result, context)
                if result.action == "reject":
                    logger.warning(
                        f"Chunk observer {observer.__class__.__name__} rejected storage: {result.reason}. "
                        "This is advisory only - chunks were already stored."
                    )
            except Exception as e:
                logger.error(f"Chunk observer {observer.__class__.__name__} failed: {e}")

        # Create document summary record for fast catalog and semantic discovery
        summary_text, headings, summary_id = self._create_document_summary(
            doc_id=doc_id,
            filename=filename,
            namespace=ns,
            chunks=chunks,
            chunk_metadatas=chunk_metadatas,
            created_at=created_at,
            metadata=metadata
        )

        # Create document index entry for efficient metadata queries (dual-write pattern)
        # This is wrapped in try/except to prevent ingestion failure if index write fails
        if self.document_index_provider:
            try:
                # Extract file metadata
                file_extension = path.suffix.lower().lstrip('.')
                file_size = path.stat().st_size if path.exists() else 0

                self.document_index_provider.create_document(
                    doc_id=doc_id,
                    filename=filename,
                    namespace=ns,
                    chunk_ids=ids,
                    summary=summary_text,
                    summary_embedding_id=summary_id,
                    headings=headings,
                    metadata=metadata,
                    file_type=file_extension,
                    file_size=file_size
                )
                logger.info(f"Created document index entry for {filename} (doc_id: {doc_id})")
            except Exception as e:
                # Log error but continue - document is in vector DB and searchable
                logger.error(f"Failed to create document index for {filename}: {e}")

        result = {
            "chunks_created": len(embeddings),
            "success": True,
            "ids": ids,
            "namespace": ns,
            "doc_id": doc_id,
            "chunking_strategy": chunking_strategy
        }

        # Add split info if any occurred
        if split_count > 0:
            result["splits_created"] = split_count
            result["info"] = [
                f"{split_count} chunk(s) were auto-split due to embedding token limits"
            ]

        return result

    def _create_document_summary(
        self,
        doc_id: str,
        filename: str,
        namespace: str,
        chunks: list[str],
        chunk_metadatas: list[dict[str, Any]],
        created_at: str,
        metadata: dict[str, Any] | None = None
    ) -> tuple[str | None, list[str], str | None]:
        """
        Create a document summary record in the vector DB for fast catalog
        and semantic discovery.

        The summary record has _type: "document_summary" to distinguish
        it from regular chunks. It contains:
        - Document info (filename, namespace, doc_id)
        - Headings extracted from chunks (for semantic search)
        - First ~1500 chars of content (for topic matching)
        - Chunk count for display

        Args:
            doc_id: The document ID
            filename: Original filename
            namespace: Namespace the document belongs to
            chunks: List of chunk texts
            chunk_metadatas: Metadata from each chunk (may contain headings)
            created_at: ISO timestamp
            metadata: Original document metadata

        Returns:
            Tuple of (summary_text, headings, summary_id) for document index creation,
            or (None, [], None) if summary creation fails
        """
        try:
            # Extract unique headings from chunk metadata (from hierarchical chunking)
            headings = []
            seen_headings = set()
            for chunk_meta in chunk_metadatas:
                for heading in chunk_meta.get("headings", []):
                    if heading and heading not in seen_headings:
                        headings.append(heading)
                        seen_headings.add(heading)

            # Build summary text for semantic search
            # Format: Document: {filename}\nNamespace: {namespace}\nHeadings: {...}\n\n{first 500 chars}
            summary_parts = [
                f"Document: {filename}",
                f"Namespace: {namespace}"
            ]

            if headings:
                summary_parts.append(f"Headings: {', '.join(headings[:20])}")  # Limit to 20 headings

            # Add first ~1500 chars of content from first chunks for better semantic matching
            content_preview = ""
            char_count = 0
            for chunk in chunks:
                remaining = 1500 - char_count
                if remaining <= 0:
                    break
                content_preview += chunk[:remaining] + " "
                char_count += len(chunk[:remaining])

            if content_preview.strip():
                summary_parts.append("")  # Empty line before content
                summary_parts.append(content_preview.strip())

            summary_text = "\n".join(summary_parts)

            # Generate embedding for summary
            summary_embedding = self.embedding_provider.embed(summary_text)

            # Create summary record - use a new UUID (Qdrant requires valid UUID or integer)
            summary_id = str(uuid.uuid4())
            summary_metadata = {
                "_type": "document_summary",
                "doc_id": doc_id,
                "filename": filename,
                "namespace": namespace,
                "chunk_count": len(chunks),
                "created_at": created_at,
                **(metadata or {})
            }
            # Only include headings if non-empty (S3 Vectors rejects empty arrays)
            if headings:
                summary_metadata["headings"] = headings[:50]

            # Insert summary record
            self.summaries_provider.insert(
                vectors=[summary_embedding],
                texts=[summary_text],
                metadatas=[summary_metadata],
                ids=[summary_id],
                namespace=namespace
            )

            logger.info(f"Created document summary for {filename} (doc_id: {doc_id}, headings: {len(headings)})")

            # Return summary data for document index creation
            return summary_text, headings, summary_id

        except Exception as e:
            # Don't fail the whole ingestion if summary creation fails
            logger.error(f"Failed to create document summary for {filename}: {e}")
            return None, [], None

    def get_available_chunking_strategies(self) -> list[str]:
        """Get list of available chunking strategies"""
        return ChunkingStrategyFactory.get_available_strategies()

    async def query(
        self,
        question: str,
        top_k: int = 5,
        synthesize: bool = True,
        namespace: str | None = None,
        rerank: bool = False,
        model: str | None = None,
        filter: dict[str, Any] | None = None,
        context: "RequestContext | None" = None
    ) -> dict[str, Any]:
        """
        Query the knowledge base

        Args:
            question: User question
            top_k: Number of results to retrieve
            synthesize: Whether to use LLM synthesis
            namespace: Optional namespace to search within
            rerank: Whether to rerank results for better relevance
            model: Optional model ID to use for synthesis (overrides default)
            filter: Optional metadata filter (e.g., {"source": "meeting notes"})
            context: Optional request context for middleware (created if not provided)

        Returns:
            Dictionary with question, answer (if synthesize=True), and sources
        """
        logger.info(f"Querying: {question} (synthesize={synthesize}, namespace={namespace}, rerank={rerank}, model={model}, filter={filter})")

        # Use provided namespace or default from config
        ns = namespace or self.config.default_namespace

        # Create request context if not provided
        if context is None:
            from datetime import datetime, timezone
            from uuid import uuid4
            from stache_ai.middleware.context import RequestContext
            context = RequestContext(
                request_id=str(uuid4()),
                timestamp=datetime.now(timezone.utc),
                namespace=ns,
                source="api"
            )

        # Create query context for middleware
        from stache_ai.middleware.context import QueryContext
        query_context = QueryContext.from_request_context(
            context=context,
            query=question,
            top_k=top_k,
            filters=filter
        )

        # Apply query processor middleware
        current_query = question
        current_filters = filter
        for processor in self.query_processors:
            from stache_ai.middleware.chain import MiddlewareRejection
            result = await processor.process(current_query, current_filters, query_context)
            if result.action == "reject":
                raise MiddlewareRejection(processor.__class__.__name__, result.reason)
            if result.action == "transform":
                current_query = result.query or current_query
                current_filters = result.filters or current_filters

        # Use processed query and filters
        question = current_query
        filter = current_filters

        # Generate query embedding (uses embed_query for providers that differentiate)
        query_embedding = self.embedding_provider.embed_query(question)

        # Sanitize filter: remove reserved keys that conflict with explicit parameters
        sanitized_filter = None
        if filter:
            reserved_keys = {'namespace', '_type'}  # namespace handled separately, _type is internal
            sanitized_filter = {k: v for k, v in filter.items() if k not in reserved_keys}
            removed = set(filter.keys()) - set(sanitized_filter.keys())
            if removed:
                logger.warning(f"Removed reserved keys from filter: {removed}")
            if not sanitized_filter:
                sanitized_filter = None

        # Search vector DB - fetch more results if reranking
        search_top_k = top_k * 3 if rerank else top_k
        results = self.documents_provider.search(
            query_vector=query_embedding,
            top_k=search_top_k,
            namespace=ns,
            filter=sanitized_filter
        )

        # Format sources - include namespace in metadata for downstream consumers
        sources = [
            {
                "text": result["text"],
                "content": result["text"],  # Alias for LLM providers expecting 'content'
                "metadata": {**result["metadata"], "namespace": result.get("namespace", "default")},
                "score": result.get("score", 0)
            }
            for result in results
        ]

        # Convert to SearchResult objects for result processors
        from stache_ai.middleware.results import SearchResult
        search_results = [
            SearchResult(
                text=s["text"],
                score=s["score"],
                metadata=s["metadata"],
                vector_id=s.get("id", "")
            )
            for s in sources
        ]

        # Apply result processor middleware
        for processor in self.result_processors:
            from stache_ai.middleware.chain import MiddlewareRejection
            result = await processor.process(search_results, query_context)
            if result.action == "reject":
                raise MiddlewareRejection(processor.__class__.__name__, result.reason)
            if result.action == "allow" and result.results is not None:
                search_results = result.results

        # Convert back to dict format for response
        sources = [
            {
                "text": r.text,
                "content": r.text,
                "metadata": r.metadata,
                "score": r.score
            }
            for r in search_results
        ]

        # Apply reranking if requested
        if rerank and sources and self.reranker_provider:
            logger.info(f"Reranking {len(sources)} results")
            sources = self.reranker_provider.rerank(question, sources, top_k=top_k)
        elif rerank and not self.reranker_provider:
            logger.warning("Reranking requested but no reranker configured")
            sources = sources[:top_k]
        else:
            sources = sources[:top_k]

        response = {
            "question": question,
            "sources": sources,
            "namespace": ns,
            "reranked": rerank and self.reranker_provider is not None
        }

        # Optionally synthesize answer
        if synthesize and sources:
            # Use custom model if specified, otherwise use default provider
            if model:
                answer = self.llm_provider.generate_with_context_and_model(
                    query=question,
                    context=sources,
                    model_id=model
                )
                response["model"] = model
            else:
                answer = self.llm_provider.generate_with_context(
                    query=question,
                    context=sources
                )
            response["answer"] = answer

        return response

    def search(
        self,
        query: str,
        top_k: int = 5,
        namespace: str | None = None
    ) -> dict[str, Any]:
        """
        Search without LLM synthesis (faster)

        Args:
            query: Search query
            top_k: Number of results
            namespace: Optional namespace to search within

        Returns:
            Search results
        """
        return self.query(query, top_k=top_k, synthesize=False, namespace=namespace)

    def create_insight(
        self,
        content: str,
        namespace: str,
        tags: list[str] | None = None
    ) -> dict[str, Any]:
        """
        Create a new insight (user note with semantic search capability)

        Args:
            content: The insight content text
            namespace: Namespace for organizing insights
            tags: Optional tags for categorization

        Returns:
            Dictionary with insight_id and other metadata
        """
        logger.info(f"Creating insight in namespace: {namespace}")

        # Generate insight ID
        insight_id = str(uuid.uuid4())

        # Generate embedding for the insight content
        embedding = self.embedding_provider.embed(content)

        # Build metadata
        from datetime import datetime, timezone
        created_at = datetime.now(timezone.utc).isoformat()
        metadata = {
            "namespace": namespace,
            "created_at": created_at,
            "_type": "insight"
        }

        # Only include tags if provided and not empty
        if tags:
            metadata["tags"] = tags

        # Insert into insights provider
        ids = self.insights_provider.insert(
            vectors=[embedding],
            texts=[content],
            metadatas=[metadata],
            ids=[insight_id],
            namespace=namespace
        )

        logger.info(f"Created insight {insight_id} in namespace {namespace}")

        return {
            "insight_id": insight_id,
            "success": True,
            "namespace": namespace,
            "created_at": created_at,
            "tags": tags
        }

    def search_insights(
        self,
        query: str,
        namespace: str,
        top_k: int = 10
    ) -> dict[str, Any]:
        """
        Search insights using semantic search

        Args:
            query: Search query text
            namespace: Namespace to search within
            top_k: Maximum number of results to return

        Returns:
            Dictionary with search results
        """
        logger.info(f"Searching insights in namespace: {namespace} with query: {query}")

        # Generate embedding for the query
        query_embedding = self.embedding_provider.embed(query)

        # Search insights provider
        results = self.insights_provider.search(
            query_vector=query_embedding,
            top_k=top_k,
            namespace=namespace,
            filter={"_type": "insight"}
        )

        logger.info(f"Found {len(results)} insights matching query")

        return {"insights": results, "count": len(results)}

    def delete_insight(
        self,
        insight_id: str,
        namespace: str
    ) -> dict[str, Any]:
        """
        Delete an insight by ID

        Args:
            insight_id: The insight ID to delete
            namespace: Namespace containing the insight

        Returns:
            Dictionary with deletion status
        """
        logger.info(f"Deleting insight {insight_id} from namespace {namespace}")

        # Delete from insights provider by ID
        result = self.insights_provider.delete(
            ids=[insight_id],
            namespace=namespace
        )

        logger.info(f"Deleted insight {insight_id}")

        return {
            "success": True,
            "insight_id": insight_id,
            "namespace": namespace
        }

    def get_providers_info(self) -> dict[str, str]:
        """Get information about current providers"""
        info = {
            "embedding_provider": self.embedding_provider.get_name(),
            "llm_provider": self.llm_provider.get_name(),
            "vectordb_provider": self.vectordb_provider.get_name(),
            "embedding_dimensions": self.embedding_provider.get_dimensions(),
        }

        # Add separate index providers if using s3vectors
        if self.config.vectordb_provider == "s3vectors":
            info["documents_provider"] = self.documents_provider.get_name()
            info["summaries_provider"] = self.summaries_provider.get_name()
            info["insights_provider"] = self.insights_provider.get_name()

        return info

    async def delete_document(
        self,
        doc_id: str,
        namespace: str,
        context: "RequestContext | None" = None
    ) -> dict[str, Any]:
        """
        Delete a document by ID

        Args:
            doc_id: The document ID to delete
            namespace: Namespace containing the document
            context: Optional request context for middleware (created if not provided)

        Returns:
            Dictionary with deletion status
        """
        logger.info(f"Deleting document {doc_id} from namespace {namespace}")

        # Create request context if not provided
        if context is None:
            from datetime import datetime, timezone
            from uuid import uuid4
            from stache_ai.middleware.context import RequestContext
            context = RequestContext(
                request_id=str(uuid4()),
                timestamp=datetime.now(timezone.utc),
                namespace=namespace,
                source="api"
            )

        # Create delete target
        from stache_ai.middleware.base import DeleteTarget
        target = DeleteTarget(
            target_type="document",
            doc_id=doc_id,
            namespace=namespace
        )

        # Call delete observers (pre-delete)
        for observer in self.delete_observers:
            from stache_ai.middleware.chain import MiddlewareRejection
            result = await observer.on_delete(target, context)
            if result.action == "reject":
                raise MiddlewareRejection(observer.__class__.__name__, result.reason)

        # Delete from document index (if enabled)
        if self.document_index_provider:
            try:
                self.document_index_provider.delete_document(doc_id, namespace)
                logger.info(f"Deleted document index entry for {doc_id}")
            except Exception as e:
                logger.error(f"Failed to delete document index for {doc_id}: {e}")

        # Delete chunks from vector DB
        # Query for all chunks belonging to this document
        filter_dict = {"doc_id": doc_id}

        # For providers that support metadata filtering, delete by filter
        # Otherwise, we'd need to query first to get IDs (not implemented here)
        try:
            # Delete chunks with this doc_id
            self.documents_provider.delete(
                namespace=namespace,
                filter=filter_dict
            )
            logger.info(f"Deleted document chunks for {doc_id}")
        except Exception as e:
            logger.error(f"Failed to delete document chunks for {doc_id}: {e}")
            raise

        # Delete summary if exists
        try:
            # Query for summary with this doc_id
            summary_filter = {"_type": "document_summary", "doc_id": doc_id}
            self.summaries_provider.delete(
                namespace=namespace,
                filter=summary_filter
            )
            logger.info(f"Deleted document summary for {doc_id}")
        except Exception as e:
            # Non-critical - log and continue
            logger.warning(f"Failed to delete document summary for {doc_id}: {e}")

        # Call delete observers (post-delete)
        for observer in self.delete_observers:
            try:
                await observer.on_delete_complete(target, context)
            except Exception as e:
                logger.error(f"Delete observer {observer.__class__.__name__} on_delete_complete failed: {e}")

        return {
            "success": True,
            "doc_id": doc_id,
            "namespace": namespace
        }


# Global pipeline instance with thread-safe initialization
_pipeline: RAGPipeline | None = None
_pipeline_lock = threading.Lock()


def get_pipeline() -> RAGPipeline:
    """Get or create global pipeline instance (thread-safe)"""
    global _pipeline
    if _pipeline is None:
        with _pipeline_lock:
            # Double-check pattern
            if _pipeline is None:
                _pipeline = RAGPipeline()
    return _pipeline

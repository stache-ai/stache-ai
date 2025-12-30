"""Configuration management for Stache - Extensible provider architecture"""

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings with support for multiple providers.

    Provider Selection:
        Provider names are strings that map to entry points. Available providers
        depend on which stache-ai-* packages are installed. Core provides:
        - LLM: fallback
        - Embedding: fallback
        - VectorDB: (none built-in, requires plugin)
        - Namespace: sqlite
        - Reranker: simple

    Install additional providers:
        pip install stache-ai-bedrock  # Adds bedrock LLM and embedding
        pip install stache-ai-qdrant   # Adds qdrant vectordb
    """

    # ===== Provider Selection =====
    # String-based to support dynamic plugin discovery
    llm_provider: str = Field(
        default="fallback",
        description="LLM provider name (discovered via stache.llm entry points)"
    )
    llm_model: str | None = None

    # ===== Ollama Configuration =====
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    ollama_embedding_model: str = "mxbai-embed-large"

    # ===== Ollama Robustness Configuration =====
    # Timeouts
    ollama_embedding_timeout: float = 90.0  # Increased for large batches
    ollama_llm_timeout: float = 120.0  # LLM generation timeout
    ollama_health_check_timeout: float = 5.0  # Health check timeout

    # Retry configuration
    ollama_max_retries: int = 3  # Max retry attempts
    ollama_retry_base_delay: float = 1.0  # Base delay for exponential backoff
    ollama_retry_max_delay: float = 10.0  # Cap retry delay

    # Parallel processing
    ollama_batch_size: int = 10  # Max concurrent embedding requests
    ollama_enable_parallel: bool = True  # Feature flag

    # Circuit breaker
    ollama_circuit_breaker_threshold: int = 15  # Failures before opening (increased for batch workloads)
    ollama_circuit_breaker_timeout: float = 60.0  # Recovery window (seconds)
    ollama_circuit_breaker_half_open_max_calls: int = 3  # Test calls in half-open state

    # Connection pool
    ollama_max_connections: int = 50  # Total connection limit
    ollama_max_keepalive_connections: int = 20  # Persistent connections
    ollama_keepalive_expiry: float = 30.0  # Seconds

    # ===== Fallback Provider Configuration =====
    fallback_primary: Literal["ollama", "openai", "anthropic"] = "ollama"
    fallback_secondary: Literal["ollama", "openai", "anthropic"] = "anthropic"

    # ===== Embedding Provider =====
    embedding_provider: str = Field(
        default="openai",
        description="Embedding provider name (discovered via stache.embeddings entry points)"
    )
    embedding_model: str | None = None
    embedding_dimension: int = 1536

    # ===== Embedding Fallback Configuration =====
    embedding_fallback_primary: Literal["ollama", "openai", "cohere", "mixedbread"] = "ollama"
    embedding_fallback_secondary: Literal["ollama", "openai", "cohere", "mixedbread"] = "mixedbread"

    # ===== Auto-split Embedding Configuration =====
    embedding_auto_split_enabled: bool = Field(
        default=True,
        description="Enable automatic splitting of oversized embedding chunks"
    )

    embedding_auto_split_max_depth: int = Field(
        default=4,
        ge=1,
        le=10,
        description="Maximum split recursion depth (4 = up to 16 sub-chunks)"
    )

    # ===== Vector Database Provider =====
    vectordb_provider: str = Field(
        default="qdrant",
        description="Vector database provider name (discovered via stache.vectordb entry points)"
    )

    # ===== Mixedbread Configuration =====
    mixedbread_api_key: str | None = None
    mixedbread_model: str = "mxbai-embed-large-v1"

    # Mixedbread resilience settings
    mixedbread_timeout: float = 60.0
    mixedbread_max_retries: int = 3
    mixedbread_retry_base_delay: float = 1.0
    mixedbread_retry_max_delay: float = 10.0
    mixedbread_circuit_breaker_threshold: int = 10
    mixedbread_circuit_breaker_timeout: float = 60.0
    mixedbread_circuit_breaker_half_open_max_calls: int = 3
    mixedbread_max_connections: int = 50
    mixedbread_max_keepalive_connections: int = 20
    mixedbread_keepalive_expiry: float = 30.0

    # ===== API Keys =====
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    cohere_api_key: str | None = None

    # ===== Qdrant Configuration =====
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "stache"

    # ===== Namespace Configuration =====
    default_namespace: str | None = None  # Optional default namespace for multi-user setups
    namespace_provider: str = Field(
        default="sqlite",
        description="Namespace registry provider name (discovered via stache.namespace entry points)"
    )
    namespace_db_path: str = "data/namespaces.db"  # Path to SQLite database for namespaces

    # ===== Redis Configuration (for namespace provider) =====
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str | None = None
    redis_db: int = 0  # Redis database number (0-15)

    # ===== MongoDB Configuration (for namespace and document index providers) =====
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_database: str = "stache"
    mongodb_namespace_collection: str = "namespaces"
    mongodb_documents_collection: str = "documents"

    # ===== Pinecone Configuration =====
    pinecone_api_key: str | None = None
    pinecone_index: str = "stache"
    pinecone_namespace: str | None = None
    pinecone_cloud: str = "aws"
    pinecone_region: str = "us-east-1"

    # ===== Chroma Configuration =====
    chroma_collection: str = "stache"
    # For embedded mode (local)
    chroma_persist_directory: str | None = None  # Default: ./data/chroma
    # For client/server mode (HTTP)
    chroma_host: str | None = None  # e.g., "localhost" or "chroma.example.com"
    chroma_port: int = 8000
    chroma_ssl: bool = False
    chroma_api_key: str | None = None

    # ===== AWS Configuration =====
    aws_region: str = "us-east-1"

    # ===== S3 Vectors Configuration =====
    s3vectors_bucket: str | None = None  # Vector bucket name
    s3vectors_index: str = "stache"  # DEPRECATED: Use specific indexes below. Kept for backward compatibility.
    s3vectors_documents_index: str | None = None  # Index for document chunks
    s3vectors_summaries_index: str | None = None  # Index for document summaries
    s3vectors_insights_index: str | None = None  # Index for user insights

    # ===== DynamoDB Configuration =====
    dynamodb_namespace_table: str = "stache-namespaces"  # Table for namespace registry
    document_index_provider: str = Field(
        default="dynamodb",
        description="Document index provider name (discovered via stache.document_index entry points)"
    )
    dynamodb_documents_table: str = Field(default="stache-documents", description="DynamoDB table name for document index")

    # ===== Bedrock Configuration =====
    bedrock_llm_model: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"
    bedrock_embedding_model: str = "amazon.titan-embed-text-v2:0"

    # ===== Reranker Configuration =====
    reranker_provider: str = Field(
        default="simple",
        description="Reranker provider name (discovered via stache.reranker entry points)"
    )
    reranker_model: str = "qllama/bge-reranker-v2-m3"  # For Ollama reranker
    reranker_dedupe_threshold: float = 0.85  # For simple reranker: similarity threshold for deduplication

    # ===== Chunking Configuration =====
    # Available strategies: recursive, markdown, semantic, character, transcript
    default_chunking_strategy: Literal["recursive", "markdown", "semantic", "character", "transcript"] = "recursive"
    chunk_size: int = 2000  # Target size for content (before metadata prefix)
    chunk_overlap: int = 200  # Overlap between chunks for context continuity
    chunk_max_size: int = 2500  # Hard limit including metadata prefix
    chunk_metadata_reserve: int = 300  # Reserved space for prepended metadata (e.g., speaker, topic)

    # ===== Middleware Configuration =====
    # Enrichment
    enrichment_enabled: bool = True
    enrichment_auto_detect: bool = True  # Auto-detect content type
    enrichment_plugins: list[str] | None = None  # Whitelist, None = all

    # Audio transcription (lazy loaded, optional dependency)
    whisper_model: str = "base"
    whisper_enabled: bool = False  # Must explicitly enable

    # Middleware chain behavior
    middleware_default_on_error: Literal["allow", "reject", "skip"] = "reject"
    middleware_timeout_seconds: float | None = None  # Global default timeout

    # Observability
    middleware_log_level: str = "INFO"
    middleware_emit_metrics: bool = True

    # ===== Application Settings =====
    log_level: str = "info"
    upload_dir: str = "uploads"
    queue_dir: str = "/data/queue"  # Shared directory for pending uploads from dropbox

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"  # Ignore unknown fields from .env to handle old config variables

    def get_llm_model(self) -> str:
        """Get LLM model name based on provider"""
        if self.llm_model:
            return self.llm_model

        defaults = {
            "anthropic": "claude-3-7-sonnet-20250219",
            "openai": "gpt-4-turbo-preview",
            "ollama": self.ollama_model,
            "bedrock": self.bedrock_llm_model,
            "fallback": self.ollama_model,  # Primary model for fallback
        }
        return defaults.get(self.llm_provider, "claude-3-7-sonnet-20250219")

    def get_embedding_model(self) -> str:
        """Get embedding model name based on provider"""
        if self.embedding_model:
            return self.embedding_model

        defaults = {
            "openai": "text-embedding-3-small",
            "cohere": "embed-english-v3.0",
            "ollama": self.ollama_embedding_model,
            "mixedbread": self.mixedbread_model,
            "bedrock": self.bedrock_embedding_model,
            "fallback": self.ollama_embedding_model,  # Primary model for fallback
        }
        return defaults.get(self.embedding_provider, "text-embedding-3-small")

    def get_embedding_dimensions(self) -> int:
        """Get embedding dimensions based on provider/model"""
        dimension_map = {
            "openai": {
                "text-embedding-3-small": 1536,
                "text-embedding-3-large": 3072,
            },
            "cohere": {
                "embed-english-v3.0": 1024,
            },
            "ollama": {
                "mxbai-embed-large": 1024,
                "nomic-embed-text": 768,
                "all-minilm": 384,
                "snowflake-arctic-embed": 1024,
                "bge-large": 1024,
                "bge-m3": 1024,
            },
            "mixedbread": {
                "mxbai-embed-large-v1": 1024,
                "deepset-mxbai-embed-de-large-v1": 1024,
                "mxbai-embed-2d-large-v1": 1024,
            },
            "bedrock": {
                "amazon.titan-embed-text-v1": 1536,
                "amazon.titan-embed-text-v2:0": 1024,
                "cohere.embed-english-v3": 1024,
                "cohere.embed-multilingual-v3": 1024,
            },
        }

        # For fallback, use primary provider's dimensions
        provider = self.embedding_provider
        if provider == "fallback":
            provider = self.embedding_fallback_primary

        provider_models = dimension_map.get(provider, {})
        model = self.get_embedding_model()
        return provider_models.get(model, self.embedding_dimension)

    def validate_aws_config(self) -> None:
        """Validate AWS-specific configuration when AWS providers are selected

        Raises:
            ValueError: If required AWS settings are missing for selected providers
        """
        errors = []

        # Check S3 Vectors configuration
        if self.vectordb_provider == "s3vectors":
            if not self.s3vectors_bucket:
                errors.append(
                    "S3VECTORS_BUCKET environment variable is required when vectordb_provider='s3vectors'"
                )

        # Check DynamoDB configuration
        if self.namespace_provider == "dynamodb":
            if not self.dynamodb_namespace_table:
                errors.append(
                    "DYNAMODB_NAMESPACE_TABLE environment variable is required when namespace_provider='dynamodb'"
                )

        # Check Bedrock configuration
        if self.llm_provider == "bedrock" or self.embedding_provider == "bedrock":
            if not self.aws_region:
                errors.append(
                    "AWS_REGION environment variable is required when using Bedrock providers"
                )

        if errors:
            raise ValueError(
                "AWS configuration validation failed:\n  - " + "\n  - ".join(errors)
            )


# Global settings instance
settings = Settings()

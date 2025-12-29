"""Tests for configuration module"""


import pytest


class TestSettings:
    """Tests for Settings configuration class"""

    def test_qdrant_defaults(self):
        """Test Qdrant default configuration"""
        from stache_ai.config import Settings

        settings = Settings()
        assert settings.qdrant_url == "http://localhost:6333"
        assert settings.qdrant_collection == "stache"

    def test_get_llm_model_default(self):
        """Test default LLM model selection"""
        from stache_ai.config import Settings

        # Anthropic provider
        settings = Settings(llm_provider="anthropic")
        assert "claude" in settings.get_llm_model()

        # OpenAI provider
        settings = Settings(llm_provider="openai")
        assert "gpt" in settings.get_llm_model()

        # Ollama provider
        settings = Settings(llm_provider="ollama")
        assert settings.get_llm_model() == "llama3.2"

    def test_get_llm_model_custom(self):
        """Test custom LLM model override"""
        from stache_ai.config import Settings

        settings = Settings(llm_provider="anthropic", llm_model="claude-3-opus")
        assert settings.get_llm_model() == "claude-3-opus"

    def test_get_embedding_model_default(self):
        """Test default embedding model selection"""
        from stache_ai.config import Settings

        # OpenAI provider
        settings = Settings(embedding_provider="openai")
        assert "embedding" in settings.get_embedding_model()

        # Cohere provider
        settings = Settings(embedding_provider="cohere")
        assert "embed" in settings.get_embedding_model()

    def test_get_embedding_model_custom(self):
        """Test custom embedding model override"""
        from stache_ai.config import Settings

        settings = Settings(embedding_provider="openai", embedding_model="custom-model")
        assert settings.get_embedding_model() == "custom-model"

    def test_get_embedding_dimensions_openai(self):
        """Test embedding dimensions for OpenAI models"""
        from stache_ai.config import Settings

        # text-embedding-3-small
        settings = Settings(embedding_provider="openai")
        settings.embedding_model = None  # Force default
        assert settings.get_embedding_dimensions() == 1536

    def test_get_embedding_dimensions_cohere(self):
        """Test embedding dimensions for Cohere models"""
        from stache_ai.config import Settings

        settings = Settings(embedding_provider="cohere")
        settings.embedding_model = "embed-english-v3.0"
        assert settings.get_embedding_dimensions() == 1024

    def test_get_embedding_dimensions_fallback(self):
        """Test embedding dimensions fallback to default"""
        from stache_ai.config import Settings

        settings = Settings(
            embedding_provider="openai",
            embedding_model="unknown-model",
            embedding_dimension=2048
        )
        assert settings.get_embedding_dimensions() == 2048

    def test_chroma_configuration(self):
        """Test Chroma configuration options"""
        from stache_ai.config import Settings

        settings = Settings(
            vectordb_provider="chroma",
            chroma_collection="test-collection",
            chroma_persist_directory="/data/chroma",
            chroma_host="localhost",
            chroma_port=8001,
            chroma_ssl=True
        )

        assert settings.chroma_collection == "test-collection"
        assert settings.chroma_persist_directory == "/data/chroma"
        assert settings.chroma_host == "localhost"
        assert settings.chroma_port == 8001
        assert settings.chroma_ssl is True

    def test_pinecone_configuration(self):
        """Test Pinecone configuration options"""
        from stache_ai.config import Settings

        settings = Settings(
            vectordb_provider="pinecone",
            pinecone_api_key="test-key",
            pinecone_index="test-index",
            pinecone_cloud="gcp",
            pinecone_region="us-central1"
        )

        assert settings.pinecone_api_key == "test-key"
        assert settings.pinecone_index == "test-index"
        assert settings.pinecone_cloud == "gcp"
        assert settings.pinecone_region == "us-central1"

    def test_fallback_provider_configuration(self):
        """Test fallback provider configuration"""
        from stache_ai.config import Settings

        settings = Settings(
            llm_provider="fallback",
            fallback_primary="ollama",
            fallback_secondary="anthropic"
        )

        assert settings.llm_provider == "fallback"
        assert settings.fallback_primary == "ollama"
        assert settings.fallback_secondary == "anthropic"

    def test_api_keys_optional(self, monkeypatch):
        """Test that API keys are optional"""
        from stache_ai.config import Settings

        # Clear any environment variables that might set API keys
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("COHERE_API_KEY", raising=False)

        settings = Settings()
        assert settings.anthropic_api_key is None
        assert settings.openai_api_key is None
        assert settings.cohere_api_key is None

    def test_log_level_default(self):
        """Test default log level"""
        from stache_ai.config import Settings

        settings = Settings()
        assert settings.log_level == "info"

    def test_upload_dir_default(self):
        """Test default upload directory"""
        from stache_ai.config import Settings

        settings = Settings()
        assert settings.upload_dir == "uploads"


class TestGlobalSettings:
    """Tests for global settings instance"""

    def test_global_settings_exists(self):
        """Test that global settings instance exists"""
        from stache_ai.config import settings

        assert settings is not None

    def test_global_settings_is_settings_instance(self):
        """Test that global settings is a Settings instance"""
        from stache_ai.config import Settings, settings

        assert isinstance(settings, Settings)


class TestAWSConfigValidation:
    """Tests for AWS configuration validation"""

    def test_validate_s3vectors_missing_bucket(self):
        """Should raise ValueError when S3 Vectors bucket is not configured"""
        from stache_ai.config import Settings

        settings = Settings(
            vectordb_provider="s3vectors",
            s3vectors_bucket=None  # Missing required config
        )

        with pytest.raises(ValueError) as exc_info:
            settings.validate_aws_config()

        assert "S3VECTORS_BUCKET" in str(exc_info.value)
        assert "required" in str(exc_info.value)

    def test_validate_dynamodb_missing_table(self):
        """Should raise ValueError when DynamoDB table is not configured"""
        from stache_ai.config import Settings

        settings = Settings(
            namespace_provider="dynamodb",
            dynamodb_namespace_table=""  # Missing required config
        )

        with pytest.raises(ValueError) as exc_info:
            settings.validate_aws_config()

        assert "DYNAMODB_NAMESPACE_TABLE" in str(exc_info.value)
        assert "required" in str(exc_info.value)

    def test_validate_bedrock_missing_region(self):
        """Should raise ValueError when Bedrock is used without AWS region"""
        from stache_ai.config import Settings

        settings = Settings(
            llm_provider="bedrock",
            aws_region=""  # Missing required config
        )

        with pytest.raises(ValueError) as exc_info:
            settings.validate_aws_config()

        assert "AWS_REGION" in str(exc_info.value)
        assert "required" in str(exc_info.value)

    def test_validate_bedrock_embedding_missing_region(self):
        """Should raise ValueError when Bedrock embeddings used without AWS region"""
        from stache_ai.config import Settings

        settings = Settings(
            embedding_provider="bedrock",
            aws_region=""
        )

        with pytest.raises(ValueError) as exc_info:
            settings.validate_aws_config()

        assert "AWS_REGION" in str(exc_info.value)

    def test_validate_multiple_aws_errors(self):
        """Should report all AWS configuration errors at once"""
        from stache_ai.config import Settings

        settings = Settings(
            vectordb_provider="s3vectors",
            namespace_provider="dynamodb",
            s3vectors_bucket=None,
            dynamodb_namespace_table=""
        )

        with pytest.raises(ValueError) as exc_info:
            settings.validate_aws_config()

        error_msg = str(exc_info.value)
        assert "S3VECTORS_BUCKET" in error_msg
        assert "DYNAMODB_NAMESPACE_TABLE" in error_msg

    def test_validate_aws_config_passes_when_configured(self):
        """Should pass validation when all AWS configs are present"""
        from stache_ai.config import Settings

        settings = Settings(
            vectordb_provider="s3vectors",
            namespace_provider="dynamodb",
            llm_provider="bedrock",
            embedding_provider="bedrock",
            s3vectors_bucket="test-bucket",
            dynamodb_namespace_table="test-table",
            aws_region="us-east-1"
        )

        # Should not raise
        settings.validate_aws_config()

    def test_validate_non_aws_providers_skipped(self):
        """Should not validate when non-AWS providers are used"""
        from stache_ai.config import Settings

        settings = Settings(
            vectordb_provider="qdrant",
            namespace_provider="sqlite",
            llm_provider="anthropic"
        )

        # Should not raise even though AWS configs are missing
        settings.validate_aws_config()

    def test_aws_defaults(self):
        """Test AWS default configuration values"""
        from stache_ai.config import Settings

        settings = Settings()
        assert settings.aws_region == "us-east-1"
        assert settings.s3vectors_index == "stache"
        assert settings.dynamodb_namespace_table == "stache-namespaces"
        assert settings.bedrock_llm_model == "anthropic.claude-3-5-sonnet-20241022-v2:0"
        assert settings.bedrock_embedding_model == "amazon.titan-embed-text-v2:0"

    def test_bedrock_model_in_get_llm_model(self):
        """Test Bedrock model in get_llm_model"""
        from stache_ai.config import Settings

        settings = Settings(llm_provider="bedrock")
        model = settings.get_llm_model()
        assert "anthropic.claude" in model or "claude" in model.lower()

    def test_bedrock_model_in_get_embedding_model(self):
        """Test Bedrock model in get_embedding_model"""
        from stache_ai.config import Settings

        settings = Settings(embedding_provider="bedrock")
        model = settings.get_embedding_model()
        assert "titan" in model.lower() or "amazon" in model.lower()

    def test_bedrock_embedding_dimensions(self):
        """Test embedding dimensions for Bedrock models"""
        from stache_ai.config import Settings

        # Titan v2
        settings = Settings(
            embedding_provider="bedrock",
            bedrock_embedding_model="amazon.titan-embed-text-v2:0"
        )
        assert settings.get_embedding_dimensions() == 1024

        # Cohere on Bedrock
        settings = Settings(
            embedding_provider="bedrock",
            bedrock_embedding_model="cohere.embed-english-v3"
        )
        assert settings.get_embedding_dimensions() == 1024

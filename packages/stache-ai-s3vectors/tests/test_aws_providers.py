"""Tests for AWS providers (S3 Vectors, DynamoDB, Bedrock)"""

import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from botocore.exceptions import ClientError

from stache_ai.config import Settings


def make_client_error(code: str, message: str = "Error") -> ClientError:
    """Helper to create ClientError exceptions"""
    return ClientError(
        {"Error": {"Code": code, "Message": message}},
        "TestOperation"
    )


class TestS3VectorsProvider:
    """Tests for S3VectorsProvider"""

    @pytest.fixture
    def mock_settings(self):
        """Create settings for S3 Vectors"""
        return Settings(
            vectordb_provider="s3vectors",
            s3vectors_bucket="test-bucket",
            s3vectors_index="test-index",
            aws_region="us-east-1",
            embedding_dimension=1024
        )

    @pytest.fixture
    def mock_boto_client(self):
        """Create a mock boto3 client"""
        with patch("boto3.client") as mock_client:
            client_instance = MagicMock()
            mock_client.return_value = client_instance
            yield client_instance

    def test_init_validates_infrastructure(self, mock_settings, mock_boto_client):
        """Should validate bucket and index exist on init"""
        from stache_s3vectors.provider import S3VectorsProvider

        mock_boto_client.get_vector_bucket.return_value = {}
        mock_boto_client.get_index.return_value = {}

        provider = S3VectorsProvider(mock_settings)

        mock_boto_client.get_vector_bucket.assert_called_once_with(
            vectorBucketName="test-bucket"
        )
        mock_boto_client.get_index.assert_called_once_with(
            vectorBucketName="test-bucket",
            indexName="test-index"
        )

    def test_init_raises_on_missing_bucket(self, mock_settings, mock_boto_client):
        """Should raise ValueError if bucket doesn't exist"""
        from stache_s3vectors.provider import S3VectorsProvider

        mock_boto_client.get_vector_bucket.side_effect = make_client_error(
            "ResourceNotFoundException"
        )

        with pytest.raises(ValueError) as exc_info:
            S3VectorsProvider(mock_settings)

        assert "not found" in str(exc_info.value)
        assert "test-bucket" in str(exc_info.value)

    def test_init_raises_on_missing_index(self, mock_settings, mock_boto_client):
        """Should raise ValueError if index doesn't exist"""
        from stache_s3vectors.provider import S3VectorsProvider

        mock_boto_client.get_vector_bucket.return_value = {}
        mock_boto_client.get_index.side_effect = make_client_error(
            "ResourceNotFoundException"
        )

        with pytest.raises(ValueError) as exc_info:
            S3VectorsProvider(mock_settings)

        assert "not found" in str(exc_info.value)
        assert "test-index" in str(exc_info.value)

    def test_init_raises_on_missing_bucket_config(self, mock_boto_client):
        """Should raise ValueError if bucket not configured"""
        from stache_s3vectors.provider import S3VectorsProvider

        settings = Settings(
            vectordb_provider="s3vectors",
            s3vectors_bucket=None,
            aws_region="us-east-1"
        )

        with pytest.raises(ValueError) as exc_info:
            S3VectorsProvider(settings)

        assert "S3VECTORS_BUCKET" in str(exc_info.value)

    def test_insert_vectors(self, mock_settings, mock_boto_client):
        """Should insert vectors with metadata"""
        from stache_s3vectors.provider import S3VectorsProvider

        mock_boto_client.get_vector_bucket.return_value = {}
        mock_boto_client.get_index.return_value = {}

        provider = S3VectorsProvider(mock_settings)

        vectors = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        texts = ["text1", "text2"]
        metadatas = [{"key": "value1"}, {"key": "value2"}]

        ids = provider.insert(vectors, texts, metadatas, namespace="test-ns")

        assert len(ids) == 2
        mock_boto_client.put_vectors.assert_called_once()

    def test_search_vectors(self, mock_settings, mock_boto_client):
        """Should search vectors and return results"""
        from stache_s3vectors.provider import S3VectorsProvider

        mock_boto_client.get_vector_bucket.return_value = {}
        mock_boto_client.get_index.return_value = {}
        mock_boto_client.query_vectors.return_value = {
            "vectors": [
                {
                    "key": "id1",
                    "distance": 0.05,  # S3 Vectors returns distance, not score
                    "metadata": {
                        "text": "test content",
                        "namespace": "test-ns",
                    }
                }
            ]
        }

        provider = S3VectorsProvider(mock_settings)
        results = provider.search([0.1, 0.2, 0.3], top_k=5, namespace="test-ns")

        assert len(results) == 1
        assert results[0]["id"] == "id1"
        # Score is converted from distance: score = 1 - distance
        assert results[0]["score"] == 0.95
        assert results[0]["text"] == "test content"

    def test_delete_vectors(self, mock_settings, mock_boto_client):
        """Should delete vectors by IDs"""
        from stache_s3vectors.provider import S3VectorsProvider

        mock_boto_client.get_vector_bucket.return_value = {}
        mock_boto_client.get_index.return_value = {}

        provider = S3VectorsProvider(mock_settings)
        result = provider.delete(["id1", "id2"])

        assert result is True
        mock_boto_client.delete_vectors.assert_called_once()

    def test_get_collection_info(self, mock_settings, mock_boto_client):
        """Should return index info"""
        from stache_s3vectors.provider import S3VectorsProvider

        mock_boto_client.get_vector_bucket.return_value = {}
        mock_boto_client.get_index.return_value = {
            "dimension": 1024,
            "distanceMetric": "cosine",
            "status": "ACTIVE"
        }

        provider = S3VectorsProvider(mock_settings)
        info = provider.get_collection_info()

        assert info["name"] == "test-index"
        assert info["bucket"] == "test-bucket"
        assert info["dimension"] == 1024


class TestDynamoDBNamespaceProvider:
    """Tests for DynamoDBNamespaceProvider"""

    @pytest.fixture
    def mock_settings(self):
        """Create settings for DynamoDB"""
        return Settings(
            namespace_provider="dynamodb",
            dynamodb_namespace_table="test-table",
            aws_region="us-east-1"
        )

    @pytest.fixture
    def mock_dynamodb(self):
        """Create mock DynamoDB resource and client"""
        with patch("boto3.resource") as mock_resource, \
             patch("boto3.client") as mock_client:
            # Mock resource
            resource_instance = MagicMock()
            table_mock = MagicMock()
            resource_instance.Table.return_value = table_mock
            resource_instance.meta.client.meta.region_name = "us-east-1"
            mock_resource.return_value = resource_instance

            # Mock client for describe_table
            client_instance = MagicMock()
            client_instance.describe_table.return_value = {
                "Table": {"TableStatus": "ACTIVE"}
            }
            mock_client.return_value = client_instance

            yield {"resource": resource_instance, "table": table_mock, "client": client_instance}

    def test_init_validates_table(self, mock_settings, mock_dynamodb):
        """Should validate table exists on init"""
        from stache_dynamodb.namespace import DynamoDBNamespaceProvider

        provider = DynamoDBNamespaceProvider(mock_settings)

        mock_dynamodb["client"].describe_table.assert_called_once_with(
            TableName="test-table"
        )

    def test_init_raises_on_missing_table(self, mock_settings, mock_dynamodb):
        """Should raise ValueError if table doesn't exist"""
        from stache_dynamodb.namespace import DynamoDBNamespaceProvider

        mock_dynamodb["client"].describe_table.side_effect = make_client_error(
            "ResourceNotFoundException"
        )

        with pytest.raises(ValueError) as exc_info:
            DynamoDBNamespaceProvider(mock_settings)

        assert "not found" in str(exc_info.value)
        assert "test-table" in str(exc_info.value)

    def test_init_raises_on_inactive_table(self, mock_settings, mock_dynamodb):
        """Should raise ValueError if table is not ACTIVE"""
        from stache_dynamodb.namespace import DynamoDBNamespaceProvider

        mock_dynamodb["client"].describe_table.return_value = {
            "Table": {"TableStatus": "CREATING"}
        }

        with pytest.raises(ValueError) as exc_info:
            DynamoDBNamespaceProvider(mock_settings)

        assert "not ACTIVE" in str(exc_info.value)

    def test_create_namespace(self, mock_settings, mock_dynamodb):
        """Should create a namespace"""
        from stache_dynamodb.namespace import DynamoDBNamespaceProvider

        mock_dynamodb["table"].put_item.return_value = {}

        # First call to exists() check - doesn't exist
        # Second call in create() after put_item - exists
        mock_dynamodb["table"].get_item.side_effect = [
            {},  # exists() check - doesn't exist
            {  # get() after create
                "Item": {
                    "id": "test-ns",
                    "name": "Test Namespace",
                    "description": "A test",
                    "parent_id": "__ROOT__",
                    "metadata": "{}",
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-01T00:00:00Z"
                }
            }
        ]

        provider = DynamoDBNamespaceProvider(mock_settings)

        result = provider.create("test-ns", "Test Namespace", "A test")

        assert result["id"] == "test-ns"
        assert result["name"] == "Test Namespace"
        mock_dynamodb["table"].put_item.assert_called_once()

    def test_get_namespace(self, mock_settings, mock_dynamodb):
        """Should get a namespace by ID"""
        from stache_dynamodb.namespace import DynamoDBNamespaceProvider

        mock_dynamodb["table"].get_item.return_value = {
            "Item": {
                "id": "test-ns",
                "name": "Test",
                "description": "",
                "parent_id": "__ROOT__",
                "metadata": "{}",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z"
            }
        }

        provider = DynamoDBNamespaceProvider(mock_settings)
        result = provider.get("test-ns")

        assert result["id"] == "test-ns"
        assert result["parent_id"] is None  # __ROOT__ converted to None

    def test_delete_namespace(self, mock_settings, mock_dynamodb):
        """Should delete a namespace"""
        from stache_dynamodb.namespace import DynamoDBNamespaceProvider

        # exists check
        mock_dynamodb["table"].get_item.return_value = {
            "Item": {"id": "test-ns"}
        }
        # no children
        mock_dynamodb["table"].query.return_value = {"Items": []}

        provider = DynamoDBNamespaceProvider(mock_settings)
        result = provider.delete("test-ns")

        assert result is True
        mock_dynamodb["table"].delete_item.assert_called_once()

    def test_update_namespace_name(self, mock_settings, mock_dynamodb):
        """Should update namespace name with reserved keyword handling"""
        from stache_dynamodb.namespace import DynamoDBNamespaceProvider

        # Mock existing namespace
        existing_item = {
            "id": "test-ns",
            "name": "Old Name",
            "description": "Test",
            "parent_id": "__ROOT__",
            "metadata": "{}",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z"
        }

        updated_item = existing_item.copy()
        updated_item["name"] = "New Name"

        mock_dynamodb["table"].get_item.side_effect = [
            {"Item": existing_item},  # First call in update()
            {"Item": updated_item}     # Second call at end of update()
        ]

        provider = DynamoDBNamespaceProvider(mock_settings)
        result = provider.update("test-ns", name="New Name")

        assert result["name"] == "New Name"

        # Verify ExpressionAttributeNames was used for reserved keyword
        call_args = mock_dynamodb["table"].update_item.call_args
        assert call_args.kwargs["ExpressionAttributeNames"]["#n"] == "name"
        assert call_args.kwargs["ExpressionAttributeValues"][":name"] == "New Name"

    def test_update_namespace_description(self, mock_settings, mock_dynamodb):
        """Should update namespace description"""
        from stache_dynamodb.namespace import DynamoDBNamespaceProvider

        existing_item = {
            "id": "test-ns",
            "name": "Test",
            "description": "Old Description",
            "parent_id": "__ROOT__",
            "metadata": "{}",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z"
        }

        updated_item = existing_item.copy()
        updated_item["description"] = "New Description"

        mock_dynamodb["table"].get_item.side_effect = [
            {"Item": existing_item},
            {"Item": updated_item}
        ]

        provider = DynamoDBNamespaceProvider(mock_settings)
        result = provider.update("test-ns", description="New Description")

        assert result is not None
        call_args = mock_dynamodb["table"].update_item.call_args
        assert call_args.kwargs["ExpressionAttributeNames"]["#desc"] == "description"

    def test_update_namespace_metadata(self, mock_settings, mock_dynamodb):
        """Should merge metadata when updating"""
        from stache_dynamodb.namespace import DynamoDBNamespaceProvider

        existing_item = {
            "id": "test-ns",
            "name": "Test",
            "description": "",
            "parent_id": "__ROOT__",
            "metadata": '{"key1": "value1"}',
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z"
        }

        mock_dynamodb["table"].get_item.side_effect = [
            {"Item": existing_item},
            {"Item": existing_item}
        ]

        provider = DynamoDBNamespaceProvider(mock_settings)
        result = provider.update("test-ns", metadata={"key2": "value2"})

        # Verify metadata was merged
        call_args = mock_dynamodb["table"].update_item.call_args
        import json
        merged_metadata = json.loads(call_args.kwargs["ExpressionAttributeValues"][":meta"])
        assert "key1" in merged_metadata
        assert "key2" in merged_metadata

    def test_update_namespace_parent_validation(self, mock_settings, mock_dynamodb):
        """Should validate parent exists when updating parent_id"""
        from stache_dynamodb.namespace import DynamoDBNamespaceProvider

        existing_item = {
            "id": "test-ns",
            "name": "Test",
            "description": "",
            "parent_id": "__ROOT__",
            "metadata": "{}",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z"
        }

        mock_dynamodb["table"].get_item.side_effect = [
            {"Item": existing_item},  # exists check for namespace
            {}                        # parent doesn't exist
        ]

        provider = DynamoDBNamespaceProvider(mock_settings)

        with pytest.raises(ValueError) as exc_info:
            provider.update("test-ns", parent_id="nonexistent-parent")

        assert "Parent namespace not found" in str(exc_info.value)

    def test_update_namespace_self_parent_validation(self, mock_settings, mock_dynamodb):
        """Should prevent namespace from being its own parent"""
        from stache_dynamodb.namespace import DynamoDBNamespaceProvider

        existing_item = {
            "id": "test-ns",
            "name": "Test",
            "description": "",
            "parent_id": "__ROOT__",
            "metadata": "{}",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z"
        }

        mock_dynamodb["table"].get_item.return_value = {"Item": existing_item}

        provider = DynamoDBNamespaceProvider(mock_settings)

        with pytest.raises(ValueError) as exc_info:
            provider.update("test-ns", parent_id="test-ns")

        assert "cannot be its own parent" in str(exc_info.value)

    def test_list_namespaces_all(self, mock_settings, mock_dynamodb):
        """Should list all root namespaces when no parent specified"""
        from stache_dynamodb.namespace import DynamoDBNamespaceProvider

        # list() with no args queries for parent_id="__ROOT__", not scan
        mock_dynamodb["table"].query.return_value = {
            "Items": [
                {
                    "id": "ns1",
                    "name": "Namespace 1",
                    "description": "",
                    "parent_id": "__ROOT__",
                    "metadata": "{}",
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-01T00:00:00Z"
                },
                {
                    "id": "ns2",
                    "name": "Namespace 2",
                    "description": "",
                    "parent_id": "__ROOT__",
                    "metadata": "{}",
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-01T00:00:00Z"
                }
            ]
        }

        provider = DynamoDBNamespaceProvider(mock_settings)
        result = provider.list()

        assert len(result) == 2
        assert result[0]["id"] == "ns1"
        assert result[1]["id"] == "ns2"

    def test_list_namespaces_by_parent(self, mock_settings, mock_dynamodb):
        """Should list namespaces filtered by parent_id"""
        from stache_dynamodb.namespace import DynamoDBNamespaceProvider

        mock_dynamodb["table"].query.return_value = {
            "Items": [
                {
                    "id": "child1",
                    "name": "Child 1",
                    "description": "",
                    "parent_id": "parent-id",
                    "metadata": "{}",
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-01T00:00:00Z"
                }
            ]
        }

        provider = DynamoDBNamespaceProvider(mock_settings)
        result = provider.list(parent_id="parent-id")

        assert len(result) == 1
        assert result[0]["id"] == "child1"
        assert result[0]["parent_id"] == "parent-id"

    def test_get_ancestors(self, mock_settings, mock_dynamodb):
        """Should retrieve ancestor chain for a namespace"""
        from stache_dynamodb.namespace import DynamoDBNamespaceProvider

        # Mock hierarchy: root -> parent -> child
        mock_dynamodb["table"].get_item.side_effect = [
            # First call for child
            {
                "Item": {
                    "id": "child",
                    "name": "Child",
                    "parent_id": "parent",
                    "description": "",
                    "metadata": "{}",
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-01T00:00:00Z"
                }
            },
            # Second call for parent
            {
                "Item": {
                    "id": "parent",
                    "name": "Parent",
                    "parent_id": "__ROOT__",
                    "description": "",
                    "metadata": "{}",
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-01T00:00:00Z"
                }
            }
        ]

        provider = DynamoDBNamespaceProvider(mock_settings)
        ancestors = provider.get_ancestors("child")

        assert len(ancestors) == 1
        assert ancestors[0]["id"] == "parent"

    def test_get_path(self, mock_settings, mock_dynamodb):
        """Should build full path string for namespace"""
        from stache_dynamodb.namespace import DynamoDBNamespaceProvider

        # Mock hierarchy: root -> parent -> child
        mock_dynamodb["table"].get_item.side_effect = [
            # First call in get_ancestors (child)
            {
                "Item": {
                    "id": "child",
                    "name": "Child",
                    "parent_id": "parent",
                    "description": "",
                    "metadata": "{}",
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-01T00:00:00Z"
                }
            },
            # Second call in get_ancestors (parent)
            {
                "Item": {
                    "id": "parent",
                    "name": "Parent",
                    "parent_id": "__ROOT__",
                    "description": "",
                    "metadata": "{}",
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-01T00:00:00Z"
                }
            },
            # Third call in get_path (child)
            {
                "Item": {
                    "id": "child",
                    "name": "Child",
                    "parent_id": "parent",
                    "description": "",
                    "metadata": "{}",
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-01T00:00:00Z"
                }
            }
        ]

        provider = DynamoDBNamespaceProvider(mock_settings)
        path = provider.get_path("child")

        assert path == "Parent > Child"


class TestBedrockLLMProvider:
    """Tests for BedrockLLMProvider"""

    @pytest.fixture
    def mock_settings(self):
        """Create settings for Bedrock LLM"""
        return Settings(
            llm_provider="bedrock",
            bedrock_llm_model="anthropic.claude-3-5-sonnet-20241022-v2:0",
            aws_region="us-east-1"
        )

    @pytest.fixture
    def mock_boto_client(self):
        """Create a mock boto3 client"""
        with patch("boto3.client") as mock_client:
            client_instance = MagicMock()
            mock_client.return_value = client_instance
            yield client_instance

    def test_generate_via_converse_api(self, mock_settings, mock_boto_client):
        """Should generate text using the Converse API"""
        from stache_bedrock.llm import BedrockLLMProvider

        # Mock Converse API response format
        mock_boto_client.converse.return_value = {
            "output": {
                "message": {
                    "content": [{"text": "Generated response"}]
                }
            }
        }

        provider = BedrockLLMProvider(mock_settings)
        result = provider.generate("Test prompt")

        assert result == "Generated response"
        mock_boto_client.converse.assert_called_once()

    def test_generate_handles_access_denied(self, mock_settings, mock_boto_client):
        """Should raise RuntimeError on AccessDeniedException"""
        from stache_bedrock.llm import BedrockLLMProvider

        mock_boto_client.converse.side_effect = make_client_error(
            "AccessDeniedException", "Model not enabled"
        )

        provider = BedrockLLMProvider(mock_settings)

        with pytest.raises(RuntimeError) as exc_info:
            provider.generate("Test prompt")

        assert "Access denied" in str(exc_info.value)

    def test_generate_handles_throttling(self, mock_settings, mock_boto_client):
        """Should raise RuntimeError on ThrottlingException"""
        from stache_bedrock.llm import BedrockLLMProvider

        mock_boto_client.converse.side_effect = make_client_error(
            "ThrottlingException"
        )

        provider = BedrockLLMProvider(mock_settings)

        with pytest.raises(RuntimeError) as exc_info:
            provider.generate("Test prompt")

        assert "throttled" in str(exc_info.value)

    def test_generate_handles_validation_error(self, mock_settings, mock_boto_client):
        """Should raise ValueError on ValidationException"""
        from stache_bedrock.llm import BedrockLLMProvider

        mock_boto_client.converse.side_effect = make_client_error(
            "ValidationException", "Invalid input"
        )

        provider = BedrockLLMProvider(mock_settings)

        with pytest.raises(ValueError) as exc_info:
            provider.generate("Test prompt")

        assert "Invalid request" in str(exc_info.value)

    def test_generate_with_context(self, mock_settings, mock_boto_client):
        """Should generate answer with context"""
        from stache_bedrock.llm import BedrockLLMProvider

        mock_boto_client.converse.return_value = {
            "output": {
                "message": {
                    "content": [{"text": "Contextual answer"}]
                }
            }
        }

        provider = BedrockLLMProvider(mock_settings)
        result = provider.generate_with_context(
            "What is X?",
            [{"content": "X is a thing"}]
        )

        assert result == "Contextual answer"

    def test_get_available_models(self, mock_settings, mock_boto_client):
        """Should return curated list of Claude models"""
        from stache_bedrock.llm import BedrockLLMProvider, BEDROCK_CLAUDE_MODELS

        provider = BedrockLLMProvider(mock_settings)
        models = provider.get_available_models()

        # Should return the curated list
        assert models == BEDROCK_CLAUDE_MODELS
        assert len(models) > 0

        # Check structure of models
        for model in models:
            assert hasattr(model, 'id')
            assert hasattr(model, 'name')
            assert hasattr(model, 'provider')
            assert hasattr(model, 'tier')
            assert model.provider == "anthropic"
            assert model.tier in ["fast", "balanced", "premium"]

    def test_get_default_model(self, mock_settings, mock_boto_client):
        """Should return the configured model ID"""
        from stache_bedrock.llm import BedrockLLMProvider

        provider = BedrockLLMProvider(mock_settings)
        default = provider.get_default_model()

        assert default == mock_settings.bedrock_llm_model

    def test_generate_with_model(self, mock_settings, mock_boto_client):
        """Should generate using specified model via Converse API"""
        from stache_bedrock.llm import BedrockLLMProvider

        # Mock Converse API response
        mock_boto_client.converse.return_value = {
            "output": {
                "message": {
                    "content": [{"text": "Response from specific model"}]
                }
            }
        }

        provider = BedrockLLMProvider(mock_settings)
        result = provider.generate_with_model(
            "Test prompt",
            "us.anthropic.claude-3-haiku-20240307-v1:0"
        )

        assert result == "Response from specific model"
        mock_boto_client.converse.assert_called_once()
        call_args = mock_boto_client.converse.call_args
        assert call_args.kwargs['modelId'] == "us.anthropic.claude-3-haiku-20240307-v1:0"

    def test_generate_with_context_and_model(self, mock_settings, mock_boto_client):
        """Should generate with context using specified model"""
        from stache_bedrock.llm import BedrockLLMProvider

        mock_boto_client.converse.return_value = {
            "output": {
                "message": {
                    "content": [{"text": "Context answer with model"}]
                }
            }
        }

        provider = BedrockLLMProvider(mock_settings)
        result = provider.generate_with_context_and_model(
            "What is X?",
            [{"content": "X is something"}],
            "us.anthropic.claude-opus-4-20250514-v1:0"
        )

        assert result == "Context answer with model"
        call_args = mock_boto_client.converse.call_args
        assert call_args.kwargs['modelId'] == "us.anthropic.claude-opus-4-20250514-v1:0"


class TestBedrockEmbeddingProvider:
    """Tests for BedrockEmbeddingProvider"""

    @pytest.fixture
    def mock_settings_titan(self):
        """Create settings for Titan embeddings"""
        return Settings(
            embedding_provider="bedrock",
            bedrock_embedding_model="amazon.titan-embed-text-v2:0",
            aws_region="us-east-1"
        )

    @pytest.fixture
    def mock_settings_cohere(self):
        """Create settings for Cohere embeddings on Bedrock"""
        return Settings(
            embedding_provider="bedrock",
            bedrock_embedding_model="cohere.embed-english-v3",
            aws_region="us-east-1"
        )

    @pytest.fixture
    def mock_boto_client(self):
        """Create a mock boto3 client"""
        with patch("boto3.client") as mock_client:
            client_instance = MagicMock()
            mock_client.return_value = client_instance
            yield client_instance

    def test_embed_titan(self, mock_settings_titan, mock_boto_client):
        """Should embed text using Titan"""
        from stache_bedrock.embedding import BedrockEmbeddingProvider

        response_body = MagicMock()
        response_body.read.return_value = json.dumps({
            "embedding": [0.1, 0.2, 0.3]
        })
        mock_boto_client.invoke_model.return_value = {"body": response_body}

        provider = BedrockEmbeddingProvider(mock_settings_titan)
        result = provider.embed("Test text")

        assert result == [0.1, 0.2, 0.3]

    def test_embed_cohere_document(self, mock_settings_cohere, mock_boto_client):
        """Should embed document text using Cohere with search_document type"""
        from stache_bedrock.embedding import BedrockEmbeddingProvider

        response_body = MagicMock()
        response_body.read.return_value = json.dumps({
            "embeddings": [[0.1, 0.2, 0.3]]
        })
        mock_boto_client.invoke_model.return_value = {"body": response_body}

        provider = BedrockEmbeddingProvider(mock_settings_cohere)
        result = provider.embed("Test text")

        assert result == [0.1, 0.2, 0.3]

        # Verify input_type was search_document
        call_args = mock_boto_client.invoke_model.call_args
        body = json.loads(call_args.kwargs["body"])
        assert body["input_type"] == "search_document"

    def test_embed_query_cohere(self, mock_settings_cohere, mock_boto_client):
        """Should embed query text using Cohere with search_query type"""
        from stache_bedrock.embedding import BedrockEmbeddingProvider

        response_body = MagicMock()
        response_body.read.return_value = json.dumps({
            "embeddings": [[0.4, 0.5, 0.6]]
        })
        mock_boto_client.invoke_model.return_value = {"body": response_body}

        provider = BedrockEmbeddingProvider(mock_settings_cohere)
        result = provider.embed_query("Search query")

        assert result == [0.4, 0.5, 0.6]

        # Verify input_type was search_query
        call_args = mock_boto_client.invoke_model.call_args
        body = json.loads(call_args.kwargs["body"])
        assert body["input_type"] == "search_query"

    def test_embed_batch_titan(self, mock_settings_titan, mock_boto_client):
        """Should embed batch of texts using Titan (parallel for 3+ texts)"""
        from stache_bedrock.embedding import BedrockEmbeddingProvider
        import threading

        call_count = [0]
        lock = threading.Lock()

        def mock_invoke(*args, **kwargs):
            with lock:
                call_count[0] += 1
                idx = call_count[0]
            response_body = MagicMock()
            response_body.read.return_value = json.dumps({
                "embedding": [0.1 * idx] * 3
            })
            return {"body": response_body}

        mock_boto_client.invoke_model.side_effect = mock_invoke

        provider = BedrockEmbeddingProvider(mock_settings_titan)
        result = provider.embed_batch(["text1", "text2", "text3"])

        assert len(result) == 3
        assert mock_boto_client.invoke_model.call_count == 3

    def test_embed_batch_titan_parallel_preserves_order(self, mock_settings_titan, mock_boto_client):
        """Should preserve order of embeddings even with parallel execution"""
        from stache_bedrock.embedding import BedrockEmbeddingProvider
        import threading
        import time

        # Use different delays to ensure parallel execution could reorder
        delays = [0.02, 0.01, 0.03, 0.005, 0.015]
        call_count = [0]
        lock = threading.Lock()

        def mock_invoke(*args, **kwargs):
            body = json.loads(kwargs.get("body", "{}"))
            text = body.get("inputText", "")
            idx = int(text.replace("text", ""))  # Extract index from "text0", "text1", etc.

            # Simulate varying response times
            time.sleep(delays[idx] if idx < len(delays) else 0.01)

            response_body = MagicMock()
            response_body.read.return_value = json.dumps({
                "embedding": [float(idx)] * 3  # Embedding value matches input index
            })
            return {"body": response_body}

        mock_boto_client.invoke_model.side_effect = mock_invoke

        provider = BedrockEmbeddingProvider(mock_settings_titan)
        texts = [f"text{i}" for i in range(5)]
        result = provider.embed_batch(texts)

        # Verify order is preserved: result[i] should have embedding [i, i, i]
        for i, embedding in enumerate(result):
            assert embedding == [float(i)] * 3, f"Embedding at index {i} is incorrect"

    def test_embed_batch_titan_small_batch_sequential(self, mock_settings_titan, mock_boto_client):
        """Should use sequential processing for batches of 2 or fewer"""
        from stache_bedrock.embedding import BedrockEmbeddingProvider

        call_count = [0]

        def mock_invoke(*args, **kwargs):
            call_count[0] += 1
            response_body = MagicMock()
            response_body.read.return_value = json.dumps({
                "embedding": [0.1] * 3
            })
            return {"body": response_body}

        mock_boto_client.invoke_model.side_effect = mock_invoke

        provider = BedrockEmbeddingProvider(mock_settings_titan)

        # Small batch - should be sequential (no threading overhead)
        result = provider.embed_batch(["text1", "text2"])

        assert len(result) == 2
        assert mock_boto_client.invoke_model.call_count == 2

    def test_embed_batch_cohere(self, mock_settings_cohere, mock_boto_client):
        """Should embed batch of texts using Cohere (native batch)"""
        from stache_bedrock.embedding import BedrockEmbeddingProvider

        response_body = MagicMock()
        response_body.read.return_value = json.dumps({
            "embeddings": [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]
        })
        mock_boto_client.invoke_model.return_value = {"body": response_body}

        provider = BedrockEmbeddingProvider(mock_settings_cohere)
        result = provider.embed_batch(["text1", "text2", "text3"])

        assert len(result) == 3
        # Cohere uses native batch, so only one call
        assert mock_boto_client.invoke_model.call_count == 1

    def test_get_dimensions_titan_v2(self, mock_settings_titan, mock_boto_client):
        """Should return correct dimensions for Titan v2"""
        from stache_bedrock.embedding import BedrockEmbeddingProvider

        provider = BedrockEmbeddingProvider(mock_settings_titan)
        assert provider.get_dimensions() == 1024

    def test_get_dimensions_cohere(self, mock_settings_cohere, mock_boto_client):
        """Should return correct dimensions for Cohere"""
        from stache_bedrock.embedding import BedrockEmbeddingProvider

        provider = BedrockEmbeddingProvider(mock_settings_cohere)
        assert provider.get_dimensions() == 1024


class TestEmbedQueryBaseClass:
    """Tests for embed_query in base EmbeddingProvider"""

    def test_embed_query_defaults_to_embed(self):
        """Base class embed_query should call embed by default"""
        from stache_ai.providers.base import EmbeddingProvider

        class TestProvider(EmbeddingProvider):
            def __init__(self):
                self.embed_called_with = None

            def embed(self, text):
                self.embed_called_with = text
                return [0.1, 0.2, 0.3]

            def embed_batch(self, texts):
                return [[0.1, 0.2, 0.3] for _ in texts]

            def get_dimensions(self):
                return 3

        provider = TestProvider()
        result = provider.embed_query("test query")

        assert result == [0.1, 0.2, 0.3]
        assert provider.embed_called_with == "test query"


class TestCohereProviderEmbedQuery:
    """Tests for embed_query in Cohere provider"""

    @pytest.fixture
    def mock_cohere_client(self):
        """Create a mock Cohere client"""
        with patch("cohere.Client") as mock_client:
            client_instance = MagicMock()
            mock_client.return_value = client_instance
            yield client_instance

    def test_embed_uses_search_document(self, mock_cohere_client):
        """embed() should use input_type=search_document"""
        from stache_cohere.embedding import CohereEmbeddingProvider

        mock_cohere_client.embed.return_value = MagicMock(
            embeddings=[[0.1, 0.2, 0.3]]
        )

        settings = Settings(
            embedding_provider="cohere",
            cohere_api_key="test-key"
        )
        provider = CohereEmbeddingProvider(settings)
        provider.embed("test document")

        mock_cohere_client.embed.assert_called_once()
        call_kwargs = mock_cohere_client.embed.call_args.kwargs
        assert call_kwargs["input_type"] == "search_document"

    def test_embed_query_uses_search_query(self, mock_cohere_client):
        """embed_query() should use input_type=search_query"""
        from stache_cohere.embedding import CohereEmbeddingProvider

        mock_cohere_client.embed.return_value = MagicMock(
            embeddings=[[0.1, 0.2, 0.3]]
        )

        settings = Settings(
            embedding_provider="cohere",
            cohere_api_key="test-key"
        )
        provider = CohereEmbeddingProvider(settings)
        provider.embed_query("search query")

        mock_cohere_client.embed.assert_called_once()
        call_kwargs = mock_cohere_client.embed.call_args.kwargs
        assert call_kwargs["input_type"] == "search_query"


class TestS3VectorsMetadataValidation:
    """Tests for S3 Vectors metadata validation"""

    @pytest.fixture
    def mock_settings(self):
        return Settings(
            vectordb_provider="s3vectors",
            s3vectors_bucket="test-bucket",
            s3vectors_index="test-index",
            aws_region="us-east-1"
        )

    @pytest.fixture
    def mock_boto_client(self):
        with patch("boto3.client") as mock_client:
            client_instance = MagicMock()
            client_instance.get_vector_bucket.return_value = {}
            client_instance.get_index.return_value = {}
            mock_client.return_value = client_instance
            yield client_instance

    def test_metadata_key_limit_exceeded(self, mock_settings, mock_boto_client):
        """Should raise ValueError when metadata exceeds 50 key limit"""
        from stache_s3vectors.provider import S3VectorsProvider

        provider = S3VectorsProvider(mock_settings)

        # Create metadata with 49 keys (+ text + namespace = 51 total)
        large_metadata = {f"key{i}": f"value{i}" for i in range(49)}

        with pytest.raises(ValueError) as exc_info:
            provider.insert(
                vectors=[[0.1, 0.2]],
                texts=["test"],
                metadatas=[large_metadata]
            )

        assert "51 keys" in str(exc_info.value)
        assert "maximum is 50" in str(exc_info.value)

    def test_metadata_40kb_limit_exceeded(self, mock_settings, mock_boto_client):
        """Should raise ValueError when metadata exceeds 40KB total limit"""
        from stache_s3vectors.provider import S3VectorsProvider

        provider = S3VectorsProvider(mock_settings)

        # Create very large text that exceeds 40KB
        large_text = "x" * 50000  # 50KB text

        with pytest.raises(ValueError) as exc_info:
            provider.insert(
                vectors=[[0.1, 0.2]],
                texts=[large_text],
                metadatas=[{}]
            )

        assert "exceeds S3 Vectors limit of 40 KB" in str(exc_info.value)

    def test_metadata_2kb_warning(self, mock_settings, mock_boto_client):
        """Should raise ValueError when metadata exceeds 2KB filterable limit"""
        from stache_s3vectors.provider import S3VectorsProvider
        import pytest

        provider = S3VectorsProvider(mock_settings)

        # Create metadata that exceeds 2KB filterable limit
        # Each key-value pair takes space, and we need to exceed 2KB when serialized
        large_metadata = {f"key_{i}": "x" * 100 for i in range(30)}  # ~3KB of metadata

        with pytest.raises(ValueError) as exc_info:
            provider.insert(
                vectors=[[0.1, 0.2]],
                texts=["small"],
                metadatas=[large_metadata]
            )

        assert "exceeds S3 Vectors limit of 2KB" in str(exc_info.value)

    def test_metadata_within_limits(self, mock_settings, mock_boto_client):
        """Should succeed when metadata is within all limits"""
        from stache_s3vectors.provider import S3VectorsProvider

        provider = S3VectorsProvider(mock_settings)

        # Small metadata - should pass
        metadata = {"key1": "value1", "key2": 123}
        ids = provider.insert(
            vectors=[[0.1, 0.2]],
            texts=["small text"],
            metadatas=[metadata]
        )

        assert len(ids) == 1
        mock_boto_client.put_vectors.assert_called_once()


class TestS3VectorsRetryLogic:
    """Tests for S3 Vectors exponential backoff retry logic"""

    @pytest.fixture
    def mock_settings(self):
        return Settings(
            vectordb_provider="s3vectors",
            s3vectors_bucket="test-bucket",
            s3vectors_index="test-index",
            aws_region="us-east-1"
        )

    @pytest.fixture
    def mock_boto_client(self):
        with patch("boto3.client") as mock_client:
            client_instance = MagicMock()
            client_instance.get_vector_bucket.return_value = {}
            client_instance.get_index.return_value = {}
            mock_client.return_value = client_instance
            yield client_instance

    def test_retry_on_throttling_exception(self, mock_settings, mock_boto_client):
        """Should retry on ThrottlingException and eventually succeed"""
        from stache_s3vectors.provider import S3VectorsProvider

        provider = S3VectorsProvider(mock_settings)

        # Fail twice, then succeed
        call_count = [0]

        def mock_put_vectors(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 2:
                raise make_client_error("ThrottlingException")
            return {}

        mock_boto_client.put_vectors.side_effect = mock_put_vectors

        with patch("time.sleep"):  # Mock sleep to speed up test
            ids = provider.insert(
                vectors=[[0.1, 0.2]],
                texts=["test"],
                metadatas=[{}]
            )

        assert len(ids) == 1
        assert mock_boto_client.put_vectors.call_count == 3

    def test_retry_on_too_many_requests(self, mock_settings, mock_boto_client):
        """Should retry on TooManyRequestsException"""
        from stache_s3vectors.provider import S3VectorsProvider

        provider = S3VectorsProvider(mock_settings)

        call_count = [0]

        def mock_put_vectors(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise make_client_error("TooManyRequestsException")
            return {}

        mock_boto_client.put_vectors.side_effect = mock_put_vectors

        with patch("time.sleep"):
            ids = provider.insert(
                vectors=[[0.1, 0.2]],
                texts=["test"],
                metadatas=[{}]
            )

        assert len(ids) == 1
        assert mock_boto_client.put_vectors.call_count == 2

    def test_no_retry_on_other_errors(self, mock_settings, mock_boto_client):
        """Should not retry on non-throttling errors"""
        from stache_s3vectors.provider import S3VectorsProvider

        provider = S3VectorsProvider(mock_settings)

        mock_boto_client.put_vectors.side_effect = make_client_error(
            "ValidationException", "Invalid input"
        )

        with pytest.raises(ClientError):
            provider.insert(
                vectors=[[0.1, 0.2]],
                texts=["test"],
                metadatas=[{}]
            )

        # Should only be called once (no retry)
        assert mock_boto_client.put_vectors.call_count == 1

    def test_max_retries_exceeded(self, mock_settings, mock_boto_client):
        """Should raise error after max retries exceeded"""
        from stache_s3vectors.provider import S3VectorsProvider

        provider = S3VectorsProvider(mock_settings)

        # Always fail with throttling
        mock_boto_client.put_vectors.side_effect = make_client_error("ThrottlingException")

        with patch("time.sleep"):
            with pytest.raises(ClientError) as exc_info:
                provider.insert(
                    vectors=[[0.1, 0.2]],
                    texts=["test"],
                    metadatas=[{}]
                )

        assert exc_info.value.response['Error']['Code'] == "ThrottlingException"
        # Should try 5 times (initial + 4 retries)
        assert mock_boto_client.put_vectors.call_count == 5


class TestS3VectorsTopKValidation:
    """Tests for top_k validation and clamping"""

    @pytest.fixture
    def mock_settings(self):
        return Settings(
            vectordb_provider="s3vectors",
            s3vectors_bucket="test-bucket",
            s3vectors_index="test-index",
            aws_region="us-east-1"
        )

    @pytest.fixture
    def mock_boto_client(self):
        with patch("boto3.client") as mock_client:
            client_instance = MagicMock()
            client_instance.get_vector_bucket.return_value = {}
            client_instance.get_index.return_value = {}
            client_instance.query_vectors.return_value = {"vectors": []}
            mock_client.return_value = client_instance
            yield client_instance

    def test_top_k_clamped_to_100(self, mock_settings, mock_boto_client, caplog):
        """Should clamp top_k to 100 and log warning"""
        from stache_s3vectors.provider import S3VectorsProvider
        import logging

        provider = S3VectorsProvider(mock_settings)

        with caplog.at_level(logging.WARNING):
            provider.search([0.1, 0.2], top_k=150)

        assert "exceeds S3 Vectors limit of 100" in caplog.text
        assert "clamping to 100" in caplog.text

        # Verify the actual query used top_k=100
        call_args = mock_boto_client.query_vectors.call_args
        assert call_args.kwargs['topK'] == 100

    def test_top_k_under_limit(self, mock_settings, mock_boto_client):
        """Should not clamp when top_k is under 100"""
        from stache_s3vectors.provider import S3VectorsProvider

        provider = S3VectorsProvider(mock_settings)
        provider.search([0.1, 0.2], top_k=50)

        call_args = mock_boto_client.query_vectors.call_args
        assert call_args.kwargs['topK'] == 50

    def test_top_k_exactly_100(self, mock_settings, mock_boto_client, caplog):
        """Should accept top_k=100 without warning"""
        from stache_s3vectors.provider import S3VectorsProvider
        import logging

        provider = S3VectorsProvider(mock_settings)

        with caplog.at_level(logging.WARNING):
            provider.search([0.1, 0.2], top_k=100)

        # No warning should be logged
        assert "clamping" not in caplog.text

        call_args = mock_boto_client.query_vectors.call_args
        assert call_args.kwargs['topK'] == 100


class TestS3VectorsNamespaceFiltering:
    """Tests for namespace filtering optimizations"""

    @pytest.fixture
    def mock_settings(self):
        return Settings(
            vectordb_provider="s3vectors",
            s3vectors_bucket="test-bucket",
            s3vectors_index="test-index",
            aws_region="us-east-1"
        )

    @pytest.fixture
    def mock_boto_client(self):
        with patch("boto3.client") as mock_client:
            client_instance = MagicMock()
            client_instance.get_vector_bucket.return_value = {}
            client_instance.get_index.return_value = {}
            client_instance.query_vectors.return_value = {"vectors": []}
            mock_client.return_value = client_instance
            yield client_instance

    def test_exact_namespace_uses_native_filter(self, mock_settings, mock_boto_client):
        """Should use native filter for exact: prefix"""
        from stache_s3vectors.provider import S3VectorsProvider

        provider = S3VectorsProvider(mock_settings)
        provider.search([0.1, 0.2], top_k=5, namespace="exact:books")

        call_args = mock_boto_client.query_vectors.call_args
        assert 'filter' in call_args.kwargs
        # MongoDB-style simple dict filter
        assert call_args.kwargs['filter'] == {'namespace': 'books'}
        # Should not overfetch for exact match
        assert call_args.kwargs['topK'] == 5

    def test_wildcard_namespace_requires_post_filtering(self, mock_settings, mock_boto_client):
        """Should overfetch and post-filter for wildcard patterns"""
        from stache_s3vectors.provider import S3VectorsProvider

        provider = S3VectorsProvider(mock_settings)
        provider.search([0.1, 0.2], top_k=5, namespace="books/*")

        call_args = mock_boto_client.query_vectors.call_args
        # Should overfetch for post-filtering
        assert call_args.kwargs['topK'] == 15  # 5 * 3
        # No filter for wildcard (post-filter instead)
        assert 'filter' not in call_args.kwargs

    def test_default_namespace_uses_exact_match(self, mock_settings, mock_boto_client):
        """Should use exact match filter for default namespace behavior"""
        from stache_s3vectors.provider import S3VectorsProvider

        provider = S3VectorsProvider(mock_settings)
        provider.search([0.1, 0.2], top_k=5, namespace="books")

        call_args = mock_boto_client.query_vectors.call_args
        assert 'filter' in call_args.kwargs
        # MongoDB-style simple dict filter
        assert call_args.kwargs['filter'] == {'namespace': 'books'}
        assert call_args.kwargs['topK'] == 5  # No overfetch for exact match

    def test_no_namespace_no_filter(self, mock_settings, mock_boto_client):
        """Should not add filter when no namespace specified"""
        from stache_s3vectors.provider import S3VectorsProvider

        provider = S3VectorsProvider(mock_settings)
        provider.search([0.1, 0.2], top_k=5)

        call_args = mock_boto_client.query_vectors.call_args
        assert 'filter' not in call_args.kwargs
        assert call_args.kwargs['topK'] == 5


class TestS3VectorsBatchOperations:
    """Tests for batch delete operations"""

    @pytest.fixture
    def mock_settings(self):
        return Settings(
            vectordb_provider="s3vectors",
            s3vectors_bucket="test-bucket",
            s3vectors_index="test-index",
            aws_region="us-east-1"
        )

    @pytest.fixture
    def mock_boto_client(self):
        with patch("boto3.client") as mock_client:
            client_instance = MagicMock()
            client_instance.get_vector_bucket.return_value = {}
            client_instance.get_index.return_value = {}
            mock_client.return_value = client_instance
            yield client_instance

    def test_delete_small_batch(self, mock_settings, mock_boto_client):
        """Should delete small batch in single call"""
        from stache_s3vectors.provider import S3VectorsProvider

        provider = S3VectorsProvider(mock_settings)
        result = provider.delete(["id1", "id2", "id3"])

        assert result is True
        mock_boto_client.delete_vectors.assert_called_once()

    def test_delete_large_batch(self, mock_settings, mock_boto_client):
        """Should split large batch into multiple calls"""
        from stache_s3vectors.provider import S3VectorsProvider

        provider = S3VectorsProvider(mock_settings)

        # Create 1000 IDs (should result in 2 batches of 500)
        ids = [f"id{i}" for i in range(1000)]
        result = provider.delete(ids)

        assert result is True
        assert mock_boto_client.delete_vectors.call_count == 2

    def test_delete_empty_list(self, mock_settings, mock_boto_client):
        """Should handle empty list gracefully"""
        from stache_s3vectors.provider import S3VectorsProvider

        provider = S3VectorsProvider(mock_settings)
        result = provider.delete([])

        assert result is True
        mock_boto_client.delete_vectors.assert_not_called()


class TestS3VectorsCountByFilter:
    """Tests for S3 Vectors count_by_filter operation"""

    @pytest.fixture
    def mock_settings(self):
        return Settings(
            vectordb_provider="s3vectors",
            s3vectors_bucket="test-bucket",
            s3vectors_index="test-index",
            aws_region="us-east-1"
        )

    @pytest.fixture
    def mock_boto_client(self):
        with patch("boto3.client") as mock_client:
            client_instance = MagicMock()
            client_instance.get_vector_bucket.return_value = {}
            client_instance.get_index.return_value = {}
            mock_client.return_value = client_instance
            yield client_instance

    def test_count_by_filter_with_results(self, mock_settings, mock_boto_client):
        """Should count vectors matching filter (client-side filtering)"""
        from stache_s3vectors.provider import S3VectorsProvider

        provider = S3VectorsProvider(mock_settings)

        # Mock paginator
        paginator = MagicMock()
        mock_boto_client.get_paginator.return_value = paginator

        # Mock pagination results with metadata for client-side filtering
        paginator.paginate.return_value = [
            {"vectors": [
                {"key": "id1", "metadata": {"namespace": "test-ns"}},
                {"key": "id2", "metadata": {"namespace": "test-ns"}},
                {"key": "id3", "metadata": {"namespace": "other-ns"}}  # Won't match
            ]},
            {"vectors": [
                {"key": "id4", "metadata": {"namespace": "test-ns"}}
            ]}
        ]

        result = provider.count_by_filter({"namespace": "test-ns"})

        assert result == 3  # id1, id2, id4 match; id3 doesn't
        mock_boto_client.get_paginator.assert_called_with('list_vectors')

    def test_count_by_filter_empty(self, mock_settings, mock_boto_client):
        """Should return 0 when no vectors match"""
        from stache_s3vectors.provider import S3VectorsProvider

        provider = S3VectorsProvider(mock_settings)

        paginator = MagicMock()
        mock_boto_client.get_paginator.return_value = paginator
        # Vectors exist but don't match the filter
        paginator.paginate.return_value = [{"vectors": [
            {"key": "id1", "metadata": {"namespace": "other-ns"}}
        ]}]

        result = provider.count_by_filter({"namespace": "nonexistent"})

        assert result == 0

    def test_count_by_filter_multiple_conditions(self, mock_settings, mock_boto_client):
        """Should count with multiple filter conditions (client-side)"""
        from stache_s3vectors.provider import S3VectorsProvider

        provider = S3VectorsProvider(mock_settings)

        paginator = MagicMock()
        mock_boto_client.get_paginator.return_value = paginator
        # Include vectors that match some but not all conditions
        paginator.paginate.return_value = [{"vectors": [
            {"key": "id1", "metadata": {"namespace": "test-ns", "_type": "document_summary"}},
            {"key": "id2", "metadata": {"namespace": "test-ns", "_type": "chunk"}},  # Wrong type
            {"key": "id3", "metadata": {"namespace": "other-ns", "_type": "document_summary"}}  # Wrong ns
        ]}]

        result = provider.count_by_filter({
            "namespace": "test-ns",
            "_type": "document_summary"
        })

        assert result == 1  # Only id1 matches both conditions

        # Verify returnMetadata=True is passed (needed for client-side filtering)
        call_args = paginator.paginate.call_args
        assert call_args.kwargs["returnMetadata"] is True

    def test_count_by_filter_error_handling(self, mock_settings, mock_boto_client):
        """Should return 0 on error"""
        from stache_s3vectors.provider import S3VectorsProvider

        provider = S3VectorsProvider(mock_settings)

        paginator = MagicMock()
        mock_boto_client.get_paginator.return_value = paginator
        paginator.paginate.side_effect = make_client_error("ValidationException")

        result = provider.count_by_filter({"namespace": "test"})

        assert result == 0


class TestS3VectorsListByFilter:
    """Tests for S3 Vectors list_by_filter operation"""

    @pytest.fixture
    def mock_settings(self):
        return Settings(
            vectordb_provider="s3vectors",
            s3vectors_bucket="test-bucket",
            s3vectors_index="test-index",
            aws_region="us-east-1"
        )

    @pytest.fixture
    def mock_boto_client(self):
        with patch("boto3.client") as mock_client:
            client_instance = MagicMock()
            client_instance.get_vector_bucket.return_value = {}
            client_instance.get_index.return_value = {}
            mock_client.return_value = client_instance
            yield client_instance

    def test_list_by_filter_with_results(self, mock_settings, mock_boto_client):
        """Should list vectors matching filter with metadata (client-side filtering)"""
        from stache_s3vectors.provider import S3VectorsProvider

        provider = S3VectorsProvider(mock_settings)

        paginator = MagicMock()
        mock_boto_client.get_paginator.return_value = paginator

        paginator.paginate.return_value = [
            {
                "vectors": [
                    {
                        "key": "id1",
                        "metadata": {"namespace": "test-ns", "doc_id": "doc1", "filename": "test.txt"}
                    },
                    {
                        "key": "id2",
                        "metadata": {"namespace": "test-ns", "doc_id": "doc2", "filename": "test2.txt"}
                    },
                    {
                        "key": "id3",
                        "metadata": {"namespace": "other-ns", "doc_id": "doc3", "filename": "test3.txt"}
                    }
                ]
            }
        ]

        result = provider.list_by_filter({"namespace": "test-ns"})

        assert len(result) == 2  # id3 doesn't match namespace filter
        assert result[0]["key"] == "id1"
        assert result[0]["doc_id"] == "doc1"
        assert result[1]["key"] == "id2"

    def test_list_by_filter_with_field_filter(self, mock_settings, mock_boto_client):
        """Should filter metadata fields when specified"""
        from stache_s3vectors.provider import S3VectorsProvider

        provider = S3VectorsProvider(mock_settings)

        paginator = MagicMock()
        mock_boto_client.get_paginator.return_value = paginator

        paginator.paginate.return_value = [
            {
                "vectors": [
                    {
                        "key": "id1",
                        "metadata": {
                            "namespace": "test-ns",
                            "doc_id": "doc1",
                            "filename": "test.txt",
                            "extra": "not needed"
                        }
                    }
                ]
            }
        ]

        result = provider.list_by_filter(
            {"namespace": "test-ns"},
            fields=["doc_id", "filename"]
        )

        assert len(result) == 1
        assert "key" in result[0]
        assert "doc_id" in result[0]
        assert "filename" in result[0]
        assert "extra" not in result[0]

    def test_list_by_filter_respects_limit(self, mock_settings, mock_boto_client):
        """Should stop at limit"""
        from stache_s3vectors.provider import S3VectorsProvider

        provider = S3VectorsProvider(mock_settings)

        paginator = MagicMock()
        mock_boto_client.get_paginator.return_value = paginator

        # Return more than limit - all match the namespace filter
        paginator.paginate.return_value = [
            {
                "vectors": [
                    {"key": f"id{i}", "metadata": {"namespace": "test", "doc_id": f"doc{i}"}}
                    for i in range(100)
                ]
            }
        ]

        result = provider.list_by_filter({"namespace": "test"}, limit=10)

        assert len(result) == 10

    def test_list_by_filter_empty(self, mock_settings, mock_boto_client):
        """Should return empty list when no vectors match filter"""
        from stache_s3vectors.provider import S3VectorsProvider

        provider = S3VectorsProvider(mock_settings)

        paginator = MagicMock()
        mock_boto_client.get_paginator.return_value = paginator
        # Vectors exist but don't match the filter
        paginator.paginate.return_value = [{"vectors": [
            {"key": "id1", "metadata": {"namespace": "other-ns"}}
        ]}]

        result = provider.list_by_filter({"namespace": "nonexistent"})

        assert result == []

    def test_list_by_filter_error_handling(self, mock_settings, mock_boto_client):
        """Should return empty list on error"""
        from stache_s3vectors.provider import S3VectorsProvider

        provider = S3VectorsProvider(mock_settings)

        paginator = MagicMock()
        mock_boto_client.get_paginator.return_value = paginator
        paginator.paginate.side_effect = make_client_error("ValidationException")

        result = provider.list_by_filter({"namespace": "test"})

        assert result == []


class TestS3VectorsDeleteByMetadata:
    """Tests for S3 Vectors delete_by_metadata operation"""

    @pytest.fixture
    def mock_settings(self):
        return Settings(
            vectordb_provider="s3vectors",
            s3vectors_bucket="test-bucket",
            s3vectors_index="test-index",
            aws_region="us-east-1"
        )

    @pytest.fixture
    def mock_boto_client(self):
        with patch("boto3.client") as mock_client:
            client_instance = MagicMock()
            client_instance.get_vector_bucket.return_value = {}
            client_instance.get_index.return_value = {}
            mock_client.return_value = client_instance
            yield client_instance

    def test_delete_by_metadata_with_results(self, mock_settings, mock_boto_client):
        """Should delete vectors matching metadata criteria via client-side filtering"""
        from stache_s3vectors.provider import S3VectorsProvider

        provider = S3VectorsProvider(mock_settings)

        # Mock paginator
        paginator = MagicMock()
        mock_boto_client.get_paginator.return_value = paginator

        # Mock pagination results with metadata for client-side filtering
        # Note: S3 Vectors list_vectors doesn't support server-side filtering
        paginator.paginate.return_value = [
            {
                "vectors": [
                    {"key": "id1", "metadata": {"doc_type": "article"}},
                    {"key": "id2", "metadata": {"doc_type": "article"}},
                    {"key": "id3", "metadata": {"doc_type": "article"}},
                    {"key": "id4", "metadata": {"doc_type": "note"}}  # Won't match
                ]
            }
        ]

        result = provider.delete_by_metadata("doc_type", "article")

        assert result["deleted"] == 3
        assert len(result["ids"]) == 3
        assert "id1" in result["ids"]
        assert "id4" not in result["ids"]

        # Should batch delete with 500 limit
        mock_boto_client.delete_vectors.assert_called_once()

        # Verify we're using returnMetadata for client-side filtering
        call_args = paginator.paginate.call_args
        assert call_args.kwargs.get("returnMetadata") is True

    def test_delete_by_metadata_large_batch(self, mock_settings, mock_boto_client):
        """Should handle large batches with multiple delete calls"""
        from stache_s3vectors.provider import S3VectorsProvider

        provider = S3VectorsProvider(mock_settings)

        # Mock paginator
        paginator = MagicMock()
        mock_boto_client.get_paginator.return_value = paginator

        # Mock 1000 vectors matching + 200 not matching (client-side filtering)
        matching_vectors = [{"key": f"id{i}", "metadata": {"status": "archived"}} for i in range(1000)]
        non_matching_vectors = [{"key": f"other{i}", "metadata": {"status": "active"}} for i in range(200)]
        paginator.paginate.return_value = [{"vectors": matching_vectors + non_matching_vectors}]

        result = provider.delete_by_metadata("status", "archived")

        assert result["deleted"] == 1000
        # Should split into 2 batches of 500
        assert mock_boto_client.delete_vectors.call_count == 2

    def test_delete_by_metadata_no_results(self, mock_settings, mock_boto_client):
        """Should handle case when no vectors match criteria (client-side filtering)"""
        from stache_s3vectors.provider import S3VectorsProvider

        provider = S3VectorsProvider(mock_settings)

        # Mock paginator with vectors that don't match the filter
        paginator = MagicMock()
        mock_boto_client.get_paginator.return_value = paginator
        paginator.paginate.return_value = [{"vectors": [
            {"key": "id1", "metadata": {"status": "active"}},
            {"key": "id2", "metadata": {"status": "pending"}}
        ]}]

        result = provider.delete_by_metadata("status", "nonexistent")

        assert result["deleted"] == 0
        assert result["ids"] == []
        mock_boto_client.delete_vectors.assert_not_called()

    def test_delete_by_metadata_with_namespace(self, mock_settings, mock_boto_client):
        """Should filter by both field and namespace (client-side filtering)"""
        from stache_s3vectors.provider import S3VectorsProvider

        provider = S3VectorsProvider(mock_settings)

        # Mock paginator
        paginator = MagicMock()
        mock_boto_client.get_paginator.return_value = paginator
        paginator.paginate.return_value = [{"vectors": [
            {"key": "id1", "metadata": {"type": "temp", "namespace": "test-ns"}},  # Match
            {"key": "id2", "metadata": {"type": "temp", "namespace": "other-ns"}},  # Wrong namespace
            {"key": "id3", "metadata": {"type": "permanent", "namespace": "test-ns"}}  # Wrong type
        ]}]

        result = provider.delete_by_metadata("type", "temp", namespace="test-ns")

        assert result["deleted"] == 1
        assert result["ids"] == ["id1"]

        # Verify we're using returnMetadata for client-side filtering
        call_args = paginator.paginate.call_args
        assert call_args.kwargs.get("returnMetadata") is True


class TestDynamoDBNamespaceFilterKeys:
    """Tests for filter_keys in DynamoDB namespace provider"""

    @pytest.fixture
    def mock_settings(self):
        return Settings(
            namespace_provider="dynamodb",
            dynamodb_namespace_table="test-namespaces",
            aws_region="us-east-1"
        )

    @pytest.fixture
    def mock_dynamodb_table(self):
        with patch("boto3.resource") as mock_resource, \
             patch("boto3.client") as mock_client:
            mock_table = MagicMock()
            mock_resource.return_value.Table.return_value = mock_table
            mock_client.return_value.describe_table.return_value = {
                'Table': {'TableStatus': 'ACTIVE'}
            }
            yield mock_table

    def test_create_stores_filter_keys(self, mock_settings, mock_dynamodb_table):
        """Create should store filter_keys in DynamoDB"""
        from stache_dynamodb.namespace import DynamoDBNamespaceProvider

        # First call to get_item returns nothing (namespace doesn't exist)
        # After create, second call returns the created namespace
        mock_dynamodb_table.get_item.side_effect = [
            {},  # Initial check - not exists
            {
                'Item': {
                    'id': 'test',
                    'name': 'Test',
                    'description': '',
                    'parent_id': '__ROOT__',
                    'metadata': '{}',
                    'filter_keys': '["source", "date"]',
                    'created_at': '2025-01-01T00:00:00Z',
                    'updated_at': '2025-01-01T00:00:00Z'
                }
            }
        ]
        mock_dynamodb_table.put_item.return_value = {}

        provider = DynamoDBNamespaceProvider(mock_settings)

        result = provider.create(
            id='test',
            name='Test',
            filter_keys=['source', 'date']
        )

        # Verify put_item was called with filter_keys
        call_args = mock_dynamodb_table.put_item.call_args
        item = call_args.kwargs['Item']
        assert 'filter_keys' in item
        assert json.loads(item['filter_keys']) == ['source', 'date']

    def test_update_replaces_filter_keys(self, mock_settings, mock_dynamodb_table):
        """Update should replace filter_keys entirely"""
        from stache_dynamodb.namespace import DynamoDBNamespaceProvider

        # Mock existing namespace
        mock_dynamodb_table.get_item.return_value = {
            'Item': {
                'id': 'test',
                'name': 'Test',
                'description': '',
                'parent_id': '__ROOT__',
                'metadata': '{}',
                'filter_keys': '["old_key"]',
                'created_at': '2025-01-01T00:00:00Z',
                'updated_at': '2025-01-01T00:00:00Z'
            }
        }
        mock_dynamodb_table.update_item.return_value = {}

        provider = DynamoDBNamespaceProvider(mock_settings)
        provider.update('test', filter_keys=['new_key1', 'new_key2'])

        # Verify update expression includes filter_keys
        call_args = mock_dynamodb_table.update_item.call_args
        expression_values = call_args.kwargs['ExpressionAttributeValues']
        assert ':filter_keys' in expression_values

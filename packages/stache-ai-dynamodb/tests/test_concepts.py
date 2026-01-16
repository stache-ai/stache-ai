"""Unit tests for DynamoDBConceptIndexProvider

This test suite covers the DynamoDBConceptIndexProvider with comprehensive
unit tests that mock boto3 interactions and verify concept indexing operations,
doc-concept junction management, and batch operations.
"""

import base64
import json
import pytest
from unittest.mock import MagicMock, patch
from botocore.exceptions import ClientError

from stache_ai_dynamodb.concepts import (
    DynamoDBConceptIndexProvider,
    generate_concept_id,
    _DELIM
)


class TestGenerateConceptId:
    """Tests for concept ID generation"""

    def test_generate_concept_id_deterministic(self):
        """Should generate same ID for same input"""
        id1 = generate_concept_id("test-ns", "Machine Learning")
        id2 = generate_concept_id("test-ns", "Machine Learning")
        assert id1 == id2

    def test_generate_concept_id_normalization_lowercase(self):
        """Should normalize text to lowercase"""
        id1 = generate_concept_id("test-ns", "Machine Learning")
        id2 = generate_concept_id("test-ns", "machine learning")
        assert id1 == id2

    def test_generate_concept_id_normalization_whitespace(self):
        """Should strip whitespace"""
        id1 = generate_concept_id("test-ns", "machine learning")
        id2 = generate_concept_id("test-ns", "  machine learning  ")
        assert id1 == id2

    def test_generate_concept_id_different_namespace(self):
        """Should generate different IDs for different namespaces"""
        id1 = generate_concept_id("namespace1", "concept")
        id2 = generate_concept_id("namespace2", "concept")
        assert id1 != id2

    def test_generate_concept_id_different_text(self):
        """Should generate different IDs for different text"""
        id1 = generate_concept_id("test-ns", "concept1")
        id2 = generate_concept_id("test-ns", "concept2")
        assert id1 != id2

    def test_generate_concept_id_length(self):
        """Should generate 16-character hex string"""
        concept_id = generate_concept_id("test-ns", "machine learning")
        assert len(concept_id) == 16
        # Should be valid hex
        int(concept_id, 16)


@pytest.fixture
def mock_dynamodb_resource():
    """Create mock DynamoDB resource"""
    resource = MagicMock()
    table = MagicMock()
    table.name = "test-concept-table"
    resource.Table.return_value = table
    return resource, table


@pytest.fixture
def concept_provider(mock_dynamodb_resource):
    """Create DynamoDBConceptIndexProvider with mocked boto3"""
    resource, table = mock_dynamodb_resource
    with patch('stache_ai_dynamodb.concepts.boto3') as mock_boto3:
        mock_boto3.resource.return_value = resource
        provider = DynamoDBConceptIndexProvider("test-concept-table", "us-east-1")
    return provider, table


class TestGetOrCreateConcept:
    """Tests for get_or_create_concept method"""

    def test_get_or_create_concept_creates_new(self, concept_provider):
        """Should create new concept when it doesn't exist"""
        provider, table = concept_provider
        table.put_item.return_value = None

        item, was_created = provider.get_or_create_concept(
            concept_id="abc123",
            concept_text="machine learning",
            namespace="test-ns",
            vector_id="vec-001"
        )

        assert was_created is True
        assert item["PK"] == "CONCEPT#abc123"
        assert item["SK"] == "METADATA"
        assert item["concept_text"] == "machine learning"
        assert item["namespace"] == "test-ns"
        assert item["vector_id"] == "vec-001"
        assert "first_seen" in item

        # Verify put_item called with condition
        table.put_item.assert_called_once()
        call_args = table.put_item.call_args
        assert call_args[1]["ConditionExpression"] == "attribute_not_exists(PK)"

    def test_get_or_create_concept_returns_existing(self, concept_provider):
        """Should return existing concept when ConditionalCheckFailed"""
        provider, table = concept_provider

        # Mock ConditionalCheckFailedException
        error = ClientError(
            {'Error': {'Code': 'ConditionalCheckFailedException'}},
            'PutItem'
        )
        table.put_item.side_effect = error

        # Mock get_item response
        existing_item = {
            "PK": "CONCEPT#abc123",
            "SK": "METADATA",
            "concept_text": "machine learning",
            "namespace": "test-ns",
            "vector_id": "vec-001",
            "first_seen": "2026-01-11T00:00:00+00:00"
        }
        table.get_item.return_value = {"Item": existing_item}

        item, was_created = provider.get_or_create_concept(
            concept_id="abc123",
            concept_text="machine learning",
            namespace="test-ns",
            vector_id="vec-002"  # Different vector_id, but should use existing
        )

        assert was_created is False
        assert item == existing_item
        assert item["vector_id"] == "vec-001"  # Original vector_id

        # Verify get_item called after conditional check failed
        table.get_item.assert_called_once_with(
            Key={"PK": "CONCEPT#abc123", "SK": "METADATA"}
        )

    def test_get_or_create_concept_other_error(self, concept_provider):
        """Should propagate non-conditional ClientError"""
        provider, table = concept_provider

        error = ClientError(
            {'Error': {'Code': 'ValidationException'}},
            'PutItem'
        )
        table.put_item.side_effect = error

        with pytest.raises(ClientError):
            provider.get_or_create_concept(
                concept_id="abc123",
                concept_text="machine learning",
                namespace="test-ns",
                vector_id="vec-001"
            )

    def test_get_or_create_concept_existing_no_item_returned(self, concept_provider):
        """Should return new item when get_item returns empty on race condition"""
        provider, table = concept_provider

        error = ClientError(
            {'Error': {'Code': 'ConditionalCheckFailedException'}},
            'PutItem'
        )
        table.put_item.side_effect = error
        table.get_item.return_value = {}  # No item found

        item, was_created = provider.get_or_create_concept(
            concept_id="abc123",
            concept_text="machine learning",
            namespace="test-ns",
            vector_id="vec-001"
        )

        # Should return the item we tried to create
        assert was_created is False
        assert item["PK"] == "CONCEPT#abc123"


class TestLinkDocConcept:
    """Tests for link_doc_concept method"""

    def test_link_doc_concept_creates_junction_record(self, concept_provider):
        """Should create doc-concept junction record with correct keys"""
        provider, table = concept_provider

        provider.link_doc_concept(
            doc_id="doc-001",
            namespace="test-ns",
            concept_id="abc123"
        )

        table.put_item.assert_called_once()
        call_args = table.put_item.call_args
        item = call_args[1]["Item"]

        assert item["PK"] == f"DOC{_DELIM}test-ns{_DELIM}doc-001"
        assert item["SK"] == "CONCEPT#abc123"
        assert item["GSI1PK"] == "CONCEPT#abc123"
        assert item["GSI1SK"] == f"DOC{_DELIM}test-ns{_DELIM}doc-001"
        assert item["doc_namespace"] == "test-ns"
        assert item["doc_id"] == "doc-001"
        assert "created_at" in item

    def test_link_doc_concept_handles_special_chars(self, concept_provider):
        """Should handle doc_ids with special characters"""
        provider, table = concept_provider

        provider.link_doc_concept(
            doc_id="doc#with#hashes",
            namespace="test-ns",
            concept_id="abc123"
        )

        call_args = table.put_item.call_args
        item = call_args[1]["Item"]

        # Should use delimiter to avoid ambiguity
        assert item["PK"] == f"DOC{_DELIM}test-ns{_DELIM}doc#with#hashes"
        assert item["doc_id"] == "doc#with#hashes"


class TestGetDocConcepts:
    """Tests for get_doc_concepts method"""

    def test_get_doc_concepts_returns_concept_ids(self, concept_provider):
        """Should return list of concept IDs for document"""
        provider, table = concept_provider

        table.query.return_value = {
            "Items": [
                {"SK": "CONCEPT#abc123"},
                {"SK": "CONCEPT#def456"},
                {"SK": "CONCEPT#ghi789"}
            ]
        }

        concept_ids = provider.get_doc_concepts("doc-001", "test-ns")

        assert concept_ids == ["abc123", "def456", "ghi789"]

        # Verify query was called
        table.query.assert_called_once()

    def test_get_doc_concepts_empty_list(self, concept_provider):
        """Should return empty list when no concepts found"""
        provider, table = concept_provider
        table.query.return_value = {"Items": []}

        concept_ids = provider.get_doc_concepts("doc-001", "test-ns")

        assert concept_ids == []


class TestGetConceptDocs:
    """Tests for get_concept_docs pagination method"""

    def test_get_concept_docs_returns_docs(self, concept_provider):
        """Should return list of documents containing concept"""
        provider, table = concept_provider

        table.query.return_value = {
            "Items": [
                {"doc_namespace": "test-ns", "doc_id": "doc-001"},
                {"doc_namespace": "test-ns", "doc_id": "doc-002"}
            ]
        }

        docs, next_token = provider.get_concept_docs("abc123")

        assert len(docs) == 2
        assert docs[0] == {"namespace": "test-ns", "doc_id": "doc-001"}
        assert docs[1] == {"namespace": "test-ns", "doc_id": "doc-002"}
        assert next_token is None

    def test_get_concept_docs_with_pagination(self, concept_provider):
        """Should support pagination with next_token"""
        provider, table = concept_provider

        last_key = {"GSI1PK": "CONCEPT#abc123", "GSI1SK": "DOC|:|ns|:|doc-001"}
        table.query.return_value = {
            "Items": [{"doc_namespace": "test-ns", "doc_id": "doc-001"}],
            "LastEvaluatedKey": last_key
        }

        docs, next_token = provider.get_concept_docs("abc123", limit=1)

        assert len(docs) == 1
        assert next_token is not None

        # Decode next_token to verify it contains LastEvaluatedKey
        decoded = json.loads(base64.urlsafe_b64decode(next_token).decode())
        assert decoded == last_key

    def test_get_concept_docs_with_next_token_input(self, concept_provider):
        """Should accept next_token for pagination"""
        provider, table = concept_provider

        start_key = {"GSI1PK": "CONCEPT#abc123", "GSI1SK": "DOC|:|ns|:|doc-001"}
        next_token = base64.urlsafe_b64encode(json.dumps(start_key).encode()).decode()

        table.query.return_value = {
            "Items": [{"doc_namespace": "test-ns", "doc_id": "doc-002"}]
        }

        docs, _ = provider.get_concept_docs("abc123", next_token=next_token)

        # Verify ExclusiveStartKey was set
        call_args = table.query.call_args[1]
        assert call_args["ExclusiveStartKey"] == start_key

    def test_get_concept_docs_uses_gsi1(self, concept_provider):
        """Should query GSI1 index"""
        provider, table = concept_provider
        table.query.return_value = {"Items": []}

        provider.get_concept_docs("abc123")

        call_args = table.query.call_args[1]
        assert call_args["IndexName"] == "GSI1"

    def test_get_concept_docs_handles_missing_fields(self, concept_provider):
        """Should handle items missing doc_namespace or doc_id fields"""
        provider, table = concept_provider

        table.query.return_value = {
            "Items": [
                {"doc_namespace": "test-ns", "doc_id": "doc-001"},
                {"doc_namespace": "test-ns"},  # Missing doc_id
                {"doc_id": "doc-003"}  # Missing doc_namespace
            ]
        }

        docs, _ = provider.get_concept_docs("abc123")

        assert len(docs) == 3
        assert docs[0] == {"namespace": "test-ns", "doc_id": "doc-001"}
        assert docs[1] == {"namespace": "test-ns", "doc_id": ""}
        assert docs[2] == {"namespace": "", "doc_id": "doc-003"}


class TestGetConceptCount:
    """Tests for get_concept_count method"""

    def test_get_concept_count_returns_count(self, concept_provider):
        """Should return count of documents containing concept"""
        provider, table = concept_provider

        table.query.return_value = {"Count": 42}

        count = provider.get_concept_count("abc123")

        assert count == 42

        # Verify query uses COUNT select
        call_args = table.query.call_args[1]
        assert call_args["Select"] == "COUNT"

    def test_get_concept_count_zero(self, concept_provider):
        """Should return 0 when no documents found"""
        provider, table = concept_provider
        table.query.return_value = {}

        count = provider.get_concept_count("abc123")

        assert count == 0


class TestGetConceptMetadata:
    """Tests for get_concept_metadata method"""

    def test_get_concept_metadata_found(self, concept_provider):
        """Should return concept metadata when found"""
        provider, table = concept_provider

        metadata = {
            "PK": "CONCEPT#abc123",
            "SK": "METADATA",
            "concept_text": "machine learning",
            "namespace": "test-ns",
            "vector_id": "vec-001"
        }
        table.get_item.return_value = {"Item": metadata}

        result = provider.get_concept_metadata("abc123")

        assert result == metadata
        table.get_item.assert_called_once_with(
            Key={"PK": "CONCEPT#abc123", "SK": "METADATA"}
        )

    def test_get_concept_metadata_not_found(self, concept_provider):
        """Should return None when concept not found"""
        provider, table = concept_provider
        table.get_item.return_value = {}

        result = provider.get_concept_metadata("abc123")

        assert result is None


class TestBatchGetConceptMetadata:
    """Tests for batch_get_concept_metadata method"""

    def test_batch_get_concept_metadata_empty_input(self, concept_provider):
        """Should return empty dict for empty input"""
        provider, _ = concept_provider

        result = provider.batch_get_concept_metadata([])

        assert result == {}

    def test_batch_get_concept_metadata_single_batch(self, concept_provider):
        """Should retrieve metadata for multiple concepts"""
        provider, table = concept_provider

        metadata1 = {"PK": "CONCEPT#abc123", "concept_text": "ml"}
        metadata2 = {"PK": "CONCEPT#def456", "concept_text": "ai"}

        # Create a new mock resource for batch operations
        resource = MagicMock()
        resource.batch_get_item.return_value = {
            "Responses": {
                "test-concept-table": [metadata1, metadata2]
            }
        }

        # Patch the resource used in batch operations
        provider.dynamodb = resource

        result = provider.batch_get_concept_metadata(["abc123", "def456"])

        assert len(result) == 2
        assert result["abc123"] == metadata1
        assert result["def456"] == metadata2

    def test_batch_get_concept_metadata_batches_over_100(self, concept_provider):
        """Should batch requests in groups of 100"""
        provider, _ = concept_provider

        # Create 150 concept IDs
        concept_ids = [f"concept-{i:03d}" for i in range(150)]

        # Mock responses for two batches
        batch1_items = [{"PK": f"CONCEPT#concept-{i:03d}"} for i in range(100)]
        batch2_items = [{"PK": f"CONCEPT#concept-{i:03d}"} for i in range(100, 150)]

        # Create a new mock resource
        resource = MagicMock()
        resource.batch_get_item.side_effect = [
            {"Responses": {"test-concept-table": batch1_items}},
            {"Responses": {"test-concept-table": batch2_items}}
        ]

        provider.dynamodb = resource

        result = provider.batch_get_concept_metadata(concept_ids)

        # Should have made 2 batch_get_item calls
        assert resource.batch_get_item.call_count == 2
        assert len(result) == 150

    def test_batch_get_concept_metadata_handles_unprocessed_keys(self, concept_provider):
        """Should retry unprocessed keys"""
        provider, _ = concept_provider

        metadata1 = {"PK": "CONCEPT#abc123"}
        metadata2 = {"PK": "CONCEPT#def456"}

        # Create a new mock resource
        resource = MagicMock()
        # First call returns one item + unprocessed keys
        # Second call returns the unprocessed item
        resource.batch_get_item.side_effect = [
            {
                "Responses": {"test-concept-table": [metadata1]},
                "UnprocessedKeys": {
                    "test-concept-table": {
                        "Keys": [{"PK": "CONCEPT#def456", "SK": "METADATA"}]
                    }
                }
            },
            {"Responses": {"test-concept-table": [metadata2]}}
        ]

        provider.dynamodb = resource

        result = provider.batch_get_concept_metadata(["abc123", "def456"])

        # Should have retried once
        assert resource.batch_get_item.call_count == 2
        assert len(result) == 2
        assert "abc123" in result
        assert "def456" in result


class TestDeleteDocConcepts:
    """Tests for delete_doc_concepts batch delete method"""

    def test_delete_doc_concepts_batch_delete(self, concept_provider):
        """Should batch delete all concept links for document"""
        provider, table = concept_provider

        # Mock get_doc_concepts to return 3 concepts
        table.query.return_value = {
            "Items": [
                {"SK": "CONCEPT#abc123"},
                {"SK": "CONCEPT#def456"},
                {"SK": "CONCEPT#ghi789"}
            ]
        }

        # Create a new mock resource
        resource = MagicMock()
        resource.batch_write_item.return_value = {}
        provider.dynamodb = resource

        deleted_count = provider.delete_doc_concepts("doc-001", "test-ns")

        assert deleted_count == 3

        # Verify batch_write_item called with delete requests
        resource.batch_write_item.assert_called_once()
        call_args = resource.batch_write_item.call_args[1]
        delete_requests = call_args["RequestItems"]["test-concept-table"]

        assert len(delete_requests) == 3
        assert all("DeleteRequest" in req for req in delete_requests)

    def test_delete_doc_concepts_no_concepts(self, concept_provider):
        """Should return 0 when document has no concepts"""
        provider, table = concept_provider

        table.query.return_value = {"Items": []}

        deleted_count = provider.delete_doc_concepts("doc-001", "test-ns")

        assert deleted_count == 0

    def test_delete_doc_concepts_batch_limit(self, concept_provider):
        """Should batch deletes in groups of 25"""
        provider, table = concept_provider

        # Return 50 concepts (should require 2 batches)
        concepts = [{"SK": f"CONCEPT#concept-{i:02d}"} for i in range(50)]
        table.query.return_value = {"Items": concepts}

        # Create a new mock resource
        resource = MagicMock()
        resource.batch_write_item.return_value = {}
        provider.dynamodb = resource

        deleted_count = provider.delete_doc_concepts("doc-001", "test-ns")

        assert deleted_count == 50
        # Should have made 2 batch_write_item calls (25 items each)
        assert resource.batch_write_item.call_count == 2

    def test_delete_doc_concepts_handles_unprocessed_items(self, concept_provider):
        """Should retry unprocessed delete requests"""
        provider, table = concept_provider

        table.query.return_value = {
            "Items": [
                {"SK": "CONCEPT#abc123"},
                {"SK": "CONCEPT#def456"}
            ]
        }

        # Create a new mock resource
        resource = MagicMock()
        # First call leaves one item unprocessed, second call succeeds
        resource.batch_write_item.side_effect = [
            {
                "UnprocessedItems": {
                    "test-concept-table": [
                        {"DeleteRequest": {"Key": {"PK": "DOC|:|test-ns|:|doc-001", "SK": "CONCEPT#def456"}}}
                    ]
                }
            },
            {}
        ]

        provider.dynamodb = resource

        deleted_count = provider.delete_doc_concepts("doc-001", "test-ns")

        assert deleted_count == 2
        # Should have retried once
        assert resource.batch_write_item.call_count == 2

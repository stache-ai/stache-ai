"""Unit tests for DocumentIndexProvider implementations

This test suite covers the DynamoDBDocumentIndex provider with comprehensive
unit tests that mock boto3 interactions and verify all CRUD operations,
error handling, and pagination functionality.
"""

import pytest
from unittest.mock import MagicMock, patch
from botocore.exceptions import ClientError

from stache_ai_dynamodb.document_index import DynamoDBDocumentIndex


@pytest.fixture
def mock_settings():
    """Create mock settings object for DynamoDB configuration"""
    settings = MagicMock()
    settings.dynamodb_documents_table = "test-documents-table"
    settings.aws_region = "us-east-1"
    return settings


@pytest.fixture
def mock_boto3_client():
    """Create mock boto3 DynamoDB client"""
    client = MagicMock()
    # Mock successful describe_table response
    client.describe_table.return_value = {
        'Table': {
            'TableStatus': 'ACTIVE',
            'TableName': 'test-documents-table'
        }
    }
    return client


@pytest.fixture
def mock_boto3_resource():
    """Create mock boto3 DynamoDB resource with table"""
    resource = MagicMock()
    table = MagicMock()
    resource.Table.return_value = table
    return resource, table


@pytest.fixture
def document_index(mock_settings, mock_boto3_client, mock_boto3_resource):
    """Create DynamoDBDocumentIndex instance with mocked boto3"""
    resource, table = mock_boto3_resource
    with patch('stache_ai_dynamodb.document_index.boto3') as mock_boto3:
        mock_boto3.client.return_value = mock_boto3_client
        mock_boto3.resource.return_value = resource
        instance = DynamoDBDocumentIndex(mock_settings)
        instance.table = table
    return instance, table, mock_boto3_client


class TestDocumentIndexInitialization:
    """Tests for DocumentIndexProvider initialization and setup"""

    def test_init_successful(self, mock_settings, mock_boto3_client, mock_boto3_resource):
        """Should initialize successfully when table is ACTIVE"""
        resource, table = mock_boto3_resource
        with patch('stache_ai_dynamodb.document_index.boto3') as mock_boto3:
            mock_boto3.client.return_value = mock_boto3_client
            mock_boto3.resource.return_value = resource

            instance = DynamoDBDocumentIndex(mock_settings)

            assert instance.table_name == "test-documents-table"
            assert instance.aws_region == "us-east-1"
            mock_boto3_client.describe_table.assert_called_once_with(
                TableName="test-documents-table"
            )

    def test_init_table_not_found(self, mock_settings, mock_boto3_client, mock_boto3_resource):
        """Should raise ValueError when table does not exist"""
        resource, table = mock_boto3_resource
        error = ClientError(
            {'Error': {'Code': 'ResourceNotFoundException'}},
            'DescribeTable'
        )
        mock_boto3_client.describe_table.side_effect = error

        with patch('stache_ai_dynamodb.document_index.boto3') as mock_boto3:
            mock_boto3.client.return_value = mock_boto3_client
            mock_boto3.resource.return_value = resource
            with pytest.raises(ValueError, match="does not exist"):
                DynamoDBDocumentIndex(mock_settings)

    def test_init_table_not_active(self, mock_settings, mock_boto3_client, mock_boto3_resource):
        """Should raise ValueError when table is not ACTIVE"""
        resource, table = mock_boto3_resource
        mock_boto3_client.describe_table.return_value = {
            'Table': {
                'TableStatus': 'CREATING',
                'TableName': 'test-documents-table'
            }
        }

        with patch('stache_ai_dynamodb.document_index.boto3') as mock_boto3:
            mock_boto3.client.return_value = mock_boto3_client
            mock_boto3.resource.return_value = resource
            with pytest.raises(ValueError, match="not ACTIVE"):
                DynamoDBDocumentIndex(mock_settings)

    def test_init_describe_table_error(self, mock_settings, mock_boto3_client, mock_boto3_resource):
        """Should propagate other ClientError exceptions"""
        resource, table = mock_boto3_resource
        error = ClientError(
            {'Error': {'Code': 'AccessDeniedException'}},
            'DescribeTable'
        )
        mock_boto3_client.describe_table.side_effect = error

        with patch('stache_ai_dynamodb.document_index.boto3') as mock_boto3:
            mock_boto3.client.return_value = mock_boto3_client
            mock_boto3.resource.return_value = resource
            with pytest.raises(ClientError):
                DynamoDBDocumentIndex(mock_settings)


class TestKeyConstruction:
    """Tests for key construction helper methods"""

    def test_make_pk(self, document_index):
        """Should construct primary key correctly"""
        instance, _, _ = document_index
        pk = instance._make_pk("test-namespace", "doc-123")
        assert pk == "DOC#test-namespace#doc-123"

    def test_make_gsi1pk(self, document_index):
        """Should construct GSI1 partition key correctly"""
        instance, _, _ = document_index
        gsi1pk = instance._make_gsi1pk("test-namespace")
        assert gsi1pk == "NAMESPACE#test-namespace"

    def test_make_gsi1sk(self, document_index):
        """Should construct GSI1 sort key correctly"""
        instance, _, _ = document_index
        timestamp = "2025-12-11T12:00:00+00:00"
        gsi1sk = instance._make_gsi1sk(timestamp)
        assert gsi1sk == f"CREATED#{timestamp}"

    def test_make_gsi2pk(self, document_index):
        """Should construct GSI2 partition key correctly"""
        instance, _, _ = document_index
        gsi2pk = instance._make_gsi2pk("test-namespace", "document.pdf")
        assert gsi2pk == "FILENAME#test-namespace#document.pdf"

    def test_make_pk_with_special_chars(self, document_index):
        """Should handle special characters in namespace and doc_id"""
        instance, _, _ = document_index
        pk = instance._make_pk("my-namespace-123", "doc-uuid-456")
        assert pk == "DOC#my-namespace-123#doc-uuid-456"


class TestCreateDocument:
    """Tests for document creation"""

    def test_create_document_minimal(self, document_index):
        """Should create document with minimal required fields"""
        instance, table, _ = document_index

        result = instance.create_document(
            doc_id="doc-001",
            filename="test.txt",
            namespace="default",
            chunk_ids=["chunk-1", "chunk-2"]
        )

        assert result["doc_id"] == "doc-001"
        assert result["filename"] == "test.txt"
        assert result["namespace"] == "default"
        assert result["chunk_count"] == 2
        assert result["chunk_ids"] == ["chunk-1", "chunk-2"]
        table.put_item.assert_called_once()

    def test_create_document_with_all_fields(self, document_index):
        """Should create document with all optional fields"""
        instance, table, _ = document_index

        result = instance.create_document(
            doc_id="doc-001",
            filename="test.pdf",
            namespace="default",
            chunk_ids=["chunk-1"],
            summary="Test summary",
            summary_embedding_id="emb-001",
            headings=["Header 1", "Header 2"],
            metadata={"source": "email"},
            file_type="pdf",
            file_size=1024
        )

        assert result["doc_id"] == "doc-001"
        assert result["summary"] == "Test summary"
        assert result["summary_embedding_id"] == "emb-001"
        assert result["headings"] == ["Header 1", "Header 2"]
        assert result["metadata"] == {"source": "email"}
        assert result["file_type"] == "pdf"
        assert result["file_size"] == 1024
        table.put_item.assert_called_once()

    def test_create_document_dynamodb_error(self, document_index):
        """Should propagate DynamoDB ClientError"""
        instance, table, _ = document_index
        error = ClientError(
            {'Error': {'Code': 'ValidationException'}},
            'PutItem'
        )
        table.put_item.side_effect = error

        with pytest.raises(ClientError):
            instance.create_document(
                doc_id="doc-001",
                filename="test.txt",
                namespace="default",
                chunk_ids=["chunk-1"]
            )

    def test_create_document_pk_construction(self, document_index):
        """Should construct correct keys when creating document"""
        instance, table, _ = document_index

        instance.create_document(
            doc_id="doc-001",
            filename="test.txt",
            namespace="test-ns",
            chunk_ids=["chunk-1", "chunk-2"]
        )

        call_args = table.put_item.call_args
        item = call_args[1]["Item"]
        assert item["PK"] == "DOC#test-ns#doc-001"
        assert item["SK"] == "METADATA"
        assert item["GSI1PK"] == "NAMESPACE#test-ns"
        assert item["GSI2PK"] == "FILENAME#test-ns#test.txt"


class TestGetDocument:
    """Tests for retrieving a document"""

    def test_get_document_found(self, document_index):
        """Should return document when found"""
        instance, table, _ = document_index
        mock_doc = {
            "doc_id": "doc-001",
            "filename": "test.txt",
            "namespace": "default",
            "chunk_count": 2,
            "chunk_ids": ["chunk-1", "chunk-2"]
        }
        table.get_item.return_value = {"Item": mock_doc}

        result = instance.get_document("doc-001", "default")

        assert result == mock_doc
        table.get_item.assert_called_once_with(
            Key={
                "PK": "DOC#default#doc-001",
                "SK": "METADATA"
            }
        )

    def test_get_document_not_found(self, document_index):
        """Should return None when document not found"""
        instance, table, _ = document_index
        table.get_item.return_value = {}

        result = instance.get_document("doc-001", "default")

        assert result is None

    def test_get_document_no_namespace(self, document_index):
        """Should raise ValueError when namespace not provided"""
        instance, _, _ = document_index

        with pytest.raises(ValueError, match="Namespace is required"):
            instance.get_document("doc-001", namespace=None)

    def test_get_document_dynamodb_error(self, document_index):
        """Should propagate DynamoDB ClientError"""
        instance, table, _ = document_index
        error = ClientError(
            {'Error': {'Code': 'ValidationException'}},
            'GetItem'
        )
        table.get_item.side_effect = error

        with pytest.raises(ClientError):
            instance.get_document("doc-001", "default")


class TestListDocuments:
    """Tests for listing documents with pagination"""

    def test_list_documents_by_namespace(self, document_index):
        """Should list documents filtered by namespace"""
        instance, table, _ = document_index
        mock_docs = [
            {
                "doc_id": "doc-001",
                "filename": "test1.txt",
                "namespace": "default"
            },
            {
                "doc_id": "doc-002",
                "filename": "test2.txt",
                "namespace": "default"
            }
        ]
        table.query.return_value = {
            "Items": mock_docs,
            "LastEvaluatedKey": None
        }

        result = instance.list_documents(namespace="default", limit=10)

        assert result["documents"] == mock_docs
        assert result["next_key"] is None
        table.query.assert_called_once()
        call_args = table.query.call_args
        assert call_args[1]["IndexName"] == "GSI1"
        assert call_args[1]["KeyConditionExpression"] == "GSI1PK = :pk"

    def test_list_documents_all(self, document_index):
        """Should scan all documents when no namespace filter"""
        instance, table, _ = document_index
        mock_docs = [
            {"doc_id": "doc-001", "filename": "test1.txt", "namespace": "ns1"},
            {"doc_id": "doc-002", "filename": "test2.txt", "namespace": "ns2"}
        ]
        table.scan.return_value = {
            "Items": mock_docs,
            "LastEvaluatedKey": None
        }

        result = instance.list_documents(namespace=None, limit=10)

        assert result["documents"] == mock_docs
        assert result["next_key"] is None
        table.scan.assert_called_once()

    def test_list_documents_pagination(self, document_index):
        """Should support pagination with last_evaluated_key"""
        instance, table, _ = document_index
        mock_docs = [{"doc_id": "doc-001", "filename": "test1.txt"}]
        last_key = {"PK": "DOC#default#doc-001", "SK": "METADATA"}
        table.query.return_value = {
            "Items": mock_docs,
            "LastEvaluatedKey": last_key
        }

        result = instance.list_documents(
            namespace="default",
            limit=10,
            last_evaluated_key=last_key
        )

        assert result["documents"] == mock_docs
        assert result["next_key"] == last_key
        call_args = table.query.call_args
        assert call_args[1]["ExclusiveStartKey"] == last_key

    def test_list_documents_scan_pagination(self, document_index):
        """Should support pagination in scan (all documents)"""
        instance, table, _ = document_index
        mock_docs = [{"doc_id": "doc-001"}]
        last_key = {"PK": "DOC#default#doc-001"}
        table.scan.return_value = {
            "Items": mock_docs,
            "LastEvaluatedKey": last_key
        }

        result = instance.list_documents(
            namespace=None,
            limit=10,
            last_evaluated_key=last_key
        )

        assert result["documents"] == mock_docs
        assert result["next_key"] == last_key
        call_args = table.scan.call_args
        assert call_args[1]["ExclusiveStartKey"] == last_key

    def test_list_documents_query_error(self, document_index):
        """Should propagate query error when listing by namespace"""
        instance, table, _ = document_index
        error = ClientError(
            {'Error': {'Code': 'ValidationException'}},
            'Query'
        )
        table.query.side_effect = error

        with pytest.raises(ClientError):
            instance.list_documents(namespace="default")

    def test_list_documents_scan_error(self, document_index):
        """Should propagate scan error when listing all documents"""
        instance, table, _ = document_index
        error = ClientError(
            {'Error': {'Code': 'ValidationException'}},
            'Scan'
        )
        table.scan.side_effect = error

        with pytest.raises(ClientError):
            instance.list_documents(namespace=None)


class TestDeleteDocument:
    """Tests for deleting documents"""

    def test_delete_document_success(self, document_index):
        """Should delete document and return True"""
        instance, table, _ = document_index

        result = instance.delete_document("doc-001", "default")

        assert result is True
        table.delete_item.assert_called_once_with(
            Key={
                "PK": "DOC#default#doc-001",
                "SK": "METADATA"
            }
        )

    def test_delete_document_no_namespace(self, document_index):
        """Should raise ValueError when namespace not provided"""
        instance, _, _ = document_index

        with pytest.raises(ValueError, match="Namespace is required"):
            instance.delete_document("doc-001", namespace=None)

    def test_delete_document_error(self, document_index):
        """Should propagate DynamoDB ClientError"""
        instance, table, _ = document_index
        error = ClientError(
            {'Error': {'Code': 'ValidationException'}},
            'DeleteItem'
        )
        table.delete_item.side_effect = error

        with pytest.raises(ClientError):
            instance.delete_document("doc-001", "default")


class TestUpdateDocumentSummary:
    """Tests for updating document summary"""

    def test_update_document_summary_success(self, document_index):
        """Should update summary and return True"""
        instance, table, _ = document_index

        result = instance.update_document_summary(
            doc_id="doc-001",
            summary="Updated summary",
            summary_embedding_id="emb-001",
            namespace="default"
        )

        assert result is True
        table.update_item.assert_called_once()
        call_args = table.update_item.call_args
        assert call_args[1]["Key"] == {"PK": "DOC#default#doc-001", "SK": "METADATA"}
        assert ":summary" in call_args[1]["ExpressionAttributeValues"]
        assert ":sid" in call_args[1]["ExpressionAttributeValues"]

    def test_update_document_summary_no_namespace(self, document_index):
        """Should raise ValueError when namespace not provided"""
        instance, _, _ = document_index

        with pytest.raises(ValueError, match="Namespace is required"):
            instance.update_document_summary(
                doc_id="doc-001",
                summary="Test",
                summary_embedding_id="emb-001",
                namespace=None
            )

    def test_update_document_summary_error(self, document_index):
        """Should propagate DynamoDB ClientError"""
        instance, table, _ = document_index
        error = ClientError(
            {'Error': {'Code': 'ValidationException'}},
            'UpdateItem'
        )
        table.update_item.side_effect = error

        with pytest.raises(ClientError):
            instance.update_document_summary(
                doc_id="doc-001",
                summary="Test",
                summary_embedding_id="emb-001",
                namespace="default"
            )


class TestGetChunkIds:
    """Tests for retrieving chunk IDs"""

    def test_get_chunk_ids_success(self, document_index):
        """Should retrieve chunk IDs from document"""
        instance, table, _ = document_index
        mock_doc = {
            "doc_id": "doc-001",
            "chunk_ids": ["chunk-1", "chunk-2", "chunk-3"]
        }
        table.get_item.return_value = {"Item": mock_doc}

        result = instance.get_chunk_ids("doc-001", "default")

        assert result == ["chunk-1", "chunk-2", "chunk-3"]

    def test_get_chunk_ids_empty_list(self, document_index):
        """Should return empty list when document not found"""
        instance, table, _ = document_index
        table.get_item.return_value = {}

        result = instance.get_chunk_ids("doc-001", "default")

        assert result == []

    def test_get_chunk_ids_document_without_chunks(self, document_index):
        """Should return empty list when document has no chunk_ids field"""
        instance, table, _ = document_index
        mock_doc = {"doc_id": "doc-001"}
        table.get_item.return_value = {"Item": mock_doc}

        result = instance.get_chunk_ids("doc-001", "default")

        assert result == []

    def test_get_chunk_ids_handles_missing_namespace(self, document_index):
        """Should return empty list when namespace validation fails"""
        instance, _, _ = document_index

        result = instance.get_chunk_ids("doc-001", None)

        assert result == []

    def test_get_chunk_ids_handles_dynamodb_error(self, document_index):
        """Should return empty list on DynamoDB error"""
        instance, table, _ = document_index
        error = ClientError(
            {'Error': {'Code': 'ValidationException'}},
            'GetItem'
        )
        table.get_item.side_effect = error

        result = instance.get_chunk_ids("doc-001", "default")

        assert result == []


class TestDocumentExists:
    """Tests for checking document existence"""

    def test_document_exists_true(self, document_index):
        """Should return True when document exists"""
        instance, table, _ = document_index
        table.query.return_value = {
            "Items": [{"doc_id": "doc-001", "filename": "test.txt"}]
        }

        result = instance.document_exists("test.txt", "default")

        assert result is True
        table.query.assert_called_once()
        call_args = table.query.call_args
        assert call_args[1]["IndexName"] == "GSI2-FilenameCreated"

    def test_document_exists_false(self, document_index):
        """Should return False when document doesn't exist"""
        instance, table, _ = document_index
        table.query.return_value = {"Items": []}

        result = instance.document_exists("nonexistent.txt", "default")

        assert result is False

    def test_document_exists_error(self, document_index):
        """Should return False on DynamoDB error"""
        instance, table, _ = document_index
        error = ClientError(
            {'Error': {'Code': 'ValidationException'}},
            'Query'
        )
        table.query.side_effect = error

        result = instance.document_exists("test.txt", "default")

        assert result is False

    def test_document_exists_gsi2_query(self, document_index):
        """Should use GSI2 for filename lookup"""
        instance, table, _ = document_index
        table.query.return_value = {
            "Items": [{"doc_id": "doc-001"}]
        }

        instance.document_exists("document.pdf", "test-ns")

        call_args = table.query.call_args
        assert call_args[1]["IndexName"] == "GSI2-FilenameCreated"
        assert call_args[1]["KeyConditionExpression"] == "GSI2PK = :pk"
        assert call_args[1]["ExpressionAttributeValues"][":pk"] == "FILENAME#test-ns#document.pdf"
        assert call_args[1]["Limit"] == 1


class TestGetName:
    """Tests for get_name method"""

    def test_get_name(self, document_index):
        """Should return correct provider name"""
        instance, _, _ = document_index
        assert instance.get_name() == "dynamodb-document-index"


class TestCountByNamespace:
    """Tests for count_by_namespace method"""

    def test_count_by_namespace_returns_counts(self, document_index):
        """Should return doc_count and chunk_count from paginated query"""
        instance, _, client = document_index

        # Mock paginator that returns documents with chunk_count
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                'Items': [
                    {'chunk_count': {'N': '10'}},
                    {'chunk_count': {'N': '25'}},
                    {'chunk_count': {'N': '15'}},
                ]
            }
        ]
        client.get_paginator.return_value = mock_paginator

        result = instance.count_by_namespace("test-namespace")

        assert result == {"doc_count": 3, "chunk_count": 50}
        client.get_paginator.assert_called_once_with('query')

    def test_count_by_namespace_handles_pagination(self, document_index):
        """Should paginate through all results"""
        instance, _, client = document_index

        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {'Items': [{'chunk_count': {'N': '10'}}]},
            {'Items': [{'chunk_count': {'N': '20'}}]},
        ]
        client.get_paginator.return_value = mock_paginator

        result = instance.count_by_namespace("test-namespace")

        assert result == {"doc_count": 2, "chunk_count": 30}

    def test_count_by_namespace_empty_namespace(self, document_index):
        """Should return zeros for empty namespace"""
        instance, _, client = document_index

        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{'Items': []}]
        client.get_paginator.return_value = mock_paginator

        result = instance.count_by_namespace("empty-namespace")

        assert result == {"doc_count": 0, "chunk_count": 0}

    def test_count_by_namespace_handles_error(self, document_index):
        """Should return zeros on DynamoDB error"""
        instance, _, client = document_index

        mock_paginator = MagicMock()
        mock_paginator.paginate.side_effect = ClientError(
            {'Error': {'Code': 'InternalError', 'Message': 'Test error'}},
            'Query'
        )
        client.get_paginator.return_value = mock_paginator

        result = instance.count_by_namespace("test-namespace")

        assert result == {"doc_count": 0, "chunk_count": 0}

    def test_count_by_namespace_handles_missing_chunk_count(self, document_index):
        """Should handle documents without chunk_count field"""
        instance, _, client = document_index

        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {'Items': [{'chunk_count': {'N': '10'}}, {}]}  # Second item has no chunk_count
        ]
        client.get_paginator.return_value = mock_paginator

        result = instance.count_by_namespace("test-namespace")

        assert result == {"doc_count": 2, "chunk_count": 10}


class TestEnsureTable:
    """Tests for _ensure_table validation method"""

    def test_ensure_table_active(self, document_index):
        """Should succeed when table is ACTIVE"""
        instance, _, client = document_index
        client.describe_table.return_value = {
            'Table': {'TableStatus': 'ACTIVE'}
        }
        # Should not raise
        instance._ensure_table()

    def test_ensure_table_creating(self, document_index):
        """Should raise when table is not ACTIVE"""
        instance, _, client = document_index
        client.describe_table.return_value = {
            'Table': {'TableStatus': 'CREATING'}
        }

        with pytest.raises(ValueError, match="not ACTIVE"):
            instance._ensure_table()

    def test_ensure_table_deleting(self, document_index):
        """Should raise when table is being deleted"""
        instance, _, client = document_index
        client.describe_table.return_value = {
            'Table': {'TableStatus': 'DELETING'}
        }

        with pytest.raises(ValueError, match="not ACTIVE"):
            instance._ensure_table()

    def test_ensure_table_not_found(self, document_index):
        """Should raise when table doesn't exist"""
        instance, _, client = document_index
        error = ClientError(
            {'Error': {'Code': 'ResourceNotFoundException'}},
            'DescribeTable'
        )
        client.describe_table.side_effect = error

        with pytest.raises(ValueError, match="does not exist"):
            instance._ensure_table()

    def test_ensure_table_other_error(self, document_index):
        """Should propagate other ClientErrors"""
        instance, _, client = document_index
        error = ClientError(
            {'Error': {'Code': 'AccessDeniedException'}},
            'DescribeTable'
        )
        client.describe_table.side_effect = error

        with pytest.raises(ClientError):
            instance._ensure_table()


class TestIntegrationScenarios:
    """Integration-style tests combining multiple operations"""

    def test_full_document_lifecycle(self, document_index):
        """Should handle create, update, get, and delete in sequence"""
        instance, table, _ = document_index

        # Setup mock responses for each operation
        created_doc = {
            "doc_id": "doc-001",
            "filename": "lifecycle.txt",
            "namespace": "test",
            "chunk_ids": ["chunk-1", "chunk-2"],
            "created_at": "2025-12-11T00:00:00Z"
        }
        table.put_item.return_value = None
        table.get_item.return_value = {"Item": created_doc}
        table.update_item.return_value = None
        table.delete_item.return_value = None

        # Create
        create_result = instance.create_document(
            doc_id="doc-001",
            filename="lifecycle.txt",
            namespace="test",
            chunk_ids=["chunk-1", "chunk-2"]
        )
        assert create_result["doc_id"] == "doc-001"

        # Get
        get_result = instance.get_document("doc-001", "test")
        assert get_result["doc_id"] == "doc-001"

        # Update
        update_result = instance.update_document_summary(
            doc_id="doc-001",
            summary="Updated summary",
            summary_embedding_id="emb-001",
            namespace="test"
        )
        assert update_result is True

        # Delete
        delete_result = instance.delete_document("doc-001", "test")
        assert delete_result is True

    def test_multi_namespace_operations(self, document_index):
        """Should handle operations across multiple namespaces"""
        instance, table, _ = document_index

        # List documents in different namespaces
        ns1_docs = [{"doc_id": "doc-001", "namespace": "ns1"}]
        ns2_docs = [{"doc_id": "doc-002", "namespace": "ns2"}]

        table.query.side_effect = [
            {"Items": ns1_docs, "LastEvaluatedKey": None},
            {"Items": ns2_docs, "LastEvaluatedKey": None}
        ]

        result1 = instance.list_documents(namespace="ns1")
        result2 = instance.list_documents(namespace="ns2")

        assert result1["documents"] == ns1_docs
        assert result2["documents"] == ns2_docs
        assert table.query.call_count == 2

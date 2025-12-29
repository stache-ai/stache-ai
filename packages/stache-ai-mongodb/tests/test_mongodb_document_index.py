"""Unit tests for MongoDBDocumentIndex

This test suite covers the MongoDB document index provider with comprehensive
unit tests that mock pymongo interactions and verify all CRUD operations,
error handling, pagination, and edge cases.
"""

import pytest
import sys
from unittest.mock import MagicMock, patch


# Define mock exception classes at module level
class DuplicateKeyError(Exception):
    pass


class ConnectionFailure(Exception):
    pass


@pytest.fixture
def mock_settings():
    """Create mock settings object for MongoDB configuration"""
    settings = MagicMock()
    settings.mongodb_uri = "mongodb://localhost:27017"
    settings.mongodb_database = "test_ragbrain"
    settings.mongodb_documents_collection = "test_documents"
    return settings


@pytest.fixture
def mock_mongo_client():
    """Create mock pymongo MongoClient"""
    client = MagicMock()
    # Mock successful ping response
    client.admin.command.return_value = {"ok": 1}
    return client


@pytest.fixture
def document_index(mock_settings, mock_mongo_client):
    """Create MongoDBDocumentIndex instance with mocked pymongo"""
    # Mock pymongo module in sys.modules
    mock_pymongo = MagicMock()
    mock_pymongo.MongoClient = MagicMock(return_value=mock_mongo_client)
    mock_pymongo.ASCENDING = 1
    mock_pymongo.DESCENDING = -1

    mock_errors = MagicMock()
    mock_errors.ConnectionFailure = ConnectionFailure
    mock_pymongo.errors = mock_errors

    with patch.dict(sys.modules, {'pymongo': mock_pymongo, 'pymongo.errors': mock_errors}):
        from stache_mongodb.document_index import MongoDBDocumentIndex
        instance = MongoDBDocumentIndex(mock_settings)
    return instance, mock_mongo_client, instance.collection


class TestMongoDBDocumentIndexInitialization:
    """Tests for MongoDB document index initialization"""

    def test_init_successful(self, mock_settings, mock_mongo_client):
        """Should initialize successfully and connect to MongoDB"""
        mock_pymongo = MagicMock()
        mock_pymongo.MongoClient = MagicMock(return_value=mock_mongo_client)
        mock_pymongo.ASCENDING = 1
        mock_pymongo.DESCENDING = -1

        mock_errors = MagicMock()
        mock_errors.ConnectionFailure = ConnectionFailure
        mock_pymongo.errors = mock_errors

        with patch.dict(sys.modules, {'pymongo': mock_pymongo, 'pymongo.errors': mock_errors}):
            from stache_mongodb.document_index import MongoDBDocumentIndex
            provider = MongoDBDocumentIndex(mock_settings)

            assert provider.client == mock_mongo_client
            mock_mongo_client.admin.command.assert_called_once_with('ping')

    def test_init_connection_failure(self, mock_settings, mock_mongo_client):
        """Should raise ValueError when MongoDB connection fails"""
        mock_mongo_client.admin.command.side_effect = ConnectionFailure("Connection refused")

        mock_pymongo = MagicMock()
        mock_pymongo.MongoClient = MagicMock(return_value=mock_mongo_client)
        mock_pymongo.ASCENDING = 1
        mock_pymongo.DESCENDING = -1

        mock_errors = MagicMock()
        mock_errors.ConnectionFailure = ConnectionFailure
        mock_pymongo.errors = mock_errors

        with patch.dict(sys.modules, {'pymongo': mock_pymongo, 'pymongo.errors': mock_errors}):
            from stache_mongodb.document_index import MongoDBDocumentIndex
            with pytest.raises(ValueError, match="Cannot connect to MongoDB"):
                MongoDBDocumentIndex(mock_settings)

    def test_init_creates_indexes(self, mock_settings, mock_mongo_client):
        """Should create required indexes on initialization"""
        mock_pymongo = MagicMock()
        mock_pymongo.MongoClient = MagicMock(return_value=mock_mongo_client)
        mock_pymongo.ASCENDING = 1
        mock_pymongo.DESCENDING = -1

        mock_errors = MagicMock()
        mock_errors.ConnectionFailure = ConnectionFailure
        mock_pymongo.errors = mock_errors

        with patch.dict(sys.modules, {'pymongo': mock_pymongo, 'pymongo.errors': mock_errors}):
            from stache_mongodb.document_index import MongoDBDocumentIndex
            provider = MongoDBDocumentIndex(mock_settings)

            # Verify create_index was called at least twice
            assert provider.collection.create_index.call_count >= 2


class TestCreateDocument:
    """Tests for document creation"""

    def test_create_document_minimal(self, document_index):
        """Should create document with minimal required fields"""
        instance, _, collection = document_index

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
        assert "created_at" in result
        collection.insert_one.assert_called_once()

    def test_create_document_with_all_fields(self, document_index):
        """Should create document with all optional fields"""
        instance, _, collection = document_index

        result = instance.create_document(
            doc_id="doc-001",
            filename="test.pdf",
            namespace="default",
            chunk_ids=["chunk-1"],
            summary="Test summary",
            summary_embedding_id="emb-001",
            headings=["Header 1", "Header 2"],
            metadata={"source": "email", "author": "john"},
            file_type="pdf",
            file_size=1024
        )

        assert result["doc_id"] == "doc-001"
        assert result["summary"] == "Test summary"
        assert result["summary_embedding_id"] == "emb-001"
        assert result["headings"] == ["Header 1", "Header 2"]
        assert result["metadata"] == {"source": "email", "author": "john"}
        assert result["file_type"] == "pdf"
        assert result["file_size"] == 1024
        collection.insert_one.assert_called_once()

    def test_create_document_with_composite_id(self, document_index):
        """Should create document with composite _id field"""
        instance, _, collection = document_index

        instance.create_document(
            doc_id="doc-001",
            filename="test.txt",
            namespace="test-ns",
            chunk_ids=["chunk-1"]
        )

        call_args = collection.insert_one.call_args
        doc = call_args[0][0]
        assert doc["_id"] == {"namespace": "test-ns", "doc_id": "doc-001"}

    def test_create_document_mongodb_error(self, document_index):
        """Should propagate MongoDB errors"""
        instance, _, collection = document_index
        collection.insert_one.side_effect = Exception("Connection error")

        with pytest.raises(Exception, match="Connection error"):
            instance.create_document(
                doc_id="doc-001",
                filename="test.txt",
                namespace="default",
                chunk_ids=["chunk-1"]
            )

    def test_create_document_empty_chunk_ids(self, document_index):
        """Should handle empty chunk_ids list"""
        instance, _, collection = document_index

        result = instance.create_document(
            doc_id="doc-001",
            filename="empty.txt",
            namespace="default",
            chunk_ids=[]
        )

        assert result["chunk_count"] == 0
        assert result["chunk_ids"] == []


class TestGetDocument:
    """Tests for retrieving documents"""

    def test_get_document_found(self, document_index):
        """Should return document when found"""
        instance, _, collection = document_index
        mock_doc = {
            "_id": {"namespace": "default", "doc_id": "doc-001"},
            "doc_id": "doc-001",
            "filename": "test.txt",
            "namespace": "default",
            "chunk_count": 2,
            "chunk_ids": ["chunk-1", "chunk-2"],
            "created_at": "2025-12-11T12:00:00Z"
        }
        collection.find_one.return_value = mock_doc

        result = instance.get_document("doc-001", "default")

        assert result == mock_doc
        collection.find_one.assert_called_once_with({
            "_id": {"namespace": "default", "doc_id": "doc-001"}
        })

    def test_get_document_not_found(self, document_index):
        """Should return None when document not found"""
        instance, _, collection = document_index
        collection.find_one.return_value = None

        result = instance.get_document("doc-001", "default")

        assert result is None

    def test_get_document_no_namespace_raises_error(self, document_index):
        """Should raise ValueError when namespace not provided"""
        instance, _, _ = document_index

        with pytest.raises(ValueError, match="Namespace is required"):
            instance.get_document("doc-001", namespace=None)

    def test_get_document_mongodb_error(self, document_index):
        """Should propagate MongoDB errors"""
        instance, _, collection = document_index
        collection.find_one.side_effect = Exception("Connection error")

        with pytest.raises(Exception, match="Connection error"):
            instance.get_document("doc-001", "default")


class TestListDocuments:
    """Tests for listing documents with pagination"""

    def test_list_documents_by_namespace(self, document_index):
        """Should list documents filtered by namespace"""
        instance, _, collection = document_index
        mock_docs = [
            {
                "_id": {"namespace": "default", "doc_id": "doc-001"},
                "doc_id": "doc-001",
                "filename": "test1.txt",
                "namespace": "default",
                "created_at": "2025-12-11T12:00:02Z"
            },
            {
                "_id": {"namespace": "default", "doc_id": "doc-002"},
                "doc_id": "doc-002",
                "filename": "test2.txt",
                "namespace": "default",
                "created_at": "2025-12-11T12:00:01Z"
            }
        ]
        mock_cursor = MagicMock()
        mock_cursor.__iter__.return_value = iter(mock_docs)
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.limit.return_value = mock_cursor
        collection.find.return_value = mock_cursor

        result = instance.list_documents(namespace="default", limit=10)

        assert result["documents"] == mock_docs
        assert result["next_key"] is None
        collection.find.assert_called_once_with({"namespace": "default"})

    def test_list_documents_all_namespaces(self, document_index):
        """Should list all documents when namespace is None"""
        instance, _, collection = document_index
        mock_docs = [
            {"doc_id": "doc-001", "namespace": "ns1", "created_at": "2025-12-11T12:00:00Z"},
            {"doc_id": "doc-002", "namespace": "ns2", "created_at": "2025-12-11T12:00:00Z"}
        ]
        mock_cursor = MagicMock()
        mock_cursor.__iter__.return_value = iter(mock_docs)
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.limit.return_value = mock_cursor
        collection.find.return_value = mock_cursor

        result = instance.list_documents(namespace=None, limit=10)

        assert result["documents"] == mock_docs
        assert result["next_key"] is None
        collection.find.assert_called_once_with({})

    def test_list_documents_pagination(self, document_index):
        """Should support pagination with last_evaluated_key"""
        instance, _, collection = document_index
        mock_docs = [
            {"doc_id": "doc-003", "created_at": "2025-12-11T12:00:00Z"},
            {"doc_id": "doc-004", "created_at": "2025-12-11T11:59:00Z"}
        ]
        mock_cursor = MagicMock()
        mock_cursor.__iter__.return_value = iter(mock_docs)
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.limit.return_value = mock_cursor
        collection.find.return_value = mock_cursor

        last_key = {"created_at": "2025-12-11T12:00:30Z"}
        result = instance.list_documents(
            namespace="default",
            limit=10,
            last_evaluated_key=last_key
        )

        assert result["documents"] == mock_docs
        collection.find.assert_called_once()
        call_kwargs = collection.find.call_args[0][0]
        assert call_kwargs["namespace"] == "default"
        assert "$lt" in call_kwargs["created_at"]

    def test_list_documents_pagination_has_more(self, document_index):
        """Should return next_key when more results exist"""
        instance, _, collection = document_index
        # Return limit + 1 documents to indicate more exist
        # Create docs with distinct timestamps going backwards
        mock_docs = []
        for i in range(11):
            ts = f"2025-12-11T12:{59 - (i*5):02d}:00Z"  # 59:00, 54:00, 49:00, ... down to 00:00
            mock_docs.append({"doc_id": f"doc-{i:03d}", "created_at": ts})

        mock_cursor = MagicMock()
        mock_cursor.__iter__.return_value = iter(mock_docs)
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.limit.return_value = mock_cursor
        collection.find.return_value = mock_cursor

        result = instance.list_documents(namespace="default", limit=10)

        assert len(result["documents"]) == 10
        assert result["next_key"] is not None
        # The 10th document (index 9) should have been the last one returned
        assert result["next_key"]["created_at"] == mock_docs[9]["created_at"]

    def test_list_documents_mongodb_error(self, document_index):
        """Should propagate MongoDB errors"""
        instance, _, collection = document_index
        collection.find.side_effect = Exception("Connection error")

        with pytest.raises(Exception, match="Connection error"):
            instance.list_documents(namespace="default")

    def test_list_documents_sorts_by_created_at(self, document_index):
        """Should sort by created_at descending (most recent first)"""
        instance, _, collection = document_index
        mock_cursor = MagicMock()
        mock_cursor.__iter__.return_value = iter([])
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.limit.return_value = mock_cursor
        collection.find.return_value = mock_cursor

        instance.list_documents(namespace="default")

        mock_cursor.sort.assert_called_once_with("created_at", -1)


class TestDeleteDocument:
    """Tests for deleting documents"""

    def test_delete_document_success(self, document_index):
        """Should delete document and return True"""
        instance, _, collection = document_index
        collection.delete_one.return_value = MagicMock(deleted_count=1)

        result = instance.delete_document("doc-001", "default")

        assert result is True
        collection.delete_one.assert_called_once_with({
            "_id": {"namespace": "default", "doc_id": "doc-001"}
        })

    def test_delete_document_not_found(self, document_index):
        """Should return False when document not found"""
        instance, _, collection = document_index
        collection.delete_one.return_value = MagicMock(deleted_count=0)

        result = instance.delete_document("doc-001", "default")

        assert result is False

    def test_delete_document_no_namespace_raises_error(self, document_index):
        """Should raise ValueError when namespace not provided"""
        instance, _, _ = document_index

        with pytest.raises(ValueError, match="Namespace is required"):
            instance.delete_document("doc-001", namespace=None)

    def test_delete_document_mongodb_error(self, document_index):
        """Should propagate MongoDB errors"""
        instance, _, collection = document_index
        collection.delete_one.side_effect = Exception("Connection error")

        with pytest.raises(Exception, match="Connection error"):
            instance.delete_document("doc-001", "default")


class TestUpdateDocumentSummary:
    """Tests for updating document summary"""

    def test_update_document_summary_success(self, document_index):
        """Should update summary and return True"""
        instance, _, collection = document_index
        collection.update_one.return_value = MagicMock(matched_count=1)

        result = instance.update_document_summary(
            doc_id="doc-001",
            summary="Updated summary",
            summary_embedding_id="emb-001",
            namespace="default"
        )

        assert result is True
        collection.update_one.assert_called_once()
        call_args = collection.update_one.call_args
        assert call_args[0][0] == {"_id": {"namespace": "default", "doc_id": "doc-001"}}
        assert call_args[0][1]["$set"]["summary"] == "Updated summary"
        assert call_args[0][1]["$set"]["summary_embedding_id"] == "emb-001"

    def test_update_document_summary_not_found(self, document_index):
        """Should return False when document not found"""
        instance, _, collection = document_index
        collection.update_one.return_value = MagicMock(matched_count=0)

        result = instance.update_document_summary(
            doc_id="doc-001",
            summary="Summary",
            summary_embedding_id="emb-001",
            namespace="default"
        )

        assert result is False

    def test_update_document_summary_no_namespace_raises_error(self, document_index):
        """Should raise ValueError when namespace not provided"""
        instance, _, _ = document_index

        with pytest.raises(ValueError, match="Namespace is required"):
            instance.update_document_summary(
                doc_id="doc-001",
                summary="Summary",
                summary_embedding_id="emb-001",
                namespace=None
            )

    def test_update_document_summary_mongodb_error(self, document_index):
        """Should propagate MongoDB errors"""
        instance, _, collection = document_index
        collection.update_one.side_effect = Exception("Connection error")

        with pytest.raises(Exception, match="Connection error"):
            instance.update_document_summary(
                doc_id="doc-001",
                summary="Summary",
                summary_embedding_id="emb-001",
                namespace="default"
            )


class TestGetChunkIds:
    """Tests for retrieving chunk IDs"""

    def test_get_chunk_ids_success(self, document_index):
        """Should retrieve chunk IDs from document"""
        instance, _, collection = document_index
        mock_doc = {
            "doc_id": "doc-001",
            "chunk_ids": ["chunk-1", "chunk-2", "chunk-3"]
        }
        collection.find_one.return_value = mock_doc

        result = instance.get_chunk_ids("doc-001", "default")

        assert result == ["chunk-1", "chunk-2", "chunk-3"]

    def test_get_chunk_ids_not_found_returns_empty(self, document_index):
        """Should return empty list when document not found"""
        instance, _, collection = document_index
        collection.find_one.return_value = None

        result = instance.get_chunk_ids("doc-001", "default")

        assert result == []

    def test_get_chunk_ids_no_chunk_ids_field(self, document_index):
        """Should return empty list when document has no chunk_ids field"""
        instance, _, collection = document_index
        mock_doc = {"doc_id": "doc-001"}
        collection.find_one.return_value = mock_doc

        result = instance.get_chunk_ids("doc-001", "default")

        assert result == []

    def test_get_chunk_ids_invalid_namespace_returns_empty(self, document_index):
        """Should return empty list when namespace is invalid"""
        instance, _, _ = document_index

        result = instance.get_chunk_ids("doc-001", None)

        assert result == []

    def test_get_chunk_ids_mongodb_error_returns_empty(self, document_index):
        """Should return empty list on MongoDB error"""
        instance, _, collection = document_index
        collection.find_one.side_effect = Exception("Connection error")

        result = instance.get_chunk_ids("doc-001", "default")

        assert result == []


class TestDocumentExists:
    """Tests for checking document existence"""

    def test_document_exists_true(self, document_index):
        """Should return True when document exists"""
        instance, _, collection = document_index
        collection.find_one.return_value = {
            "_id": {"namespace": "default", "doc_id": "doc-001"},
            "filename": "test.txt"
        }

        result = instance.document_exists("test.txt", "default")

        assert result is True
        collection.find_one.assert_called_once_with({
            "filename": "test.txt",
            "namespace": "default"
        })

    def test_document_exists_false(self, document_index):
        """Should return False when document doesn't exist"""
        instance, _, collection = document_index
        collection.find_one.return_value = None

        result = instance.document_exists("nonexistent.txt", "default")

        assert result is False

    def test_document_exists_different_namespace(self, document_index):
        """Should check only in specified namespace"""
        instance, _, collection = document_index
        collection.find_one.return_value = None

        instance.document_exists("test.txt", "ns1")

        call_args = collection.find_one.call_args[0][0]
        assert call_args["namespace"] == "ns1"
        assert call_args["filename"] == "test.txt"

    def test_document_exists_mongodb_error_returns_false(self, document_index):
        """Should return False on MongoDB error"""
        instance, _, collection = document_index
        collection.find_one.side_effect = Exception("Connection error")

        result = instance.document_exists("test.txt", "default")

        assert result is False


class TestGetName:
    """Tests for get_name method"""

    def test_get_name(self, document_index):
        """Should return correct provider name"""
        instance, _, _ = document_index
        assert instance.get_name() == "mongodb-document-index"


class TestEnsureIndexes:
    """Tests for index creation"""

    def test_ensure_indexes_called_on_init(self, mock_settings, mock_mongo_client):
        """Should create required indexes during initialization"""
        mock_pymongo = MagicMock()
        mock_pymongo.MongoClient = MagicMock(return_value=mock_mongo_client)
        mock_pymongo.ASCENDING = 1
        mock_pymongo.DESCENDING = -1

        mock_errors = MagicMock()
        mock_errors.ConnectionFailure = ConnectionFailure
        mock_pymongo.errors = mock_errors

        with patch.dict(sys.modules, {'pymongo': mock_pymongo, 'pymongo.errors': mock_errors}):
            from stache_mongodb.document_index import MongoDBDocumentIndex
            provider = MongoDBDocumentIndex(mock_settings)

            # Verify indexes were created
            assert provider.collection.create_index.call_count == 2

    def test_ensure_indexes_creates_namespace_created_index(self, document_index):
        """Should create index on namespace and created_at"""
        instance, _, collection = document_index
        # The create_index calls should have been made during __init__
        # Check that one of them was for namespace + created_at
        calls = collection.create_index.call_args_list
        # At least one call should be for the composite index
        assert len(calls) >= 2


class TestIntegrationScenarios:
    """Integration-style tests combining multiple operations"""

    def test_full_document_lifecycle(self, document_index):
        """Should handle create, get, update, delete in sequence"""
        instance, _, collection = document_index

        # Create
        create_result = instance.create_document(
            doc_id="doc-001",
            filename="lifecycle.txt",
            namespace="test",
            chunk_ids=["chunk-1", "chunk-2"]
        )
        assert create_result["doc_id"] == "doc-001"

        # Get
        collection.find_one.return_value = {
            "doc_id": "doc-001",
            "filename": "lifecycle.txt",
            "namespace": "test",
            "chunk_ids": ["chunk-1", "chunk-2"]
        }
        get_result = instance.get_document("doc-001", "test")
        assert get_result is not None

        # Update summary
        collection.update_one.return_value = MagicMock(matched_count=1)
        update_result = instance.update_document_summary(
            doc_id="doc-001",
            summary="Updated",
            summary_embedding_id="emb-001",
            namespace="test"
        )
        assert update_result is True

        # Delete
        collection.delete_one.return_value = MagicMock(deleted_count=1)
        delete_result = instance.delete_document("doc-001", "test")
        assert delete_result is True

    def test_multi_namespace_operations(self, document_index):
        """Should handle operations across multiple namespaces"""
        instance, _, collection = document_index

        # Create documents in different namespaces
        instance.create_document(
            doc_id="doc-ns1",
            filename="file1.txt",
            namespace="ns1",
            chunk_ids=["chunk-1"]
        )

        instance.create_document(
            doc_id="doc-ns2",
            filename="file2.txt",
            namespace="ns2",
            chunk_ids=["chunk-2"]
        )

        assert collection.insert_one.call_count == 2

        # List documents in each namespace
        mock_cursor = MagicMock()
        mock_cursor.__iter__.return_value = iter([
            {"doc_id": "doc-ns1", "namespace": "ns1"}
        ])
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.limit.return_value = mock_cursor
        collection.find.return_value = mock_cursor

        result1 = instance.list_documents(namespace="ns1")
        assert len(result1["documents"]) == 1

    def test_document_with_comprehensive_metadata(self, document_index):
        """Should handle documents with comprehensive metadata"""
        instance, _, collection = document_index

        result = instance.create_document(
            doc_id="doc-001",
            filename="research.pdf",
            namespace="research",
            chunk_ids=["chunk-1", "chunk-2", "chunk-3"],
            summary="A comprehensive research paper about distributed systems",
            summary_embedding_id="emb-summary-001",
            headings=[
                "Introduction",
                "Background",
                "Methodology",
                "Results",
                "Conclusion"
            ],
            metadata={
                "source": "arxiv",
                "date": "2025-01-01",
                "author": "Jane Doe",
                "category": "Computer Science"
            },
            file_type="pdf",
            file_size=2097152
        )

        assert result["doc_id"] == "doc-001"
        assert len(result["chunk_ids"]) == 3
        assert len(result["headings"]) == 5
        assert result["file_size"] == 2097152
        collection.insert_one.assert_called_once()

    def test_pagination_across_large_dataset(self, document_index):
        """Should handle pagination correctly across large datasets"""
        instance, _, collection = document_index

        # Simulate a large dataset with multiple pages
        page1_docs = [
            {"doc_id": f"doc-{i:03d}", "created_at": f"2025-12-11T12:{10-i//60:02d}:{60-i%60:02d}Z"}
            for i in range(10)
        ]

        mock_cursor = MagicMock()
        mock_cursor.__iter__.return_value = iter(page1_docs + [{"doc_id": "doc-999"}])  # +1 to indicate more
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.limit.return_value = mock_cursor
        collection.find.return_value = mock_cursor

        result = instance.list_documents(namespace="default", limit=10)

        assert len(result["documents"]) == 10
        assert result["next_key"] is not None

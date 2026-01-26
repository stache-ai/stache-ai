"""Unit tests for MongoDBDocumentIndex update_document_metadata method

This test suite focuses specifically on the update_document_metadata method,
covering in-place updates, namespace migration with transactions, fallback
behavior when transactions are unavailable, and error cases.
"""

import pytest
import sys
from unittest.mock import MagicMock, patch, call


# Define mock exception classes at module level
class ConfigurationError(Exception):
    """Mock ConfigurationError from pymongo"""
    pass


class OperationFailure(Exception):
    """Mock OperationFailure from pymongo"""
    pass


class ConnectionFailure(Exception):
    """Mock ConnectionFailure from pymongo"""
    pass


@pytest.fixture
def mock_settings():
    """Create mock settings object for MongoDB configuration"""
    settings = MagicMock()
    settings.mongodb_uri = "mongodb://localhost:27017"
    settings.mongodb_database = "test_stache"
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
    mock_errors.ConfigurationError = ConfigurationError
    mock_errors.OperationFailure = OperationFailure
    mock_pymongo.errors = mock_errors

    with patch.dict(sys.modules, {'pymongo': mock_pymongo, 'pymongo.errors': mock_errors}):
        from stache_ai_mongodb.document_index import MongoDBDocumentIndex
        instance = MongoDBDocumentIndex(mock_settings)

    return instance, mock_mongo_client, instance.collection


class TestUpdateDocumentMetadataFilename:
    """Tests for in-place filename updates using $set"""

    def test_update_document_metadata_filename(self, document_index):
        """Should update filename in-place using $set"""
        instance, _, collection = document_index
        collection.update_one.return_value = MagicMock(matched_count=1)

        result = instance.update_document_metadata(
            doc_id="doc-001",
            namespace="default",
            updates={"filename": "renamed.txt"}
        )

        assert result is True
        collection.update_one.assert_called_once()
        call_args = collection.update_one.call_args

        # Verify query uses composite _id
        assert call_args[0][0] == {"_id": {"namespace": "default", "doc_id": "doc-001"}}

        # Verify $set operation for filename
        assert call_args[0][1]["$set"]["filename"] == "renamed.txt"

        # Verify namespace was NOT changed (in-place update)
        assert "namespace" not in call_args[0][1]["$set"]

    def test_update_document_metadata_custom_metadata(self, document_index):
        """Should update custom metadata field using $set"""
        instance, _, collection = document_index
        collection.update_one.return_value = MagicMock(matched_count=1)

        new_metadata = {"author": "John Doe", "tags": ["important", "reviewed"]}
        result = instance.update_document_metadata(
            doc_id="doc-001",
            namespace="default",
            updates={"metadata": new_metadata}
        )

        assert result is True
        call_args = collection.update_one.call_args
        assert call_args[0][1]["$set"]["metadata"] == new_metadata

    def test_update_document_metadata_filename_and_metadata(self, document_index):
        """Should update both filename and metadata in single operation"""
        instance, _, collection = document_index
        collection.update_one.return_value = MagicMock(matched_count=1)

        new_metadata = {"source": "email"}
        result = instance.update_document_metadata(
            doc_id="doc-001",
            namespace="default",
            updates={"filename": "updated.pdf", "metadata": new_metadata}
        )

        assert result is True
        call_args = collection.update_one.call_args
        assert call_args[0][1]["$set"]["filename"] == "updated.pdf"
        assert call_args[0][1]["$set"]["metadata"] == new_metadata

    def test_update_document_metadata_no_changes_returns_true(self, document_index):
        """Should return True when no updates specified (no-op)"""
        instance, _, collection = document_index

        result = instance.update_document_metadata(
            doc_id="doc-001",
            namespace="default",
            updates={}
        )

        assert result is True
        # No MongoDB operations should have been called
        collection.update_one.assert_not_called()
        collection.delete_one.assert_not_called()
        collection.insert_one.assert_not_called()


class TestUpdateDocumentMetadataNamespaceMigration:
    """Tests for namespace migration using transactions"""

    def test_update_document_metadata_namespace_migration(self, document_index):
        """Should use transaction for namespace migration (delete + insert)"""
        instance, client, collection = document_index

        # Mock existing document
        existing_doc = {
            "_id": {"namespace": "old-ns", "doc_id": "doc-001"},
            "doc_id": "doc-001",
            "filename": "test.txt",
            "namespace": "old-ns",
            "chunk_ids": ["chunk-1", "chunk-2"],
            "created_at": "2025-01-01T00:00:00Z"
        }

        # Mock session and transaction
        mock_session = MagicMock()
        mock_transaction_context = MagicMock()
        mock_transaction_context.__enter__ = MagicMock(return_value=mock_transaction_context)
        mock_transaction_context.__exit__ = MagicMock(return_value=None)

        mock_session.start_transaction.return_value = mock_transaction_context
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)

        client.start_session.return_value = mock_session
        collection.find_one.return_value = existing_doc

        result = instance.update_document_metadata(
            doc_id="doc-001",
            namespace="old-ns",
            updates={"namespace": "new-ns"}
        )

        assert result is True

        # Verify transaction was used
        client.start_session.assert_called_once()
        mock_session.start_transaction.assert_called_once()

        # Verify find_one was called with session
        find_call = collection.find_one.call_args
        assert find_call[0][0] == {"_id": {"namespace": "old-ns", "doc_id": "doc-001"}}
        assert find_call[1]["session"] == mock_session

        # Verify delete_one was called with old namespace
        delete_call = collection.delete_one.call_args
        assert delete_call[0][0] == {"_id": {"namespace": "old-ns", "doc_id": "doc-001"}}
        assert delete_call[1]["session"] == mock_session

        # Verify insert_one was called with new namespace
        insert_call = collection.insert_one.call_args
        inserted_doc = insert_call[0][0]
        assert inserted_doc["_id"] == {"namespace": "new-ns", "doc_id": "doc-001"}
        assert inserted_doc["namespace"] == "new-ns"
        assert insert_call[1]["session"] == mock_session

    def test_update_document_metadata_namespace_migration_with_filename(self, document_index):
        """Should update both namespace and filename in single transaction"""
        instance, client, collection = document_index

        existing_doc = {
            "_id": {"namespace": "old-ns", "doc_id": "doc-001"},
            "doc_id": "doc-001",
            "filename": "old.txt",
            "namespace": "old-ns",
            "chunk_ids": ["chunk-1"]
        }

        # Mock session and transaction
        mock_session = MagicMock()
        mock_transaction_context = MagicMock()
        mock_transaction_context.__enter__ = MagicMock(return_value=mock_transaction_context)
        mock_transaction_context.__exit__ = MagicMock(return_value=None)

        mock_session.start_transaction.return_value = mock_transaction_context
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)

        client.start_session.return_value = mock_session
        collection.find_one.return_value = existing_doc

        result = instance.update_document_metadata(
            doc_id="doc-001",
            namespace="old-ns",
            updates={"namespace": "new-ns", "filename": "new.txt"}
        )

        assert result is True

        # Verify inserted document has both updates
        insert_call = collection.insert_one.call_args
        inserted_doc = insert_call[0][0]
        assert inserted_doc["namespace"] == "new-ns"
        assert inserted_doc["filename"] == "new.txt"

    def test_update_document_metadata_namespace_migration_with_metadata(self, document_index):
        """Should update namespace and metadata in single transaction"""
        instance, client, collection = document_index

        existing_doc = {
            "_id": {"namespace": "old-ns", "doc_id": "doc-001"},
            "doc_id": "doc-001",
            "filename": "test.txt",
            "namespace": "old-ns",
            "metadata": {"old": "value"}
        }

        # Mock session and transaction
        mock_session = MagicMock()
        mock_transaction_context = MagicMock()
        mock_transaction_context.__enter__ = MagicMock(return_value=mock_transaction_context)
        mock_transaction_context.__exit__ = MagicMock(return_value=None)

        mock_session.start_transaction.return_value = mock_transaction_context
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)

        client.start_session.return_value = mock_session
        collection.find_one.return_value = existing_doc

        new_metadata = {"new": "metadata", "tags": ["important"]}
        result = instance.update_document_metadata(
            doc_id="doc-001",
            namespace="old-ns",
            updates={"namespace": "new-ns", "metadata": new_metadata}
        )

        assert result is True

        # Verify inserted document has updated metadata
        insert_call = collection.insert_one.call_args
        inserted_doc = insert_call[0][0]
        assert inserted_doc["metadata"] == new_metadata


class TestUpdateDocumentMetadataStandaloneFallback:
    """Tests for fallback behavior when transactions unavailable"""

    def test_update_document_metadata_namespace_standalone_fallback(self, document_index, caplog):
        """Should fallback to delete+insert when transactions unavailable (ConfigurationError)"""
        import logging
        caplog.set_level(logging.WARNING)

        instance, client, collection = document_index

        existing_doc = {
            "_id": {"namespace": "old-ns", "doc_id": "doc-001"},
            "doc_id": "doc-001",
            "filename": "test.txt",
            "namespace": "old-ns",
            "chunk_ids": ["chunk-1"]
        }

        # Mock ConfigurationError when trying to start session (standalone MongoDB)
        from pymongo.errors import ConfigurationError
        client.start_session.side_effect = ConfigurationError("Standalone mode")

        # Mock find_one for non-transactional path
        collection.find_one.return_value = existing_doc

        result = instance.update_document_metadata(
            doc_id="doc-001",
            namespace="old-ns",
            updates={"namespace": "new-ns"}
        )

        assert result is True

        # Verify warning was logged
        assert "Transactions not supported" in caplog.text
        assert "delete+insert" in caplog.text

        # Verify non-transactional operations (no session parameter)
        find_call = collection.find_one.call_args
        assert find_call[0][0] == {"_id": {"namespace": "old-ns", "doc_id": "doc-001"}}
        assert "session" not in find_call[1] or find_call[1].get("session") is None

        delete_call = collection.delete_one.call_args
        assert delete_call[0][0] == {"_id": {"namespace": "old-ns", "doc_id": "doc-001"}}

        insert_call = collection.insert_one.call_args
        inserted_doc = insert_call[0][0]
        assert inserted_doc["_id"] == {"namespace": "new-ns", "doc_id": "doc-001"}
        assert inserted_doc["namespace"] == "new-ns"

    def test_update_document_metadata_namespace_operation_failure_fallback(self, document_index, caplog):
        """Should fallback to delete+insert when transaction fails with OperationFailure"""
        import logging
        caplog.set_level(logging.WARNING)

        instance, client, collection = document_index

        existing_doc = {
            "_id": {"namespace": "old-ns", "doc_id": "doc-001"},
            "doc_id": "doc-001",
            "filename": "test.txt",
            "namespace": "old-ns"
        }

        # Mock OperationFailure when starting transaction
        from pymongo.errors import OperationFailure
        client.start_session.side_effect = OperationFailure("Transaction not supported")

        collection.find_one.return_value = existing_doc

        result = instance.update_document_metadata(
            doc_id="doc-001",
            namespace="old-ns",
            updates={"namespace": "new-ns"}
        )

        assert result is True

        # Verify warning was logged
        assert "Transactions not supported" in caplog.text

        # Verify fallback path was used
        assert collection.delete_one.called
        assert collection.insert_one.called

    def test_update_document_metadata_fallback_with_all_updates(self, document_index, caplog):
        """Should apply all updates in fallback path (filename + metadata)"""
        import logging
        caplog.set_level(logging.WARNING)

        instance, client, collection = document_index

        existing_doc = {
            "_id": {"namespace": "old-ns", "doc_id": "doc-001"},
            "doc_id": "doc-001",
            "filename": "old.txt",
            "namespace": "old-ns",
            "metadata": {"old": "data"}
        }

        from pymongo.errors import ConfigurationError
        client.start_session.side_effect = ConfigurationError("No replica set")
        collection.find_one.return_value = existing_doc

        new_metadata = {"new": "data"}
        result = instance.update_document_metadata(
            doc_id="doc-001",
            namespace="old-ns",
            updates={"namespace": "new-ns", "filename": "new.txt", "metadata": new_metadata}
        )

        assert result is True

        # Verify all updates were applied in fallback
        insert_call = collection.insert_one.call_args
        inserted_doc = insert_call[0][0]
        assert inserted_doc["namespace"] == "new-ns"
        assert inserted_doc["filename"] == "new.txt"
        assert inserted_doc["metadata"] == new_metadata


class TestUpdateDocumentMetadataNotFound:
    """Tests for document not found cases"""

    def test_update_document_metadata_not_found(self, document_index):
        """Should return False when document doesn't exist (in-place update)"""
        instance, _, collection = document_index
        collection.update_one.return_value = MagicMock(matched_count=0)

        result = instance.update_document_metadata(
            doc_id="nonexistent",
            namespace="default",
            updates={"filename": "test.txt"}
        )

        assert result is False

    def test_update_document_metadata_not_found_namespace_migration(self, document_index):
        """Should return False when document not found during namespace migration"""
        instance, client, collection = document_index

        # Mock session and transaction
        mock_session = MagicMock()
        mock_transaction_context = MagicMock()
        mock_transaction_context.__enter__ = MagicMock(return_value=mock_transaction_context)
        mock_transaction_context.__exit__ = MagicMock(return_value=None)

        mock_session.start_transaction.return_value = mock_transaction_context
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)

        client.start_session.return_value = mock_session
        collection.find_one.return_value = None  # Document not found

        result = instance.update_document_metadata(
            doc_id="nonexistent",
            namespace="old-ns",
            updates={"namespace": "new-ns"}
        )

        assert result is False

        # Verify no delete or insert was attempted
        collection.delete_one.assert_not_called()
        collection.insert_one.assert_not_called()

    def test_update_document_metadata_not_found_fallback_path(self, document_index):
        """Should return False when document not found in fallback path"""
        instance, client, collection = document_index

        from pymongo.errors import ConfigurationError
        client.start_session.side_effect = ConfigurationError("Standalone")
        collection.find_one.return_value = None

        result = instance.update_document_metadata(
            doc_id="nonexistent",
            namespace="old-ns",
            updates={"namespace": "new-ns"}
        )

        assert result is False

        # Verify no operations were performed
        collection.delete_one.assert_not_called()
        collection.insert_one.assert_not_called()


class TestUpdateDocumentMetadataValidation:
    """Tests for validation and error handling"""

    def test_update_document_metadata_requires_namespace(self, document_index):
        """Should raise ValueError when namespace not provided"""
        instance, _, _ = document_index

        with pytest.raises(ValueError, match="Namespace is required"):
            instance.update_document_metadata(
                doc_id="doc-001",
                namespace=None,
                updates={"filename": "test.txt"}
            )

    def test_update_document_metadata_mongodb_error_in_place(self, document_index):
        """Should propagate MongoDB errors during in-place update"""
        instance, _, collection = document_index
        collection.update_one.side_effect = Exception("Connection error")

        with pytest.raises(Exception, match="Connection error"):
            instance.update_document_metadata(
                doc_id="doc-001",
                namespace="default",
                updates={"filename": "test.txt"}
            )

    def test_update_document_metadata_same_namespace_not_migration(self, document_index):
        """Should use in-place update when new_namespace equals current namespace"""
        instance, client, collection = document_index
        collection.update_one.return_value = MagicMock(matched_count=1)

        result = instance.update_document_metadata(
            doc_id="doc-001",
            namespace="same-ns",
            updates={"namespace": "same-ns", "filename": "test.txt"}
        )

        assert result is True

        # Verify in-place update was used (update_one called, not transaction)
        collection.update_one.assert_called_once()
        client.start_session.assert_not_called()

        # Verify only filename was updated, not namespace
        call_args = collection.update_one.call_args
        assert call_args[0][1]["$set"]["filename"] == "test.txt"


class TestUpdateDocumentMetadataEdgeCases:
    """Tests for edge cases and special scenarios"""

    def test_update_document_metadata_empty_metadata(self, document_index):
        """Should handle empty metadata dictionary"""
        instance, _, collection = document_index
        collection.update_one.return_value = MagicMock(matched_count=1)

        result = instance.update_document_metadata(
            doc_id="doc-001",
            namespace="default",
            updates={"metadata": {}}
        )

        assert result is True
        call_args = collection.update_one.call_args
        assert call_args[0][1]["$set"]["metadata"] == {}

    def test_update_document_metadata_preserves_other_fields(self, document_index):
        """Should preserve fields not being updated during namespace migration"""
        instance, client, collection = document_index

        existing_doc = {
            "_id": {"namespace": "old-ns", "doc_id": "doc-001"},
            "doc_id": "doc-001",
            "filename": "test.txt",
            "namespace": "old-ns",
            "chunk_ids": ["chunk-1", "chunk-2"],
            "summary": "Important summary",
            "file_type": "pdf",
            "file_size": 1024,
            "created_at": "2025-01-01T00:00:00Z"
        }

        # Mock session and transaction
        mock_session = MagicMock()
        mock_transaction_context = MagicMock()
        mock_transaction_context.__enter__ = MagicMock(return_value=mock_transaction_context)
        mock_transaction_context.__exit__ = MagicMock(return_value=None)

        mock_session.start_transaction.return_value = mock_transaction_context
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=None)

        client.start_session.return_value = mock_session
        collection.find_one.return_value = existing_doc

        result = instance.update_document_metadata(
            doc_id="doc-001",
            namespace="old-ns",
            updates={"namespace": "new-ns"}
        )

        assert result is True

        # Verify all fields were preserved except namespace
        insert_call = collection.insert_one.call_args
        inserted_doc = insert_call[0][0]
        assert inserted_doc["chunk_ids"] == ["chunk-1", "chunk-2"]
        assert inserted_doc["summary"] == "Important summary"
        assert inserted_doc["file_type"] == "pdf"
        assert inserted_doc["file_size"] == 1024
        assert inserted_doc["created_at"] == "2025-01-01T00:00:00Z"
        assert inserted_doc["namespace"] == "new-ns"

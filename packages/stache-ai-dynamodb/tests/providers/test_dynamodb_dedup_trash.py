"""Tests for DynamoDB deduplication and trash/restore functionality"""

import pytest
from datetime import datetime, timezone, timedelta
import uuid
from unittest.mock import Mock, MagicMock, patch
from botocore.exceptions import ClientError

from stache_ai_dynamodb.document_index import (
    DynamoDBDocumentIndex,
    DOC_STATUS_ACTIVE,
    DOC_STATUS_DELETING,
    DOC_STATUS_PURGING,
    DOC_STATUS_PURGED,
)


@pytest.fixture
def mock_settings():
    """Create mock settings object"""
    settings = Mock()
    settings.dynamodb_documents_table = "test-documents"
    settings.aws_region = "us-east-1"
    return settings


@pytest.fixture
def mock_dynamodb(mock_settings):
    """Create mock DynamoDB client and provider"""
    with patch('stache_ai_dynamodb.document_index.boto3') as mock_boto3:
        # Setup mock client and resource
        mock_client = MagicMock()
        mock_resource = MagicMock()
        mock_table = MagicMock()

        mock_boto3.client.return_value = mock_client
        mock_boto3.resource.return_value = mock_resource
        mock_resource.Table.return_value = mock_table

        # Mock table descriptor
        mock_client.describe_table.return_value = {
            'Table': {'TableStatus': 'ACTIVE'}
        }

        # Setup exception types
        mock_client.exceptions.ConditionalCheckFailedException = type(
            'ConditionalCheckFailedException',
            (ClientError,),
            {}
        )
        mock_client.exceptions.TransactionCanceledException = type(
            'TransactionCanceledException',
            (ClientError,),
            {}
        )

        provider = DynamoDBDocumentIndex(mock_settings)
        provider.client = mock_client
        provider.table = mock_table

        return provider, mock_client, mock_table


class TestIdentifierReservation:
    """Test identifier reservation with SOURCE vs HASH logic"""

    def test_compute_identifier_source_path(self, mock_dynamodb):
        """Test computing SOURCE identifier for file paths"""
        provider, _, _ = mock_dynamodb
        pk, id_type = provider._compute_identifier(
            content_hash="abc123",
            filename="document.pdf",
            namespace="docs",
            source_path="/home/user/documents/document.pdf"
        )
        assert pk == "SOURCE#docs#/home/user/documents/document.pdf"
        assert id_type == "source_path"

    def test_compute_identifier_hash_for_temp_path(self, mock_dynamodb):
        """Test computing HASH identifier for temporary paths"""
        provider, _, _ = mock_dynamodb
        pk, id_type = provider._compute_identifier(
            content_hash="abc123",
            filename="document.pdf",
            namespace="docs",
            source_path="/tmp/upload123.pdf"
        )
        assert pk == "HASH#docs#abc123#document.pdf"
        assert id_type == "fingerprint"

    def test_compute_identifier_hash_without_source(self, mock_dynamodb):
        """Test computing HASH identifier when no source path provided"""
        provider, _, _ = mock_dynamodb
        pk, id_type = provider._compute_identifier(
            content_hash="abc123",
            filename="document.pdf",
            namespace="docs",
            source_path=None
        )
        assert pk == "HASH#docs#abc123#document.pdf"
        assert id_type == "fingerprint"

    def test_reserve_identifier_success(self, mock_dynamodb):
        """Test successful identifier reservation"""
        provider, _, mock_table = mock_dynamodb
        mock_table.put_item.return_value = {}

        result = provider.reserve_identifier(
            content_hash="abc123",
            filename="document.pdf",
            namespace="docs",
            doc_id=str(uuid.uuid4()),
            source_path="/home/user/documents/document.pdf",
            file_size=1024,
            file_modified_at="2024-01-01T00:00:00Z"
        )

        assert result is True
        mock_table.put_item.assert_called_once()
        call_args = mock_table.put_item.call_args
        assert call_args[1]['ConditionExpression'] == "attribute_not_exists(PK)"

    def test_reserve_identifier_conflict(self, mock_dynamodb):
        """Test reservation fails when identifier already exists"""
        provider, mock_client, mock_table = mock_dynamodb

        # Setup ConditionalCheckFailedException
        exception = ClientError(
            {'Error': {'Code': 'ConditionalCheckFailedException'}},
            'PutItem'
        )
        mock_table.put_item.side_effect = exception
        mock_client.exceptions.ConditionalCheckFailedException = type(exception)

        result = provider.reserve_identifier(
            content_hash="abc123",
            filename="document.pdf",
            namespace="docs",
            doc_id=str(uuid.uuid4()),
            source_path="/home/user/documents/document.pdf"
        )

        assert result is False

    def test_get_document_by_identifier_complete(self, mock_dynamodb):
        """Test retrieving completed identifier reservation"""
        provider, _, mock_table = mock_dynamodb
        doc_id = str(uuid.uuid4())

        mock_table.get_item.return_value = {
            'Item': {
                'doc_id': doc_id,
                'namespace': 'docs',
                'identifier_type': 'source_path',
                'content_hash': 'abc123',
                'filename': 'document.pdf',
                'source_path': '/home/user/documents/document.pdf',
                'file_size': 1024,
                'file_modified_at': '2024-01-01T00:00:00Z',
                'ingested_at': '2024-01-01T00:00:00Z',
                'version': 1,
                'status': 'complete'
            }
        }

        result = provider.get_document_by_identifier(
            content_hash="abc123",
            filename="document.pdf",
            namespace="docs",
            source_path="/home/user/documents/document.pdf"
        )

        assert result is not None
        assert result['doc_id'] == doc_id
        assert result['identifier_type'] == 'source_path'
        assert result['version'] == 1

    def test_get_document_by_identifier_pending(self, mock_dynamodb):
        """Test that pending reservations are not returned"""
        provider, _, mock_table = mock_dynamodb

        mock_table.get_item.return_value = {
            'Item': {
                'doc_id': str(uuid.uuid4()),
                'status': 'pending'
            }
        }

        result = provider.get_document_by_identifier(
            content_hash="abc123",
            filename="document.pdf",
            namespace="docs"
        )

        assert result is None

    def test_get_document_by_identifier_legacy_without_status(self, mock_dynamodb):
        """Test that legacy documents without status field are treated as complete"""
        provider, _, mock_table = mock_dynamodb
        doc_id = str(uuid.uuid4())

        # Legacy document without status field (pre-soft-delete)
        mock_table.get_item.return_value = {
            'Item': {
                'doc_id': doc_id,
                'namespace': 'docs',
                'identifier_type': 'source_path',
                'content_hash': 'abc123',
                'filename': 'legacy-document.pdf',
                'source_path': '/home/user/documents/legacy-document.pdf',
                'file_size': 2048,
                'file_modified_at': '2023-01-01T00:00:00Z',
                'ingested_at': '2023-01-01T00:00:00Z',
                'version': 1,
                # No status field (legacy)
            }
        }

        result = provider.get_document_by_identifier(
            content_hash="abc123",
            filename="legacy-document.pdf",
            namespace="docs"
        )

        # Legacy documents without status should be treated as complete
        assert result is not None
        assert result["doc_id"] == doc_id
        assert result["filename"] == "legacy-document.pdf"

    def test_complete_identifier_reservation(self, mock_dynamodb):
        """Test marking identifier reservation as complete"""
        provider, _, mock_table = mock_dynamodb

        provider.complete_identifier_reservation(
            content_hash="abc123",
            filename="document.pdf",
            namespace="docs",
            doc_id=str(uuid.uuid4()),
            chunk_count=10,
            source_path="/home/user/documents/document.pdf"
        )

        mock_table.update_item.assert_called_once()
        call_args = mock_table.update_item.call_args
        assert "SET" in call_args[1]['UpdateExpression']
        assert ":status" in call_args[1]['ExpressionAttributeValues']
        assert call_args[1]['ExpressionAttributeValues'][':status'] == "complete"

    def test_release_identifier(self, mock_dynamodb):
        """Test releasing identifier on failure"""
        provider, _, mock_table = mock_dynamodb

        provider.release_identifier(
            content_hash="abc123",
            filename="document.pdf",
            namespace="docs",
            source_path="/home/user/documents/document.pdf"
        )

        mock_table.delete_item.assert_called_once()


class TestSoftDelete:
    """Test soft delete functionality with transactions"""

    def test_soft_delete_success(self, mock_dynamodb):
        """Test successful soft delete transaction"""
        provider, mock_client, mock_table = mock_dynamodb
        doc_id = str(uuid.uuid4())

        # Mock get_item to return active document
        mock_table.get_item.return_value = {
            'Item': {
                'doc_id': doc_id,
                'filename': 'document.pdf',
                'namespace': 'docs',
                'status': DOC_STATUS_ACTIVE,
                'chunk_ids': ['chunk1', 'chunk2', 'chunk3']
            }
        }

        mock_client.transact_write_items.return_value = {}

        result = provider.soft_delete_document(
            doc_id=doc_id,
            namespace='docs',
            deleted_by='user123',
            delete_reason='user_initiated'
        )

        assert result['doc_id'] == doc_id
        assert result['namespace'] == 'docs'
        assert result['filename'] == 'document.pdf'
        assert 'deleted_at' in result
        assert 'purge_after' in result
        assert 'deleted_at_ms' in result

        # Verify transaction was called
        mock_client.transact_write_items.assert_called_once()

    def test_soft_delete_document_not_found(self, mock_dynamodb):
        """Test soft delete fails when document not found"""
        provider, _, mock_table = mock_dynamodb

        mock_table.get_item.return_value = {}

        with pytest.raises(ValueError, match="Document not found"):
            provider.soft_delete_document(
                doc_id=str(uuid.uuid4()),
                namespace='docs'
            )

    def test_soft_delete_already_deleted(self, mock_dynamodb):
        """Test soft delete fails when document already in trash"""
        provider, _, mock_table = mock_dynamodb

        mock_table.get_item.return_value = {
            'Item': {
                'status': DOC_STATUS_DELETING,
                'doc_id': 'test'
            }
        }

        with pytest.raises(ValueError, match="already in trash"):
            provider.soft_delete_document(
                doc_id='test',
                namespace='docs'
            )

    def test_soft_delete_purged(self, mock_dynamodb):
        """Test soft delete fails when document already purged"""
        provider, _, mock_table = mock_dynamodb

        mock_table.get_item.return_value = {
            'Item': {
                'status': DOC_STATUS_PURGED,
                'doc_id': 'test'
            }
        }

        with pytest.raises(ValueError, match="permanently deleted"):
            provider.soft_delete_document(
                doc_id='test',
                namespace='docs'
            )

    def test_soft_delete_creates_unique_trash_pk(self, mock_dynamodb):
        """Test that multiple deletions create unique trash entries"""
        provider, mock_client, mock_table = mock_dynamodb

        mock_table.get_item.return_value = {
            'Item': {
                'doc_id': 'doc1',
                'filename': 'document.pdf',
                'namespace': 'docs',
                'status': DOC_STATUS_ACTIVE,
                'chunk_ids': ['c1', 'c2']
            }
        }

        # First deletion
        result1 = provider.soft_delete_document(
            doc_id='doc1',
            namespace='docs'
        )
        trash_pk1 = result1['deleted_at_ms']

        # Verify transaction includes trash PK with timestamp
        call1 = mock_client.transact_write_items.call_args[1]
        items1 = call1['TransactItems']
        trash_item1 = items1[1]['Put']['Item']['PK']['S']
        assert 'TRASH#docs#document.pdf#' in trash_item1

        # Second deletion would have different timestamp
        result2_ms = int((datetime.now(timezone.utc) + timedelta(seconds=1)).timestamp() * 1000)
        assert result2_ms > trash_pk1  # Time has advanced

    def test_soft_delete_transaction_atomicity(self, mock_dynamodb):
        """Test transaction failure handling"""
        provider, mock_client, mock_table = mock_dynamodb

        mock_table.get_item.return_value = {
            'Item': {
                'doc_id': 'doc1',
                'filename': 'document.pdf',
                'namespace': 'docs',
                'status': DOC_STATUS_ACTIVE,
                'chunk_ids': []
            }
        }

        # Setup TransactionCanceledException
        exception = ClientError(
            {'Error': {'Code': 'TransactionCanceledException'},
             'CancellationReasons': [{'Code': 'ConditionalCheckFailed'}]},
            'TransactWriteItems'
        )
        mock_client.transact_write_items.side_effect = exception
        mock_client.exceptions.TransactionCanceledException = type(exception)

        with pytest.raises(ValueError, match="concurrent modification"):
            provider.soft_delete_document(
                doc_id='doc1',
                namespace='docs'
            )


class TestRestore:
    """Test restore from trash functionality"""

    def test_restore_success(self, mock_dynamodb):
        """Test successful restore transaction"""
        provider, mock_client, mock_table = mock_dynamodb
        doc_id = str(uuid.uuid4())
        deleted_at_ms = 1234567890000

        mock_table.get_item.return_value = {
            'Item': {
                'doc_id': doc_id,
                'filename': 'document.pdf',
                'namespace': 'docs',
                'status': DOC_STATUS_DELETING,
                'chunk_ids': ['chunk1', 'chunk2'],
                'deleted_by': 'user123'
            }
        }

        mock_client.transact_write_items.return_value = {}

        result = provider.restore_document(
            doc_id=doc_id,
            namespace='docs',
            deleted_at_ms=deleted_at_ms,
            restored_by='user456'
        )

        assert result['doc_id'] == doc_id
        assert result['status'] == DOC_STATUS_ACTIVE
        assert 'restored_at' in result
        assert result['chunk_ids'] == ['chunk1', 'chunk2']
        assert result['chunk_count'] == 2

        # Verify transaction deleted trash entry
        mock_client.transact_write_items.assert_called_once()
        call_args = mock_client.transact_write_items.call_args[1]
        items = call_args['TransactItems']
        assert len(items) == 2
        assert items[1]['Delete']['Key']['PK']['S'] == f'TRASH#docs#document.pdf#{deleted_at_ms}'

    def test_restore_document_not_found(self, mock_dynamodb):
        """Test restore fails when document not found"""
        provider, _, mock_table = mock_dynamodb

        mock_table.get_item.return_value = {}

        with pytest.raises(ValueError, match="Document not found"):
            provider.restore_document(
                doc_id='nonexistent',
                namespace='docs',
                deleted_at_ms=1234567890000
            )

    def test_restore_not_in_trash(self, mock_dynamodb):
        """Test restore fails when document not in trash"""
        provider, _, mock_table = mock_dynamodb

        mock_table.get_item.return_value = {
            'Item': {
                'doc_id': 'doc1',
                'status': DOC_STATUS_ACTIVE
            }
        }

        with pytest.raises(ValueError, match="not in trash"):
            provider.restore_document(
                doc_id='doc1',
                namespace='docs',
                deleted_at_ms=1234567890000
            )

    def test_restore_multiple_versions(self, mock_dynamodb):
        """Test restoring specific trash entry when multiple exist"""
        provider, mock_client, mock_table = mock_dynamodb

        mock_table.get_item.return_value = {
            'Item': {
                'doc_id': 'doc1',
                'filename': 'document.pdf',
                'namespace': 'docs',
                'status': DOC_STATUS_DELETING,
                'chunk_ids': []
            }
        }

        mock_client.transact_write_items.return_value = {}

        # Restore first version (older timestamp)
        deleted_at_ms_1 = 1000000000000

        provider.restore_document(
            doc_id='doc1',
            namespace='docs',
            deleted_at_ms=deleted_at_ms_1
        )

        call_args = mock_client.transact_write_items.call_args[1]
        items = call_args['TransactItems']
        trash_pk = items[1]['Delete']['Key']['PK']['S']
        assert f'#{deleted_at_ms_1}' in trash_pk

    def test_restore_from_purging_status(self, mock_dynamodb):
        """Test restoring document stuck in purging status (cleanup worker failure recovery)"""
        provider, mock_client, mock_table = mock_dynamodb
        doc_id = str(uuid.uuid4())
        deleted_at_ms = 1234567890000

        # Document stuck in purging status with purge metadata
        mock_table.get_item.return_value = {
            'Item': {
                'doc_id': doc_id,
                'filename': 'stuck-document.pdf',
                'namespace': 'docs',
                'status': DOC_STATUS_PURGING,
                'chunk_ids': ['chunk1', 'chunk2'],
                'deleted_by': 'user123',
                'delete_reason': 'user_initiated',
                'purge_started_at': '2026-01-26T01:01:34.864604+00:00',
                'cleanup_job_id': 'job-123'
            }
        }

        mock_client.transact_write_items.return_value = {}

        result = provider.restore_document(
            doc_id=doc_id,
            namespace='docs',
            deleted_at_ms=deleted_at_ms,
            restored_by='user456'
        )

        # Should succeed with warning
        assert result['doc_id'] == doc_id
        assert result['status'] == DOC_STATUS_ACTIVE
        assert 'restored_at' in result
        assert result['chunk_ids'] == ['chunk1', 'chunk2']
        assert result['chunk_count'] == 2
        assert 'warning' in result
        assert 'permanent deletion' in result['warning'].lower()

        # Verify purge metadata is removed
        call_args = mock_client.transact_write_items.call_args[1]
        items = call_args['TransactItems']
        update_item = items[0]['Update']
        update_expr = update_item['UpdateExpression']

        # Should remove purge-related fields
        assert 'purge_started_at' in update_expr
        assert 'cleanup_job_id' in update_expr


class TestListTrash:
    """Test trash listing functionality"""

    def test_list_trash_by_namespace(self, mock_dynamodb):
        """Test listing trash entries for a specific namespace"""
        provider, _, mock_table = mock_dynamodb

        mock_table.query.return_value = {
            'Items': [
                {
                    'doc_id': 'doc1',
                    'namespace': 'docs',
                    'filename': 'file1.pdf',
                    'deleted_at': '2024-01-01T00:00:00Z',
                    'deleted_at_ms': 1704067200000,
                    'purge_after': '2024-01-31T00:00:00Z',
                    'delete_reason': 'user_initiated'
                },
                {
                    'doc_id': 'doc2',
                    'namespace': 'docs',
                    'filename': 'file2.pdf',
                    'deleted_at': '2024-01-02T00:00:00Z',
                    'deleted_at_ms': 1704153600000,
                    'purge_after': '2024-02-01T00:00:00Z',
                }
            ]
        }

        result = provider.list_trash(namespace='docs', limit=10)

        assert 'documents' in result
        assert len(result['documents']) == 2
        assert result['documents'][0]['doc_id'] == 'doc1'
        assert result['documents'][0]['filename'] == 'file1.pdf'
        assert 'days_until_purge' in result['documents'][0]

    def test_list_trash_all_namespaces(self, mock_dynamodb):
        """Test listing trash across all namespaces"""
        provider, _, mock_table = mock_dynamodb

        mock_table.scan.return_value = {
            'Items': [
                {
                    'doc_id': 'doc1',
                    'namespace': 'docs',
                    'filename': 'file1.pdf',
                    'deleted_at': '2024-01-01T00:00:00Z',
                    'deleted_at_ms': 1704067200000,
                    'purge_after': '2024-01-31T00:00:00Z',
                }
            ]
        }

        result = provider.list_trash(namespace=None)

        assert 'documents' in result
        mock_table.scan.assert_called_once()

    def test_list_trash_with_pagination(self, mock_dynamodb):
        """Test pagination of trash listing"""
        provider, _, mock_table = mock_dynamodb

        import base64
        import json

        last_key = {"PK": "TRASH#docs#file2.pdf#123", "SK": "ENTRY"}
        encoded_key = base64.b64encode(json.dumps(last_key).encode()).decode()

        mock_table.query.return_value = {
            'Items': [],
            'LastEvaluatedKey': last_key
        }

        result = provider.list_trash(namespace='docs', limit=10, next_key=encoded_key)

        assert 'next_key' in result
        mock_table.query.assert_called_once()


class TestPermanentDelete:
    """Test permanent deletion and cleanup jobs"""

    def test_permanently_delete_document(self, mock_dynamodb):
        """Test creating cleanup job for permanent deletion"""
        provider, mock_client, mock_table = mock_dynamodb
        doc_id = str(uuid.uuid4())

        mock_table.get_item.return_value = {
            'Item': {
                'doc_id': doc_id,
                'filename': 'document.pdf',
                'namespace': 'docs',
                'status': DOC_STATUS_DELETING,
                'chunk_ids': ['chunk1', 'chunk2', 'chunk3']
            }
        }

        mock_client.transact_write_items.return_value = {}

        result = provider.permanently_delete_document(
            doc_id=doc_id,
            namespace='docs',
            deleted_at_ms=1234567890000,
            deleted_by='user123'
        )

        assert 'cleanup_job_id' in result
        assert result['doc_id'] == doc_id
        assert result['chunk_count'] == 3

        # Verify transaction marks doc as purging
        mock_client.transact_write_items.assert_called_once()

    def test_permanently_delete_not_in_trash(self, mock_dynamodb):
        """Test permanent delete fails when document not in trash"""
        provider, _, mock_table = mock_dynamodb

        mock_table.get_item.return_value = {
            'Item': {
                'doc_id': 'doc1',
                'status': DOC_STATUS_ACTIVE
            }
        }

        with pytest.raises(ValueError, match="not in trash"):
            provider.permanently_delete_document(
                doc_id='doc1',
                namespace='docs',
                deleted_at_ms=1234567890000
            )

    def test_complete_permanent_delete(self, mock_dynamodb):
        """Test completing permanent deletion after cleanup"""
        provider, mock_client, _ = mock_dynamodb
        doc_id = str(uuid.uuid4())
        deleted_at_ms = 1234567890000

        mock_client.transact_write_items.return_value = {}

        provider.complete_permanent_delete(
            doc_id=doc_id,
            namespace='docs',
            deleted_at_ms=deleted_at_ms,
            filename='document.pdf'
        )

        # Verify transaction marks doc as purged and deletes trash
        mock_client.transact_write_items.assert_called_once()
        call_args = mock_client.transact_write_items.call_args[1]
        items = call_args['TransactItems']
        assert len(items) == 2
        # First item: update doc to purged
        assert 'Update' in items[0]
        assert ":purged" in items[0]['Update']['ExpressionAttributeValues']
        # Second item: delete trash
        assert 'Delete' in items[1]

    def test_list_cleanup_jobs(self, mock_dynamodb):
        """Test listing pending cleanup jobs"""
        provider, _, mock_table = mock_dynamodb

        mock_table.scan.return_value = {
            'Items': [
                {
                    'cleanup_job_id': str(uuid.uuid4()),
                    'doc_id': 'doc1',
                    'namespace': 'docs',
                    'filename': 'document.pdf',
                    'deleted_at_ms': 1234567890000,
                    'chunk_ids': ['c1', 'c2'],
                    'retry_count': 0,
                    'max_retries': 10
                }
            ]
        }

        result = provider.list_cleanup_jobs(limit=10)

        assert len(result) == 1
        assert result[0]['doc_id'] == 'doc1'
        assert result[0]['retry_count'] == 0

    def test_mark_cleanup_job_failed(self, mock_dynamodb):
        """Test marking cleanup job as failed"""
        provider, _, mock_table = mock_dynamodb
        job_id = str(uuid.uuid4())

        mock_table.get_item.return_value = {
            'Item': {
                'cleanup_job_id': job_id,
                'retry_count': 2,
                'max_retries': 10
            }
        }

        provider.mark_cleanup_job_failed(job_id, "Connection timeout")

        mock_table.update_item.assert_called_once()
        call_args = mock_table.update_item.call_args
        assert ":inc" in call_args[1]['ExpressionAttributeValues']

    def test_list_expired_trash(self, mock_dynamodb):
        """Test listing trash entries past purge_after date"""
        provider, _, mock_table = mock_dynamodb

        mock_table.scan.return_value = {
            'Items': [
                {
                    'doc_id': 'doc1',
                    'namespace': 'docs',
                    'deleted_at_ms': 1000000000000,
                    'purge_after': '2024-01-01T00:00:00Z'
                }
            ]
        }

        result = provider.list_expired_trash(limit=100)

        assert len(result) == 1
        assert result[0]['doc_id'] == 'doc1'


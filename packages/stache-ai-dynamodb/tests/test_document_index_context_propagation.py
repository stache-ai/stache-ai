"""Context-propagation tests for the DynamoDB document index.

Proves ``context`` is forwarded into nested data calls (H1) and into the
private update helpers (L1), not merely accepted.
"""
from unittest.mock import MagicMock

from stache_ai_dynamodb.document_index import DynamoDBDocumentIndex

CTX = object()


def _provider():
    prov = DynamoDBDocumentIndex.__new__(DynamoDBDocumentIndex)
    prov.table = MagicMock()
    prov.client = MagicMock()
    prov.table_name = "test-table"
    return prov


def test_get_chunk_ids_forwards_context_into_get_document():
    prov = _provider()
    prov.get_document = MagicMock(return_value={"chunk_ids": ["a", "b"]})

    result = prov.get_chunk_ids("doc-1", "ns-1", context=CTX)

    assert result == ["a", "b"]
    prov.get_document.assert_called_once_with("doc-1", "ns-1", context=CTX)


def test_update_document_metadata_forwards_context_into_migrate():
    prov = _provider()
    prov._migrate_namespace = MagicMock(return_value=True)
    prov._update_in_place = MagicMock(return_value=True)

    prov.update_document_metadata("doc-1", "ns-1", {"namespace": "ns-2"}, context=CTX)

    prov._migrate_namespace.assert_called_once_with(
        "doc-1", "ns-1", {"namespace": "ns-2"}, context=CTX
    )
    prov._update_in_place.assert_not_called()


def test_update_document_metadata_forwards_context_into_update_in_place():
    prov = _provider()
    prov._migrate_namespace = MagicMock(return_value=True)
    prov._update_in_place = MagicMock(return_value=True)

    prov.update_document_metadata("doc-1", "ns-1", {"filename": "new.txt"}, context=CTX)

    prov._update_in_place.assert_called_once_with(
        "doc-1", "ns-1", {"filename": "new.txt"}, context=CTX
    )
    prov._migrate_namespace.assert_not_called()

"""Context-propagation tests for core/operations.py (M2).

Proves every ``do_*`` operation FORWARDS its ``context`` argument into the
underlying pipeline / provider call, rather than dropping it. A sentinel
object is threaded in and identity is asserted on the recorded call.
"""
from unittest.mock import AsyncMock, MagicMock, patch

from stache_ai.core import operations

CTX = object()


@patch("stache_ai.core.operations.get_pipeline")
def test_do_search_forwards_context(mock_get_pipeline):
    pipeline = MagicMock()
    mock_get_pipeline.return_value = pipeline
    pipeline.query = AsyncMock(return_value={"sources": []})

    operations.do_search(query="q", context=CTX)

    assert pipeline.query.call_args.kwargs["context"] is CTX


@patch("stache_ai.core.operations.get_pipeline")
def test_do_ingest_text_forwards_context(mock_get_pipeline):
    pipeline = MagicMock()
    mock_get_pipeline.return_value = pipeline
    pipeline.ingest_text = AsyncMock(return_value={"success": True})

    operations.do_ingest_text(text="hello", context=CTX)

    assert pipeline.ingest_text.call_args.kwargs["context"] is CTX


@patch("stache_ai.core.operations.NamespaceProviderFactory")
def test_do_list_namespaces_forwards_context(mock_factory):
    provider = MagicMock()
    mock_factory.create.return_value = provider
    provider.list.return_value = []

    operations.do_list_namespaces(context=CTX)

    provider.list.assert_called_once_with(include_children=True, context=CTX)


@patch("stache_ai.core.operations.get_pipeline")
def test_do_list_documents_forwards_context(mock_get_pipeline):
    pipeline = MagicMock()
    mock_get_pipeline.return_value = pipeline
    pipeline.document_index_provider.list_documents.return_value = {
        "documents": [], "next_key": None
    }

    operations.do_list_documents(namespace="ns", context=CTX)

    assert pipeline.document_index_provider.list_documents.call_args.kwargs["context"] is CTX


@patch("stache_ai.core.operations.get_pipeline")
def test_do_get_document_forwards_context(mock_get_pipeline):
    pipeline = MagicMock()
    mock_get_pipeline.return_value = pipeline
    pipeline.document_index_provider.get_document.return_value = {"id": "d"}

    operations.do_get_document(doc_id="d", namespace="ns", context=CTX)

    assert pipeline.document_index_provider.get_document.call_args.kwargs["context"] is CTX


@patch("stache_ai.core.operations.NamespaceProviderFactory")
def test_do_create_namespace_forwards_context(mock_factory):
    provider = MagicMock()
    mock_factory.create.return_value = provider
    provider.create.return_value = {"id": "x"}

    operations.do_create_namespace(id="x", name="X", context=CTX)

    assert provider.create.call_args.kwargs["context"] is CTX


@patch("stache_ai.core.operations.NamespaceProviderFactory")
def test_do_get_namespace_forwards_context(mock_factory):
    provider = MagicMock()
    mock_factory.create.return_value = provider
    provider.get.return_value = {"id": "x"}

    operations.do_get_namespace(id="x", context=CTX)

    provider.get.assert_called_once_with("x", context=CTX)


@patch("stache_ai.core.operations.NamespaceProviderFactory")
def test_do_update_namespace_forwards_context(mock_factory):
    provider = MagicMock()
    mock_factory.create.return_value = provider
    provider.update.return_value = {"id": "x"}

    operations.do_update_namespace(id="x", name="New", context=CTX)

    assert provider.update.call_args.kwargs["context"] is CTX


@patch("stache_ai.core.operations.NamespaceProviderFactory")
def test_do_delete_namespace_forwards_context(mock_factory):
    provider = MagicMock()
    mock_factory.create.return_value = provider
    provider.delete.return_value = True

    operations.do_delete_namespace(id="x", cascade=True, context=CTX)

    provider.delete.assert_called_once_with(id="x", cascade=True, context=CTX)


@patch("stache_ai.core.operations.get_pipeline")
def test_do_delete_document_forwards_context_into_all_calls(mock_get_pipeline):
    pipeline = MagicMock()
    mock_get_pipeline.return_value = pipeline
    doc_index = pipeline.document_index_provider
    doc_index.get_chunk_ids.return_value = ["c1", "c2"]
    vectordb = pipeline.vectordb_provider

    operations.do_delete_document(doc_id="d", namespace="ns", context=CTX)

    assert doc_index.get_chunk_ids.call_args.kwargs["context"] is CTX
    assert vectordb.delete.call_args.kwargs["context"] is CTX
    assert doc_index.delete_document.call_args.kwargs["context"] is CTX

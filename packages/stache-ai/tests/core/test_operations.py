"""Tests for core operations shared by HTTP routes and AgentCore handler"""

from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from stache_ai.core.operations import (
    do_get_document,
    do_ingest_text,
    do_list_documents,
    do_list_namespaces,
    do_search,
)


class TestDoSearch:
    """Tests for do_search operation"""

    @patch('stache_ai.core.operations.get_pipeline')
    def test_calls_pipeline_query_with_synthesize_false(self, mock_get_pipeline):
        """Test that do_search calls pipeline.query with synthesize=False"""
        mock_pipeline = MagicMock()
        mock_get_pipeline.return_value = mock_pipeline
        mock_pipeline.query.return_value = {
            "question": "test query",
            "sources": [],
            "answer": "test answer"
        }

        result = do_search(query="test query")

        mock_pipeline.query.assert_called_once()
        call_kwargs = mock_pipeline.query.call_args[1]
        assert call_kwargs['synthesize'] == False
        assert call_kwargs['question'] == "test query"

    @patch('stache_ai.core.operations.get_pipeline')
    def test_top_k_capped_at_50(self, mock_get_pipeline):
        """Test that top_k is capped at 50 when exceeding"""
        mock_pipeline = MagicMock()
        mock_get_pipeline.return_value = mock_pipeline
        mock_pipeline.query.return_value = {
            "question": "test",
            "sources": []
        }

        result = do_search(query="test", top_k=100)

        call_kwargs = mock_pipeline.query.call_args[1]
        assert call_kwargs['top_k'] == 50

    @patch('stache_ai.core.operations.get_pipeline')
    def test_top_k_not_capped_below_50(self, mock_get_pipeline):
        """Test that top_k is not modified when below 50"""
        mock_pipeline = MagicMock()
        mock_get_pipeline.return_value = mock_pipeline
        mock_pipeline.query.return_value = {
            "question": "test",
            "sources": []
        }

        result = do_search(query="test", top_k=25)

        call_kwargs = mock_pipeline.query.call_args[1]
        assert call_kwargs['top_k'] == 25

    @patch('stache_ai.core.operations.get_pipeline')
    def test_request_id_in_response(self, mock_get_pipeline):
        """Test that request_id is included in response"""
        mock_pipeline = MagicMock()
        mock_get_pipeline.return_value = mock_pipeline
        mock_pipeline.query.return_value = {
            "question": "test",
            "sources": []
        }

        result = do_search(query="test", request_id="test-123")

        assert result['request_id'] == "test-123"

    @patch('stache_ai.core.operations.get_pipeline')
    def test_generates_request_id_if_not_provided(self, mock_get_pipeline):
        """Test that request_id is generated if not provided"""
        mock_pipeline = MagicMock()
        mock_get_pipeline.return_value = mock_pipeline
        mock_pipeline.query.return_value = {
            "question": "test",
            "sources": []
        }

        result = do_search(query="test")

        assert 'request_id' in result
        assert len(result['request_id']) > 0

    @patch('stache_ai.core.operations.get_pipeline')
    def test_passes_namespace_parameter(self, mock_get_pipeline):
        """Test that namespace parameter is passed through"""
        mock_pipeline = MagicMock()
        mock_get_pipeline.return_value = mock_pipeline
        mock_pipeline.query.return_value = {
            "question": "test",
            "sources": []
        }

        result = do_search(query="test", namespace="test-ns")

        call_kwargs = mock_pipeline.query.call_args[1]
        assert call_kwargs['namespace'] == "test-ns"

    @patch('stache_ai.core.operations.get_pipeline')
    def test_passes_rerank_parameter(self, mock_get_pipeline):
        """Test that rerank parameter is passed through"""
        mock_pipeline = MagicMock()
        mock_get_pipeline.return_value = mock_pipeline
        mock_pipeline.query.return_value = {
            "question": "test",
            "sources": []
        }

        result = do_search(query="test", rerank=False)

        call_kwargs = mock_pipeline.query.call_args[1]
        assert call_kwargs['rerank'] == False

    @patch('stache_ai.core.operations.get_pipeline')
    def test_returns_error_on_exception(self, mock_get_pipeline):
        """Test that exceptions are caught and returned as error dict"""
        mock_pipeline = MagicMock()
        mock_get_pipeline.return_value = mock_pipeline
        mock_pipeline.query.side_effect = Exception("Pipeline error")

        result = do_search(query="test")

        assert 'error' in result
        assert result['error'] == "Pipeline error"
        assert result['question'] == "test"
        assert result['sources'] == []
        assert 'request_id' in result


class TestDoIngestText:
    """Tests for do_ingest_text operation"""

    @patch('stache_ai.core.operations.get_pipeline')
    def test_calls_pipeline_ingest_text(self, mock_get_pipeline):
        """Test that do_ingest_text calls pipeline.ingest_text with correct params"""
        mock_pipeline = MagicMock()
        mock_get_pipeline.return_value = mock_pipeline
        mock_pipeline.ingest_text.return_value = {
            "success": True,
            "chunks_created": 5
        }

        result = do_ingest_text(
            text="Test text content",
            metadata={"source": "test"},
            namespace="test-ns"
        )

        mock_pipeline.ingest_text.assert_called_once()
        call_kwargs = mock_pipeline.ingest_text.call_args[1]
        assert call_kwargs['text'] == "Test text content"
        assert call_kwargs['metadata'] == {"source": "test"}
        assert call_kwargs['namespace'] == "test-ns"

    @patch('stache_ai.core.operations.get_pipeline')
    def test_raises_value_error_for_text_exceeding_100kb(self, mock_get_pipeline):
        """Test that ValueError is raised for text exceeding 100KB"""
        mock_pipeline = MagicMock()
        mock_get_pipeline.return_value = mock_pipeline

        # Create text larger than 100KB
        large_text = "a" * (101 * 1024)

        with pytest.raises(ValueError) as exc_info:
            do_ingest_text(text=large_text)

        assert "exceeds maximum size of 100KB" in str(exc_info.value)

    def test_accepts_text_exactly_100kb(self):
        """Test that 100KB text is accepted (not rejected)"""
        with patch('stache_ai.core.operations.get_pipeline') as mock_get_pipeline:
            mock_pipeline = MagicMock()
            mock_get_pipeline.return_value = mock_pipeline
            mock_pipeline.ingest_text.return_value = {
                "success": True,
                "chunks_created": 1
            }

            # Create text exactly 100KB
            text_100kb = "a" * (100 * 1024)

            result = do_ingest_text(text=text_100kb)

            assert mock_pipeline.ingest_text.called

    @patch('stache_ai.core.operations.get_pipeline')
    def test_request_id_in_response(self, mock_get_pipeline):
        """Test that request_id is included in response"""
        mock_pipeline = MagicMock()
        mock_get_pipeline.return_value = mock_pipeline
        mock_pipeline.ingest_text.return_value = {
            "success": True,
            "chunks_created": 1
        }

        result = do_ingest_text(text="test", request_id="ingest-123")

        assert result['request_id'] == "ingest-123"

    @patch('stache_ai.core.operations.get_pipeline')
    def test_generates_request_id_if_not_provided(self, mock_get_pipeline):
        """Test that request_id is generated if not provided"""
        mock_pipeline = MagicMock()
        mock_get_pipeline.return_value = mock_pipeline
        mock_pipeline.ingest_text.return_value = {
            "success": True,
            "chunks_created": 1
        }

        result = do_ingest_text(text="test")

        assert 'request_id' in result
        assert len(result['request_id']) > 0

    @patch('stache_ai.core.operations.get_pipeline')
    def test_returns_error_on_pipeline_exception(self, mock_get_pipeline):
        """Test that pipeline exceptions are caught and returned as error dict"""
        mock_pipeline = MagicMock()
        mock_get_pipeline.return_value = mock_pipeline
        mock_pipeline.ingest_text.side_effect = Exception("Ingest failed")

        result = do_ingest_text(text="test")

        assert 'error' in result
        assert result['error'] == "Ingest failed"
        assert result['success'] == False
        assert 'request_id' in result

    @patch('stache_ai.core.operations.get_pipeline')
    def test_value_error_propagates_not_caught(self, mock_get_pipeline):
        """Test that ValueError is re-raised (not caught)"""
        large_text = "a" * (101 * 1024)

        with pytest.raises(ValueError):
            do_ingest_text(text=large_text)


class TestDoListNamespaces:
    """Tests for do_list_namespaces operation"""

    @patch('stache_ai.core.operations.NamespaceProviderFactory')
    def test_calls_namespace_provider_list(self, mock_factory):
        """Test that do_list_namespaces calls namespace_provider.list()"""
        mock_provider = MagicMock()
        mock_factory.create.return_value = mock_provider
        mock_provider.list.return_value = [
            {"id": "ns1", "name": "Namespace 1"},
            {"id": "ns2", "name": "Namespace 2"}
        ]

        result = do_list_namespaces()

        mock_factory.create.assert_called_once()
        mock_provider.list.assert_called_once()

    @patch('stache_ai.core.operations.NamespaceProviderFactory')
    def test_returns_count_and_namespaces(self, mock_factory):
        """Test that response includes count and namespaces"""
        mock_provider = MagicMock()
        mock_factory.create.return_value = mock_provider
        mock_provider.list.return_value = [
            {"id": "ns1", "name": "Namespace 1"},
            {"id": "ns2", "name": "Namespace 2"}
        ]

        result = do_list_namespaces()

        assert 'namespaces' in result
        assert 'count' in result
        assert result['count'] == 2
        assert len(result['namespaces']) == 2

    @patch('stache_ai.core.operations.NamespaceProviderFactory')
    def test_request_id_in_response(self, mock_factory):
        """Test that request_id is included in response"""
        mock_provider = MagicMock()
        mock_factory.create.return_value = mock_provider
        mock_provider.list.return_value = []

        result = do_list_namespaces(request_id="ns-123")

        assert result['request_id'] == "ns-123"

    @patch('stache_ai.core.operations.NamespaceProviderFactory')
    def test_generates_request_id_if_not_provided(self, mock_factory):
        """Test that request_id is generated if not provided"""
        mock_provider = MagicMock()
        mock_factory.create.return_value = mock_provider
        mock_provider.list.return_value = []

        result = do_list_namespaces()

        assert 'request_id' in result
        assert len(result['request_id']) > 0

    @patch('stache_ai.core.operations.NamespaceProviderFactory')
    def test_returns_error_on_exception(self, mock_factory):
        """Test that exceptions are caught and returned as error dict"""
        mock_provider = MagicMock()
        mock_factory.create.return_value = mock_provider
        mock_provider.list.side_effect = Exception("Provider error")

        result = do_list_namespaces()

        assert 'error' in result
        assert result['error'] == "Provider error"
        assert result['namespaces'] == []
        assert result['count'] == 0
        assert 'request_id' in result

    @patch('stache_ai.core.operations.NamespaceProviderFactory')
    def test_returns_empty_list_on_no_namespaces(self, mock_factory):
        """Test that empty list is returned when no namespaces exist"""
        mock_provider = MagicMock()
        mock_factory.create.return_value = mock_provider
        mock_provider.list.return_value = []

        result = do_list_namespaces()

        assert result['namespaces'] == []
        assert result['count'] == 0


class TestDoListDocuments:
    """Tests for do_list_documents operation"""

    @patch('stache_ai.core.operations.get_pipeline')
    def test_calls_document_index_provider_list_documents(self, mock_get_pipeline):
        """Test that do_list_documents calls document_index_provider.list_documents"""
        mock_pipeline = MagicMock()
        mock_get_pipeline.return_value = mock_pipeline
        mock_document_provider = MagicMock()
        type(mock_pipeline).document_index_provider = PropertyMock(return_value=mock_document_provider)
        mock_document_provider.list_documents.return_value = {
            "documents": [{"id": "doc1", "name": "Doc 1"}],
            "next_key": None
        }

        result = do_list_documents(namespace="test-ns", limit=50)

        mock_document_provider.list_documents.assert_called_once()
        call_kwargs = mock_document_provider.list_documents.call_args[1]
        assert call_kwargs['namespace'] == "test-ns"
        assert call_kwargs['limit'] == 50

    @patch('stache_ai.core.operations.get_pipeline')
    def test_limit_capped_at_100(self, mock_get_pipeline):
        """Test that limit is capped at 100 when exceeding"""
        mock_pipeline = MagicMock()
        mock_get_pipeline.return_value = mock_pipeline
        mock_document_provider = MagicMock()
        type(mock_pipeline).document_index_provider = PropertyMock(return_value=mock_document_provider)
        mock_document_provider.list_documents.return_value = {
            "documents": [],
            "next_key": None
        }

        result = do_list_documents(limit=200)

        call_kwargs = mock_document_provider.list_documents.call_args[1]
        assert call_kwargs['limit'] == 100

    @patch('stache_ai.core.operations.get_pipeline')
    def test_limit_not_capped_below_100(self, mock_get_pipeline):
        """Test that limit is not modified when below 100"""
        mock_pipeline = MagicMock()
        mock_get_pipeline.return_value = mock_pipeline
        mock_document_provider = MagicMock()
        type(mock_pipeline).document_index_provider = PropertyMock(return_value=mock_document_provider)
        mock_document_provider.list_documents.return_value = {
            "documents": [],
            "next_key": None
        }

        result = do_list_documents(limit=75)

        call_kwargs = mock_document_provider.list_documents.call_args[1]
        assert call_kwargs['limit'] == 75

    @patch('stache_ai.core.operations.get_pipeline')
    def test_next_key_passed_through(self, mock_get_pipeline):
        """Test that next_key is passed through to provider as last_evaluated_key"""
        mock_pipeline = MagicMock()
        mock_get_pipeline.return_value = mock_pipeline
        mock_document_provider = MagicMock()
        type(mock_pipeline).document_index_provider = PropertyMock(return_value=mock_document_provider)
        mock_document_provider.list_documents.return_value = {
            "documents": [],
            "next_key": None
        }

        result = do_list_documents(next_key="pagination-key")

        call_kwargs = mock_document_provider.list_documents.call_args[1]
        assert call_kwargs['last_evaluated_key'] == "pagination-key"

    @patch('stache_ai.core.operations.get_pipeline')
    def test_returns_error_when_provider_is_none(self, mock_get_pipeline):
        """Test that error is returned when document_index_provider is None"""
        mock_pipeline = MagicMock()
        mock_get_pipeline.return_value = mock_pipeline
        type(mock_pipeline).document_index_provider = PropertyMock(return_value=None)

        result = do_list_documents()

        assert 'error' in result
        assert "Document index feature is disabled" in result['error']
        assert result['documents'] == []
        assert result['next_key'] is None

    @patch('stache_ai.core.operations.get_pipeline')
    def test_request_id_in_response(self, mock_get_pipeline):
        """Test that request_id is included in response"""
        mock_pipeline = MagicMock()
        mock_get_pipeline.return_value = mock_pipeline
        mock_document_provider = MagicMock()
        type(mock_pipeline).document_index_provider = PropertyMock(return_value=mock_document_provider)
        mock_document_provider.list_documents.return_value = {
            "documents": [],
            "next_key": None
        }

        result = do_list_documents(request_id="doc-list-123")

        assert result['request_id'] == "doc-list-123"

    @patch('stache_ai.core.operations.get_pipeline')
    def test_generates_request_id_if_not_provided(self, mock_get_pipeline):
        """Test that request_id is generated if not provided"""
        mock_pipeline = MagicMock()
        mock_get_pipeline.return_value = mock_pipeline
        mock_document_provider = MagicMock()
        type(mock_pipeline).document_index_provider = PropertyMock(return_value=mock_document_provider)
        mock_document_provider.list_documents.return_value = {
            "documents": [],
            "next_key": None
        }

        result = do_list_documents()

        assert 'request_id' in result
        assert len(result['request_id']) > 0

    @patch('stache_ai.core.operations.get_pipeline')
    def test_returns_error_on_exception(self, mock_get_pipeline):
        """Test that exceptions are caught and returned as error dict"""
        mock_pipeline = MagicMock()
        mock_get_pipeline.return_value = mock_pipeline
        mock_document_provider = MagicMock()
        type(mock_pipeline).document_index_provider = PropertyMock(return_value=mock_document_provider)
        mock_document_provider.list_documents.side_effect = Exception("List failed")

        result = do_list_documents()

        assert 'error' in result
        assert result['error'] == "List failed"
        assert result['documents'] == []
        assert result['next_key'] is None


class TestDoGetDocument:
    """Tests for do_get_document operation"""

    @patch('stache_ai.core.operations.get_pipeline')
    def test_calls_document_index_provider_get_document(self, mock_get_pipeline):
        """Test that do_get_document calls document_index_provider.get_document"""
        mock_pipeline = MagicMock()
        mock_get_pipeline.return_value = mock_pipeline
        mock_document_provider = MagicMock()
        type(mock_pipeline).document_index_provider = PropertyMock(return_value=mock_document_provider)
        mock_document_provider.get_document.return_value = {
            "id": "doc1",
            "name": "Document 1",
            "content": "Sample content"
        }

        result = do_get_document(doc_id="doc1", namespace="test-ns")

        mock_document_provider.get_document.assert_called_once()
        call_kwargs = mock_document_provider.get_document.call_args[1]
        assert call_kwargs['doc_id'] == "doc1"
        assert call_kwargs['namespace'] == "test-ns"

    @patch('stache_ai.core.operations.get_pipeline')
    def test_returns_error_dict_when_document_not_found(self, mock_get_pipeline):
        """Test that error dict is returned when document is not found"""
        mock_pipeline = MagicMock()
        mock_get_pipeline.return_value = mock_pipeline
        mock_document_provider = MagicMock()
        type(mock_pipeline).document_index_provider = PropertyMock(return_value=mock_document_provider)
        mock_document_provider.get_document.return_value = None

        result = do_get_document(doc_id="nonexistent")

        assert 'error' in result
        assert "Document not found" in result['error']

    @patch('stache_ai.core.operations.get_pipeline')
    def test_returns_error_when_provider_is_none(self, mock_get_pipeline):
        """Test that error is returned when document_index_provider is None"""
        mock_pipeline = MagicMock()
        mock_get_pipeline.return_value = mock_pipeline
        type(mock_pipeline).document_index_provider = PropertyMock(return_value=None)

        result = do_get_document(doc_id="doc1")

        assert 'error' in result
        assert "Document index feature is disabled" in result['error']

    @patch('stache_ai.core.operations.get_pipeline')
    def test_request_id_in_response(self, mock_get_pipeline):
        """Test that request_id is included in response"""
        mock_pipeline = MagicMock()
        mock_get_pipeline.return_value = mock_pipeline
        mock_document_provider = MagicMock()
        type(mock_pipeline).document_index_provider = PropertyMock(return_value=mock_document_provider)
        mock_document_provider.get_document.return_value = {
            "id": "doc1",
            "name": "Document 1"
        }

        result = do_get_document(doc_id="doc1", request_id="doc-get-123")

        assert result['request_id'] == "doc-get-123"

    @patch('stache_ai.core.operations.get_pipeline')
    def test_generates_request_id_if_not_provided(self, mock_get_pipeline):
        """Test that request_id is generated if not provided"""
        mock_pipeline = MagicMock()
        mock_get_pipeline.return_value = mock_pipeline
        mock_document_provider = MagicMock()
        type(mock_pipeline).document_index_provider = PropertyMock(return_value=mock_document_provider)
        mock_document_provider.get_document.return_value = {
            "id": "doc1",
            "name": "Document 1"
        }

        result = do_get_document(doc_id="doc1")

        assert 'request_id' in result
        assert len(result['request_id']) > 0

    @patch('stache_ai.core.operations.get_pipeline')
    def test_returns_error_on_exception(self, mock_get_pipeline):
        """Test that exceptions are caught and returned as error dict"""
        mock_pipeline = MagicMock()
        mock_get_pipeline.return_value = mock_pipeline
        mock_document_provider = MagicMock()
        type(mock_pipeline).document_index_provider = PropertyMock(return_value=mock_document_provider)
        mock_document_provider.get_document.side_effect = Exception("Get failed")

        result = do_get_document(doc_id="doc1")

        assert 'error' in result
        assert result['error'] == "Get failed"

    @patch('stache_ai.core.operations.get_pipeline')
    def test_uses_default_namespace(self, mock_get_pipeline):
        """Test that default namespace is 'default' if not provided"""
        mock_pipeline = MagicMock()
        mock_get_pipeline.return_value = mock_pipeline
        mock_document_provider = MagicMock()
        type(mock_pipeline).document_index_provider = PropertyMock(return_value=mock_document_provider)
        mock_document_provider.get_document.return_value = {
            "id": "doc1",
            "name": "Document 1"
        }

        result = do_get_document(doc_id="doc1")

        call_kwargs = mock_document_provider.get_document.call_args[1]
        assert call_kwargs['namespace'] == "default"

    @patch('stache_ai.core.operations.get_pipeline')
    def test_returns_document_data_on_success(self, mock_get_pipeline):
        """Test that document data is returned in response on success"""
        mock_pipeline = MagicMock()
        mock_get_pipeline.return_value = mock_pipeline
        mock_document_provider = MagicMock()
        type(mock_pipeline).document_index_provider = PropertyMock(return_value=mock_document_provider)
        doc_data = {
            "id": "doc1",
            "name": "Document 1",
            "content": "Sample content",
            "size": 1024
        }
        mock_document_provider.get_document.return_value = doc_data

        result = do_get_document(doc_id="doc1")

        assert result['id'] == "doc1"
        assert result['name'] == "Document 1"
        assert result['content'] == "Sample content"
        assert result['size'] == 1024
        assert result['request_id'] is not None

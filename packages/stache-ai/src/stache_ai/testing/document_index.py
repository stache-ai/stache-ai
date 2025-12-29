"""Document index provider contract tests."""

import uuid
from abc import ABC, abstractmethod

import pytest


class DocumentIndexContractTest(ABC):
    """Base class for DocumentIndex provider contract tests."""

    @pytest.fixture
    @abstractmethod
    def provider(self):
        """Create the provider instance under test."""
        pass

    @pytest.fixture
    def test_doc_id(self) -> str:
        return f"doc-{uuid.uuid4().hex[:8]}"

    @pytest.fixture
    def test_namespace(self) -> str:
        return f"test-ns-{uuid.uuid4().hex[:8]}"

    def test_create_document_returns_dict(self, provider, test_doc_id, test_namespace):
        """create_document() must return document dict."""
        doc = provider.create_document(
            doc_id=test_doc_id,
            filename="test.pdf",
            namespace=test_namespace,
            chunk_ids=["chunk-1", "chunk-2"]
        )

        assert isinstance(doc, dict)
        assert "doc_id" in doc or "id" in doc

    def test_get_document_returns_dict(self, provider, test_doc_id, test_namespace):
        """get_document() must return document after creation."""
        provider.create_document(
            doc_id=test_doc_id,
            filename="test.pdf",
            namespace=test_namespace,
            chunk_ids=["chunk-1"]
        )

        doc = provider.get_document(test_doc_id, namespace=test_namespace)

        assert doc is not None
        assert isinstance(doc, dict)

    def test_list_documents_returns_paginated(self, provider, test_namespace):
        """list_documents() must return dict with documents and next_key."""
        result = provider.list_documents(namespace=test_namespace)

        assert isinstance(result, dict)
        assert "documents" in result
        assert isinstance(result["documents"], list)

    def test_delete_document_returns_bool(self, provider, test_doc_id, test_namespace):
        """delete_document() must return boolean."""
        provider.create_document(
            doc_id=test_doc_id,
            filename="test.pdf",
            namespace=test_namespace,
            chunk_ids=["chunk-1"]
        )

        result = provider.delete_document(test_doc_id, namespace=test_namespace)

        assert isinstance(result, bool)

    def test_document_exists_returns_bool(self, provider, test_namespace):
        """document_exists() must return boolean."""
        result = provider.document_exists(
            filename="nonexistent.pdf",
            namespace=test_namespace
        )

        assert isinstance(result, bool)

    def test_get_chunk_ids_returns_list(self, provider, test_doc_id, test_namespace):
        """get_chunk_ids() must return list of chunk IDs."""
        chunk_ids = ["chunk-1", "chunk-2", "chunk-3"]
        provider.create_document(
            doc_id=test_doc_id,
            filename="test.pdf",
            namespace=test_namespace,
            chunk_ids=chunk_ids
        )

        result = provider.get_chunk_ids(test_doc_id, namespace=test_namespace)

        assert isinstance(result, list)
        assert set(result) == set(chunk_ids)

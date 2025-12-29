"""VectorDB provider contract tests."""

import uuid
from abc import ABC, abstractmethod
from typing import Any

import pytest


class VectorDBContractTest(ABC):
    """Base class for VectorDB provider contract tests.

    All VectorDB provider implementations MUST pass these tests to ensure
    consistent behavior across the ecosystem.

    Subclasses must implement:
        - provider: pytest fixture returning a configured provider instance
        - test_namespace: pytest fixture returning a test namespace string
    """

    @pytest.fixture
    @abstractmethod
    def provider(self):
        """Create the provider instance under test.

        Must return a fully configured VectorDBProvider instance.
        """
        pass

    @pytest.fixture
    def test_namespace(self) -> str:
        """Return a unique test namespace."""
        return f"test-{uuid.uuid4().hex[:8]}"

    @pytest.fixture
    def sample_vectors(self) -> list[list[float]]:
        """Sample 1024-dimension vectors for testing."""
        return [
            [0.1] * 1024,
            [0.2] * 1024,
            [0.3] * 1024,
        ]

    @pytest.fixture
    def sample_texts(self) -> list[str]:
        """Sample texts corresponding to vectors."""
        return [
            "The quick brown fox jumps over the lazy dog.",
            "Machine learning models require training data.",
            "Vector databases enable semantic search.",
        ]

    @pytest.fixture
    def sample_metadatas(self) -> list[dict[str, Any]]:
        """Sample metadata for vectors."""
        return [
            {"source": "document1.pdf", "page": 1},
            {"source": "document2.pdf", "page": 5},
            {"source": "document3.pdf", "page": 10},
        ]

    # ===== Required Method Tests =====

    def test_insert_returns_ids(
        self, provider, sample_vectors, sample_texts, sample_metadatas, test_namespace
    ):
        """Insert must return list of string IDs matching input count."""
        ids = provider.insert(
            vectors=sample_vectors,
            texts=sample_texts,
            metadatas=sample_metadatas,
            namespace=test_namespace
        )

        assert isinstance(ids, list)
        assert len(ids) == len(sample_vectors)
        assert all(isinstance(id_, str) for id_ in ids)

    def test_insert_with_custom_ids(
        self, provider, sample_vectors, sample_texts, test_namespace
    ):
        """Insert with provided IDs must use those IDs."""
        custom_ids = [f"custom-{i}" for i in range(len(sample_vectors))]

        returned_ids = provider.insert(
            vectors=sample_vectors,
            texts=sample_texts,
            ids=custom_ids,
            namespace=test_namespace
        )

        assert returned_ids == custom_ids

    def test_search_returns_results(
        self, provider, sample_vectors, sample_texts, test_namespace
    ):
        """Search must return results with required fields."""
        # Insert first
        provider.insert(
            vectors=sample_vectors,
            texts=sample_texts,
            namespace=test_namespace
        )

        # Search with first vector
        results = provider.search(
            query_vector=sample_vectors[0],
            top_k=3,
            namespace=test_namespace
        )

        assert isinstance(results, list)
        assert len(results) >= 1

        # Check result structure
        for result in results:
            assert "score" in result
            assert "text" in result or "content" in result
            assert isinstance(result["score"], (int, float))

    def test_search_respects_top_k(
        self, provider, sample_vectors, sample_texts, test_namespace
    ):
        """Search must not return more than top_k results."""
        provider.insert(
            vectors=sample_vectors,
            texts=sample_texts,
            namespace=test_namespace
        )

        results = provider.search(
            query_vector=sample_vectors[0],
            top_k=1,
            namespace=test_namespace
        )

        assert len(results) <= 1

    def test_delete_by_ids(
        self, provider, sample_vectors, sample_texts, test_namespace
    ):
        """Delete must remove vectors by ID."""
        ids = provider.insert(
            vectors=sample_vectors,
            texts=sample_texts,
            namespace=test_namespace
        )

        result = provider.delete(ids=ids[:1], namespace=test_namespace)

        assert result is True

    def test_get_collection_info(self, provider):
        """get_collection_info must return a dictionary."""
        info = provider.get_collection_info()

        assert isinstance(info, dict)

    def test_namespace_isolation(
        self, provider, sample_vectors, sample_texts
    ):
        """Vectors in different namespaces must not be visible to each other."""
        ns1 = f"test-ns1-{uuid.uuid4().hex[:8]}"
        ns2 = f"test-ns2-{uuid.uuid4().hex[:8]}"

        # Insert to ns1
        provider.insert(
            vectors=sample_vectors[:1],
            texts=["Namespace 1 content"],
            namespace=ns1
        )

        # Insert different content to ns2
        provider.insert(
            vectors=sample_vectors[1:2],
            texts=["Namespace 2 content"],
            namespace=ns2
        )

        # Search ns1 should not find ns2 content
        results = provider.search(
            query_vector=sample_vectors[1],  # Vector from ns2
            top_k=10,
            namespace=ns1
        )

        for result in results:
            text = result.get("text") or result.get("content", "")
            assert "Namespace 2" not in text

    # ===== Optional Method Tests =====
    # These test optional methods that may raise NotImplementedError

    def test_delete_by_metadata_if_supported(
        self, provider, sample_vectors, sample_texts, sample_metadatas, test_namespace
    ):
        """delete_by_metadata should work if implemented."""
        provider.insert(
            vectors=sample_vectors,
            texts=sample_texts,
            metadatas=sample_metadatas,
            namespace=test_namespace
        )

        try:
            result = provider.delete_by_metadata(
                field="source",
                value="document1.pdf",
                namespace=test_namespace
            )
            assert isinstance(result, dict)
            assert "deleted" in result
        except NotImplementedError:
            pytest.skip("delete_by_metadata not implemented")

    def test_get_by_ids_if_supported(
        self, provider, sample_vectors, sample_texts, test_namespace
    ):
        """get_by_ids should return vector data if implemented."""
        ids = provider.insert(
            vectors=sample_vectors,
            texts=sample_texts,
            namespace=test_namespace
        )

        try:
            results = provider.get_by_ids(ids=ids[:1], namespace=test_namespace)
            assert isinstance(results, list)
            if results:
                assert "id" in results[0] or "text" in results[0]
        except NotImplementedError:
            pytest.skip("get_by_ids not implemented")

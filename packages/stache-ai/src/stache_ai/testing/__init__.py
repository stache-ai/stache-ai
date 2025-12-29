"""Contract test base classes for Stache providers.

These abstract test classes define the behavioral contract that all provider
implementations must satisfy. Plugin packages should subclass these and
implement the provider fixture.

Usage in plugin package:
    # packages/stache-qdrant/tests/test_contract.py
    from stache_ai.testing import VectorDBContractTest

    class TestQdrantContract(VectorDBContractTest):
        @pytest.fixture
        def provider(self):
            return QdrantVectorDBProvider(test_settings)
"""

from .document_index import DocumentIndexContractTest
from .embedding import EmbeddingContractTest
from .llm import LLMContractTest
from .namespace import NamespaceContractTest
from .reranker import RerankerContractTest
from .vectordb import VectorDBContractTest

__all__ = [
    'VectorDBContractTest',
    'LLMContractTest',
    'EmbeddingContractTest',
    'NamespaceContractTest',
    'DocumentIndexContractTest',
    'RerankerContractTest',
]

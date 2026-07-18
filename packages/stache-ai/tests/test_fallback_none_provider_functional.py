"""Functional regression test for the F1/F2 pre-freeze fix.

Unlike the drift-guard unit tests in tests/providers/test_provider_context_forwarding_drift.py
(which introspect signatures and identity-propagate a sentinel in isolation),
this drives the REAL FallbackEmbeddingProvider and NoneLLMProvider through the
actual RAGPipeline call sites (ingest_text's embed_batch call, query's
generate_with_context call) to prove the previously-broken supported configs
(EMBEDDING_PROVIDER=fallback, LLM_PROVIDER=none) no longer raise TypeError.
"""

from unittest.mock import MagicMock

import pytest

from stache_ai.middleware.postingest.summary import HeuristicSummaryGenerator
from stache_ai.providers.embeddings.fallback import FallbackEmbeddingProvider
from stache_ai.providers.llm.none import NoneLLMProvider
from stache_ai.rag.pipeline import RAGPipeline

pytestmark = pytest.mark.anyio


class _StubUnderlyingEmbedder:
    """Stands in for whatever real embedding provider FallbackEmbeddingProvider
    would lazily construct as its primary (bedrock, ollama, etc.) — only its
    embed/embed_batch signatures matter here."""

    def embed(self, text, *, context=None):
        return [0.1] * 1536

    def embed_batch(self, texts, *, context=None):
        return [[0.1] * 1536 for _ in texts]

    def get_dimensions(self):
        return 1536

    def get_name(self):
        return "stub-underlying"


def _make_fallback_embedding_provider():
    """Build a real FallbackEmbeddingProvider wired to a stub primary,
    bypassing __init__ (which needs live Settings/factory wiring irrelevant
    to this check)."""
    provider = FallbackEmbeddingProvider.__new__(FallbackEmbeddingProvider)
    stub = _StubUnderlyingEmbedder()
    provider._primary = stub
    provider._secondary = stub
    provider._primary_name = "stub"
    provider._secondary_name = "stub"
    return provider


@pytest.fixture
def fallback_none_pipeline(
    mock_vectordb_provider,
    mock_document_index_provider,
    mock_documents_provider,
    mock_summaries_provider,
    mock_insights_provider,
):
    """RAGPipeline wired to the two providers the review flagged as broken:
    EMBEDDING_PROVIDER=fallback and LLM_PROVIDER=none — both real, unmocked
    instances (not MagicMocks, which would hide a dropped kwarg)."""
    pipeline = RAGPipeline()
    pipeline._embedding_provider = _make_fallback_embedding_provider()
    pipeline._llm_provider = NoneLLMProvider(settings=None)
    pipeline._vectordb_provider = mock_vectordb_provider
    pipeline._document_index_provider = mock_document_index_provider
    pipeline._documents_provider = mock_documents_provider
    pipeline._summaries_provider = mock_summaries_provider
    pipeline._insights_provider = mock_insights_provider
    pipeline._enrichers = []
    pipeline._chunk_observers = []
    pipeline._postingest_processors = [HeuristicSummaryGenerator()]
    pipeline._query_processors = []
    pipeline._result_processors = []
    pipeline._delete_observers = []
    return pipeline


async def test_ingest_text_with_fallback_embedding_provider_does_not_raise_typeerror(
    fallback_none_pipeline,
):
    """Regression test for F1: before the fix, embedding_provider.embed_batch(
    chunks, context=context) raised TypeError because FallbackEmbeddingProvider
    .embed_batch() didn't accept 'context'."""
    result = await fallback_none_pipeline.ingest_text(
        text="This is test content for the fallback embedding provider config.",
        metadata={"filename": "test.txt"},
    )
    assert result["success"] is True
    assert result["chunks_created"] > 0


async def test_query_with_none_llm_provider_raises_not_implemented_not_typeerror(
    fallback_none_pipeline,
):
    """Regression test for F2: before the fix, llm_provider.generate_with_context(
    ..., request_context=context) raised an opaque TypeError instead of the
    intended NotImplementedError."""
    with pytest.raises(NotImplementedError, match="LLM synthesis is not available"):
        await fallback_none_pipeline.query(
            question="What is in the document?",
            synthesize=True,
        )


async def test_query_with_none_llm_provider_and_model_raises_not_implemented(
    fallback_none_pipeline,
):
    """Same regression, via the generate_with_context_and_model call site,
    which the pipeline invokes with model_id= (keyword)."""
    with pytest.raises(NotImplementedError, match="LLM synthesis is not available"):
        await fallback_none_pipeline.query(
            question="What is in the document?",
            synthesize=True,
            model="some-model",
        )

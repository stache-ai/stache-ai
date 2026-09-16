"""Progress-reporting tests for the RAG pipeline (Job.progress backend).

Covers the additive ``progress_callback`` on ``ingest_text`` / ``ingest_file``:
a monotonic 0-100 sequence is emitted across stage boundaries, None is a
zero-overhead no-op, and a raising callback never fails the ingest.
"""

import pytest

from stache_ai.rag.pipeline import RAGPipeline
from stache_ai.rag.embedding_resilience import AutoSplitEmbeddingWrapper

pytestmark = pytest.mark.anyio


@pytest.fixture
def progress_pipeline(
    mock_embedding_provider,
    mock_llm_provider,
    mock_vectordb_provider,
    mock_document_index_provider,
    mock_documents_provider,
    mock_summaries_provider,
    mock_insights_provider,
):
    """Pipeline with mocked providers and no middleware (mirrors test_pipeline)."""
    pipeline = RAGPipeline()
    pipeline._embedding_provider = mock_embedding_provider
    pipeline._llm_provider = mock_llm_provider
    pipeline._vectordb_provider = mock_vectordb_provider
    pipeline._document_index_provider = mock_document_index_provider
    pipeline._documents_provider = mock_documents_provider
    pipeline._summaries_provider = mock_summaries_provider
    pipeline._insights_provider = mock_insights_provider
    pipeline._enrichers = []
    pipeline._chunk_observers = []
    pipeline._postingest_processors = []
    pipeline._query_processors = []
    pipeline._result_processors = []
    pipeline._delete_observers = []
    pipeline._ingest_guards = []
    pipeline._error_processors = []
    return pipeline


async def test_ingest_text_emits_monotonic_progress(progress_pipeline):
    seen: list[int] = []
    result = await progress_pipeline.ingest_text(
        text="This is a short document to embed and index.",
        namespace="default",
        progress_callback=seen.append,
    )

    assert result["success"] is True
    # Non-decreasing throughout.
    assert seen == sorted(seen)
    # Starts low (extraction/chunking band), crosses the embedding band, ends <= 100.
    assert seen[0] <= 20
    assert any(20 <= p <= 80 for p in seen)
    assert seen[-1] <= 100
    # The pipeline reaches the indexing stage (it leaves 100 for the worker).
    assert seen[-1] >= 90


async def test_ingest_file_emits_monotonic_progress(progress_pipeline, tmp_path):
    f = tmp_path / "note.txt"
    f.write_text("Some file text that will be chunked, embedded, and stored.")

    seen: list[int] = []
    result = await progress_pipeline.ingest_file(
        file_path=str(f),
        namespace="default",
        progress_callback=seen.append,
    )

    assert result["success"] is True
    assert seen == sorted(seen)
    assert seen[0] <= 20
    assert any(20 <= p <= 80 for p in seen)
    assert 90 <= seen[-1] <= 100


async def test_no_callback_is_zero_overhead_and_does_not_error(progress_pipeline):
    # Default path (progress_callback=None): must run cleanly with no emission.
    result = await progress_pipeline.ingest_text(text="plain ingest, no progress hook")
    assert result["success"] is True


async def test_progress_callback_exception_is_swallowed(progress_pipeline):
    calls: list[int] = []

    def boom(pct: int) -> None:
        calls.append(pct)
        raise RuntimeError("callback blew up")

    # A raising callback must NOT fail the ingest.
    result = await progress_pipeline.ingest_text(
        text="ingest survives a broken progress hook",
        progress_callback=boom,
    )
    assert result["success"] is True
    assert calls  # it really was invoked (and every call raised)


def test_embed_batch_callback_reports_each_batch_monotonically():
    """The embedding band fires once per completed batch with a climbing
    done-count, so the pipeline can interpolate 20->80 across batches."""

    class _Provider:
        def embed_batch(self, texts, *, context=None):
            return [[0.1, 0.2, 0.3] for _ in texts]

        def get_name(self):
            return "fake"

    wrapper = AutoSplitEmbeddingWrapper(
        provider=_Provider(), enabled=True, batch_size=2, max_workers=1,
    )
    seen: list[tuple[int, int]] = []
    texts = [f"chunk {i}" for i in range(5)]  # 3 batches at batch_size=2
    results, splits = wrapper.embed_batch_with_splits(
        texts, progress_callback=lambda done, total: seen.append((done, total)),
    )

    assert len(results) == 5
    assert splits == 0
    # One report per batch, done-count strictly increasing, total constant at 3.
    assert [d for d, _ in seen] == [1, 2, 3]
    assert all(total == 3 for _, total in seen)

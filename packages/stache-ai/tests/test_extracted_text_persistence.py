"""Tests for persisting the full extracted/plain text at ingest.

The GET chunks endpoint used to rebuild a document's text by joining its chunks,
which duplicates every ``chunk_overlap`` region. Instead the pipeline now stores
the exact text that was chunked in the blob store and records its key as
``text_blob_key`` on the document record; the readers serve that clean text.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from stache_ai.identity import Principal
from stache_ai.ingestion.base import Job, JobStatus
from stache_ai.ingestion.providers.inline import FilesystemBlobStore
from stache_ai.middleware.context import RequestContext
from stache_ai.rag.pipeline import RAGPipeline, _persist_extracted_text

pytestmark = pytest.mark.anyio


def _ctx(blobstore, job):
    return RequestContext(
        request_id="r1",
        timestamp=datetime.now(timezone.utc),
        namespace="default",
        source="worker",
        custom={"ingest_job": job, "blobstore": blobstore,
                "principal": Principal(user_id="alice")},
    )


def _job(*, blob_key=None):
    return Job(
        job_id="job-123", status=JobStatus.PROCESSING, namespace="default",
        source="api", filename="note.txt", content_type="text",
        requested_by="alice", blob_key=blob_key,
    )


# ---------------------------------------------------------------------------
# _persist_extracted_text unit behavior
# ---------------------------------------------------------------------------

def test_text_ingest_writes_job_scoped_text_blob(tmp_path):
    """A pasted-text ingest has no binary original (blob_key None); the text is
    written to a job-scoped ``extracted.txt`` blob via the store's make_key."""
    bs = FilesystemBlobStore(str(tmp_path))
    key = _persist_extracted_text(_ctx(bs, _job(blob_key=None)), "hello clean world")
    assert key == "job-123/extracted.txt"
    data, _ = bs.get(key)
    assert data.decode("utf-8") == "hello clean world"


def test_file_ingest_writes_sibling_text_blob(tmp_path):
    """An extracted file keeps its binary original at blob_key and the text in a
    sibling ``{blob_key}.text`` blob (same job_id under parse_job_id)."""
    bs = FilesystemBlobStore(str(tmp_path))
    job = _job(blob_key="job-123/report.pdf")
    key = _persist_extracted_text(_ctx(bs, job), "extracted pdf text")
    assert key == "job-123/report.pdf.text"
    # The suffix keeps the same job_id, so an async re-trigger would no-op.
    assert bs.parse_job_id(key) == "job-123"
    data, _ = bs.get(key)
    assert data.decode("utf-8") == "extracted pdf text"


def test_producer_drop_text_key_round_trips_to_job(tmp_path):
    """A producer-drop job's blob_key is the producer's arbitrary key and its
    job_id a fresh uuid, so the ``{blob_key}.text`` sibling parses to the WRONG
    job -> an S3 re-trigger would mint a new producer job in an unbounded loop.
    The fix mints a job-scoped key that inverts back to THIS job instead (whose
    terminal status makes the re-trigger a no-op)."""
    bs = FilesystemBlobStore(str(tmp_path))
    job = _job(blob_key="dropzone/incoming.bin")     # producer-drop shape
    # Precondition: the sibling key would NOT resolve to this job.
    assert bs.parse_job_id("dropzone/incoming.bin.text") != job.job_id
    key = _persist_extracted_text(_ctx(bs, job), "extracted text")
    # Not the sibling; a job-scoped key that DOES round-trip to the job.
    assert key == "job-123/extracted.txt"
    assert bs.parse_job_id(key) == job.job_id
    data, _ = bs.get(key)
    assert data.decode("utf-8") == "extracted text"


def test_null_tier_records_no_text_blob_key():
    """The null blob tier (default OSS) retains nothing, so no text_blob_key is
    recorded -- reconstructed_text falls back to the chunk join and the download
    404s, instead of persisting a key whose later get() would always raise."""
    from stache_ai.ingestion.providers.inline import NullBlobStore
    bs = NullBlobStore()
    assert "blob_read" not in bs.capabilities
    assert _persist_extracted_text(_ctx(bs, _job(blob_key=None)), "text") is None


def test_returns_none_without_blobstore_in_context():
    ctx = RequestContext(request_id="r", timestamp=datetime.now(timezone.utc),
                         namespace="default", source="worker",
                         custom={"ingest_job": _job()})
    assert _persist_extracted_text(ctx, "text") is None


def test_returns_none_without_job_in_context(tmp_path):
    bs = FilesystemBlobStore(str(tmp_path))
    ctx = RequestContext(request_id="r", timestamp=datetime.now(timezone.utc),
                         namespace="default", source="api",
                         custom={"blobstore": bs})
    assert _persist_extracted_text(ctx, "text") is None


def test_returns_none_for_empty_text(tmp_path):
    bs = FilesystemBlobStore(str(tmp_path))
    assert _persist_extracted_text(_ctx(bs, _job()), "") is None


def test_put_failure_returns_none_not_raises():
    bs = MagicMock()
    bs.capabilities = {"blob_read"}
    bs.make_key.return_value = "k"
    bs.put.side_effect = RuntimeError("s3 down")
    assert _persist_extracted_text(_ctx(bs, _job()), "text") is None


# ---------------------------------------------------------------------------
# Threading: ingest_text passes text_blob_key to create_document
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_pipeline(mock_embedding_provider, mock_llm_provider, mock_vectordb_provider,
                  mock_document_index_provider, mock_documents_provider,
                  mock_summaries_provider, mock_insights_provider):
    from stache_ai.middleware.postingest.summary import HeuristicSummaryGenerator

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
    pipeline._postingest_processors = [HeuristicSummaryGenerator()]
    pipeline._query_processors = []
    pipeline._result_processors = []
    pipeline._delete_observers = []
    return pipeline


async def test_ingest_text_threads_text_blob_key_to_create_document(mock_pipeline, tmp_path):
    bs = FilesystemBlobStore(str(tmp_path))
    context = _ctx(bs, _job(blob_key=None))

    await mock_pipeline.ingest_text(
        text="This is the exact text that was chunked.",
        metadata={"filename": "note.txt"},
        context=context,
    )

    call = mock_pipeline._document_index_provider.create_document.call_args
    text_key = call.kwargs["text_blob_key"]
    assert text_key == "job-123/extracted.txt"
    # The stored blob holds the exact text (not a lossy chunk join).
    data, _ = bs.get(text_key)
    assert data.decode("utf-8") == "This is the exact text that was chunked."


async def test_ingest_text_without_retention_omits_retention_kwargs(mock_pipeline):
    """Direct pipeline ingestion (no worker -> no blob retention) leaves
    blob_key/content_type/text_blob_key all None. Rather than pass them as None,
    create_document is called WITHOUT those keyword names at all, so a 0.3.0
    third-party provider that predates the retention feature (and has no
    ``**kwargs`` to absorb them) is called with the exact pre-0.3.1 kwarg set
    instead of raising TypeError -> silent index loss."""
    await mock_pipeline.ingest_text(text="direct ingest", metadata={"filename": "d.txt"})
    call = mock_pipeline._document_index_provider.create_document.call_args
    assert "text_blob_key" not in call.kwargs
    assert "blob_key" not in call.kwargs
    assert "content_type" not in call.kwargs

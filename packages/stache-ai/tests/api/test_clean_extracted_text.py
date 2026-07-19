"""Tests for serving clean extracted text: the GET chunks ``reconstructed_text``
and the ``?format=text`` variant of the original-download endpoint."""

import types
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import stache_ai.api.main as main_mod
from stache_ai.identity import Principal, PrincipalExtractor

USER_ID = "principal-9"


class _FixedExtractor(PrincipalExtractor):
    def extract(self, request):
        return Principal(user_id=USER_ID, claims={})


@pytest.fixture
def client():
    with patch.object(main_mod, "_principal_extractor", _FixedExtractor()):
        yield TestClient(main_mod.app)


class _GetBlobStore:
    """Blob store double whose get() returns fixed bytes (or raises)."""

    def __init__(self, text=None, error=None):
        self._text = text
        self._error = error
        self.get_calls = []

    def get(self, key):
        self.get_calls.append(key)
        if self._error is not None:
            raise self._error
        return self._text.encode("utf-8"), {}


class _PresignBlobStore:
    def __init__(self, url="https://signed.example/text"):
        self._url = url
        self.presign_calls = []

    @property
    def capabilities(self):
        return {"presign_download"}

    def presign_get(self, key, *, expiry, download_filename=None):
        self.presign_calls.append((key, expiry, download_filename))
        return self._url


def _service_with(blobstore):
    return types.SimpleNamespace(blobstore=blobstore)


def _chunk_pipeline(chunks, doc_record):
    pipeline = MagicMock()
    pipeline.document_index_provider = MagicMock()
    pipeline.get_document_chunks = MagicMock(return_value=chunks)
    pipeline.get_document_record = MagicMock(return_value=doc_record)
    return pipeline


# ---------------------------------------------------------------------------
# reconstructed_text
# ---------------------------------------------------------------------------

def test_reconstructed_text_serves_stored_clean_text(client):
    # Chunks overlap ("...brown fox" repeated); the join would duplicate it.
    chunks = [
        {"id": "c0", "text": "the quick brown fox", "doc_id": "d1",
         "namespace": "ns1", "chunk_index": 0},
        {"id": "c1", "text": "brown fox jumps over", "doc_id": "d1",
         "namespace": "ns1", "chunk_index": 1},
    ]
    doc = {"doc_id": "d1", "namespace": "ns1", "text_blob_key": "d1/x.text"}
    pipeline = _chunk_pipeline(chunks, doc)
    blob = _GetBlobStore(text="the quick brown fox jumps over")
    with patch("stache_ai.api.routes.documents.get_pipeline", return_value=pipeline), \
         patch("stache_ai.ingestion.factory.get_ingestion_service",
               return_value=_service_with(blob)):
        resp = client.get("/api/documents/chunks?point_ids=c0,c1")

    assert resp.status_code == 200
    # Clean stored text, not the overlap-duplicating join.
    assert resp.json()["reconstructed_text"] == "the quick brown fox jumps over"
    assert blob.get_calls == ["d1/x.text"]
    pipeline.get_document_record.assert_called_once()
    assert pipeline.get_document_record.call_args.args[:2] == ("d1", "ns1")


def test_reconstructed_text_falls_back_to_join_without_text_blob_key(client):
    chunks = [
        {"id": "c0", "text": "alpha", "doc_id": "d1", "namespace": "ns1", "chunk_index": 0},
        {"id": "c1", "text": "beta", "doc_id": "d1", "namespace": "ns1", "chunk_index": 1},
    ]
    doc = {"doc_id": "d1", "namespace": "ns1"}  # no text_blob_key
    pipeline = _chunk_pipeline(chunks, doc)
    with patch("stache_ai.api.routes.documents.get_pipeline", return_value=pipeline):
        resp = client.get("/api/documents/chunks?point_ids=c0,c1")

    assert resp.status_code == 200
    assert resp.json()["reconstructed_text"] == "alpha\n\nbeta"


def test_reconstructed_text_falls_back_on_blob_fetch_error(client):
    chunks = [
        {"id": "c0", "text": "alpha", "doc_id": "d1", "namespace": "ns1", "chunk_index": 0},
    ]
    doc = {"doc_id": "d1", "namespace": "ns1", "text_blob_key": "d1/x.text"}
    pipeline = _chunk_pipeline(chunks, doc)
    blob = _GetBlobStore(error=KeyError("gone"))
    with patch("stache_ai.api.routes.documents.get_pipeline", return_value=pipeline), \
         patch("stache_ai.ingestion.factory.get_ingestion_service",
               return_value=_service_with(blob)):
        resp = client.get("/api/documents/chunks?point_ids=c0")

    assert resp.status_code == 200          # fetch failure -> fallback, not 500
    assert resp.json()["reconstructed_text"] == "alpha"


def test_reconstructed_text_falls_back_without_doc_id(client):
    chunks = [{"id": "c0", "text": "orphan", "chunk_index": 0}]  # no doc_id
    pipeline = _chunk_pipeline(chunks, None)
    with patch("stache_ai.api.routes.documents.get_pipeline", return_value=pipeline):
        resp = client.get("/api/documents/chunks?point_ids=c0")

    assert resp.status_code == 200
    assert resp.json()["reconstructed_text"] == "orphan"
    pipeline.get_document_record.assert_not_called()


# ---------------------------------------------------------------------------
# ?format=text on the original-download endpoint
# ---------------------------------------------------------------------------

def _doc_pipeline(doc_record):
    pipeline = MagicMock()
    pipeline.document_index_provider = MagicMock()
    pipeline.get_document_record = MagicMock(return_value=doc_record)
    return pipeline


def test_format_text_presigns_the_text_blob(client):
    pipeline = _doc_pipeline({
        "doc_id": "d1", "filename": "report.pdf", "namespace": "ns1",
        "blob_key": "d1/report.pdf", "text_blob_key": "d1/report.pdf.text",
    })
    blob = _PresignBlobStore(url="https://signed.example/text")
    with patch("stache_ai.api.routes.documents.get_pipeline", return_value=pipeline), \
         patch("stache_ai.ingestion.factory.get_ingestion_service",
               return_value=_service_with(blob)):
        resp = client.get("/api/documents/d1/original?namespace=ns1&format=text")

    assert resp.status_code == 200
    assert resp.json() == {"url": "https://signed.example/text"}
    # Presigns the TEXT key (not the binary original) with a .txt save-as name.
    assert blob.presign_calls[0][0] == "d1/report.pdf.text"
    assert blob.presign_calls[0][2] == "report.pdf.txt"


def test_format_text_404_when_no_text_blob(client):
    pipeline = _doc_pipeline({
        "doc_id": "d1", "filename": "report.pdf", "namespace": "ns1",
        "blob_key": "d1/report.pdf",  # original present, but no text_blob_key
    })
    blob = _PresignBlobStore()
    with patch("stache_ai.api.routes.documents.get_pipeline", return_value=pipeline), \
         patch("stache_ai.ingestion.factory.get_ingestion_service",
               return_value=_service_with(blob)):
        resp = client.get("/api/documents/d1/original?namespace=ns1&format=text")

    assert resp.status_code == 404
    assert blob.presign_calls == []


def test_format_original_still_presigns_blob_key(client):
    """Default format is unchanged: presigns the binary original."""
    pipeline = _doc_pipeline({
        "doc_id": "d1", "filename": "report.pdf", "namespace": "ns1",
        "blob_key": "d1/report.pdf", "text_blob_key": "d1/report.pdf.text",
    })
    blob = _PresignBlobStore(url="https://signed.example/original")
    with patch("stache_ai.api.routes.documents.get_pipeline", return_value=pipeline), \
         patch("stache_ai.ingestion.factory.get_ingestion_service",
               return_value=_service_with(blob)):
        resp = client.get("/api/documents/d1/original?namespace=ns1")

    assert resp.status_code == 200
    assert blob.presign_calls[0][0] == "d1/report.pdf"
    assert blob.presign_calls[0][2] == "report.pdf"

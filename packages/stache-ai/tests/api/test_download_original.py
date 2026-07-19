"""Tests for the original-file download endpoint, the presign_get seam, and
the has_original flag on list/query responses."""

import types
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import stache_ai.api.main as main_mod
from stache_ai.identity import ForbiddenError, Principal, PrincipalExtractor
from stache_ai.ingestion.base import BlobStore

USER_ID = "principal-7"


class _FixedExtractor(PrincipalExtractor):
    def extract(self, request):
        return Principal(user_id=USER_ID, claims={})


@pytest.fixture
def client():
    with patch.object(main_mod, "_principal_extractor", _FixedExtractor()):
        yield TestClient(main_mod.app)


class _FakeBlobStore:
    """Blob store double with a togglable presign capability + URL."""

    def __init__(self, *, capable=True, url="https://signed.example/get"):
        self._capable = capable
        self._url = url
        self.presign_calls = []

    @property
    def capabilities(self):
        return {"presign_download"} if self._capable else set()

    def presign_get(self, key, *, expiry, download_filename=None):
        self.presign_calls.append((key, expiry, download_filename))
        return self._url


def _service_with(blobstore):
    return types.SimpleNamespace(blobstore=blobstore)


def _doc_pipeline(doc_record):
    pipeline = MagicMock()
    pipeline.document_index_provider = MagicMock()
    pipeline.get_document_record = MagicMock(return_value=doc_record)
    return pipeline


# ---------------------------------------------------------------------------
# Download route
# ---------------------------------------------------------------------------

def test_download_authorized_returns_url():
    pipeline = _doc_pipeline({
        "doc_id": "doc-1", "filename": "report.pdf", "namespace": "ns1",
        "blob_key": "doc-1/report.pdf",
    })
    blob = _FakeBlobStore(url="https://signed.example/report")
    with patch("stache_ai.api.routes.documents.get_pipeline", return_value=pipeline), \
         patch("stache_ai.ingestion.factory.get_ingestion_service",
               return_value=_service_with(blob)):
        with patch.object(main_mod, "_principal_extractor", _FixedExtractor()):
            resp = TestClient(main_mod.app).get(
                "/api/documents/doc-1/original?namespace=ns1")

    assert resp.status_code == 200
    assert resp.json() == {"url": "https://signed.example/report"}
    # Presigns the stored blob_key and passes the filename as the save-as name.
    assert blob.presign_calls[0][0] == "doc-1/report.pdf"
    assert blob.presign_calls[0][2] == "report.pdf"


def test_download_unauthorized_returns_403(client):
    pipeline = _doc_pipeline({"doc_id": "doc-1", "blob_key": "k"})
    with patch("stache_ai.api.routes.documents.get_pipeline", return_value=pipeline), \
         patch("stache_ai.api.routes.documents.auth.authorize",
               side_effect=ForbiddenError("nope")):
        resp = client.get("/api/documents/doc-1/original?namespace=ns1")
    assert resp.status_code == 403


def test_download_missing_blob_key_returns_404(client):
    pipeline = _doc_pipeline({"doc_id": "doc-1", "filename": "f.txt", "namespace": "ns1"})
    blob = _FakeBlobStore()
    with patch("stache_ai.api.routes.documents.get_pipeline", return_value=pipeline), \
         patch("stache_ai.ingestion.factory.get_ingestion_service",
               return_value=_service_with(blob)):
        resp = client.get("/api/documents/doc-1/original?namespace=ns1")
    assert resp.status_code == 404
    # No presign attempted when there is no original to sign.
    assert blob.presign_calls == []


def test_download_document_not_found_returns_404(client):
    pipeline = _doc_pipeline(None)
    with patch("stache_ai.api.routes.documents.get_pipeline", return_value=pipeline):
        resp = client.get("/api/documents/missing/original?namespace=ns1")
    assert resp.status_code == 404


def test_download_presign_none_returns_404(client):
    """Inline / non-presigning store: presign_get returns None -> 404."""
    pipeline = _doc_pipeline({
        "doc_id": "doc-1", "filename": "f.txt", "namespace": "ns1",
        "blob_key": "doc-1/f.txt",
    })
    blob = _FakeBlobStore(url=None)
    with patch("stache_ai.api.routes.documents.get_pipeline", return_value=pipeline), \
         patch("stache_ai.ingestion.factory.get_ingestion_service",
               return_value=_service_with(blob)):
        resp = client.get("/api/documents/doc-1/original?namespace=ns1")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# presign_get default on the base seam
# ---------------------------------------------------------------------------

def test_base_blobstore_presign_get_defaults_to_none():
    class _Store(BlobStore):
        def put(self, key, data, metadata):
            return key

        def get(self, key):
            return b"", {}

    store = _Store()
    assert store.presign_get("k", expiry=60) is None
    assert store.presign_get("k", expiry=60, download_filename="a.txt") is None
    assert "presign_download" not in store.capabilities


# ---------------------------------------------------------------------------
# has_original on the documents-list response
# ---------------------------------------------------------------------------

def _list_pipeline(documents):
    pipeline = MagicMock()
    pipeline.document_index_provider = MagicMock()
    pipeline.list_documents = MagicMock(
        return_value={"documents": documents, "next_key": None})
    return pipeline


def test_list_has_original_true_when_blob_key_and_capability(client):
    docs = [
        {"doc_id": "d1", "filename": "a.pdf", "blob_key": "d1/a.pdf"},
        {"doc_id": "d2", "filename": "b.txt"},  # no blob_key -> False
    ]
    pipeline = _list_pipeline(docs)
    blob = _FakeBlobStore(capable=True)
    with patch("stache_ai.api.routes.documents.get_pipeline", return_value=pipeline), \
         patch("stache_ai.ingestion.factory.get_ingestion_service",
               return_value=_service_with(blob)):
        resp = client.get("/api/documents")
    assert resp.status_code == 200
    by_id = {d["doc_id"]: d for d in resp.json()["documents"]}
    assert by_id["d1"]["has_original"] is True
    assert by_id["d2"]["has_original"] is False


def test_list_has_original_false_without_capability(client):
    docs = [{"doc_id": "d1", "filename": "a.pdf", "blob_key": "d1/a.pdf"}]
    pipeline = _list_pipeline(docs)
    blob = _FakeBlobStore(capable=False)
    with patch("stache_ai.api.routes.documents.get_pipeline", return_value=pipeline), \
         patch("stache_ai.ingestion.factory.get_ingestion_service",
               return_value=_service_with(blob)):
        resp = client.get("/api/documents")
    assert resp.status_code == 200
    assert resp.json()["documents"][0]["has_original"] is False


# ---------------------------------------------------------------------------
# has_original on query-result sources (via the annotation helper)
# ---------------------------------------------------------------------------

def test_query_annotate_has_original():
    from stache_ai.api.routes.query import _annotate_has_original

    pipeline = MagicMock()

    def _get_record(doc_id, ns, context=None):
        return {"blob_key": "k"} if doc_id == "d1" else {"filename": "x"}

    pipeline.get_document_record = MagicMock(side_effect=_get_record)
    sources = [
        {"metadata": {"doc_id": "d1", "namespace": "ns1"}},
        {"metadata": {"doc_id": "d2", "namespace": "ns1"}},
        {"metadata": {}},  # no doc_id
    ]
    blob = _FakeBlobStore(capable=True)
    with patch("stache_ai.ingestion.factory.get_ingestion_service",
               return_value=_service_with(blob)):
        _annotate_has_original(sources, pipeline, context=None)

    assert sources[0]["has_original"] is True
    assert sources[1]["has_original"] is False
    assert sources[2]["has_original"] is False


def test_query_annotate_skips_lookups_without_capability():
    from stache_ai.api.routes.query import _annotate_has_original

    pipeline = MagicMock()
    sources = [{"metadata": {"doc_id": "d1", "namespace": "ns1"}}]
    blob = _FakeBlobStore(capable=False)
    with patch("stache_ai.ingestion.factory.get_ingestion_service",
               return_value=_service_with(blob)):
        _annotate_has_original(sources, pipeline, context=None)

    assert sources[0]["has_original"] is False
    pipeline.get_document_record.assert_not_called()

"""FIX 1 regression tests: a ForbiddenError raised INSIDE a route body (by a
plugged authorizer doing a finer-grained check, or by a provider) must
surface as a 403, not get rewritten into a 500 by a route's blanket
``except Exception`` handler.

``test_authorization.py`` covers denials at the route's up-front
``auth.authorize()`` call, which every route already places outside its
broad try/except. These tests cover the other case: the authorizer/provider
call happens deeper in the request (e.g. the ingestion worker's
defense-in-depth check, or a per-document policy check that a deployment
plugs into a provider) and previously got swallowed by the route's blanket
catch-all before it could reach the app-level ForbiddenError -> 403 handler.

Each test installs an always-allow route-level authorizer (so the up-front
``auth.authorize()`` passes) and makes the mocked pipeline/service call that
the route body performs raise ForbiddenError directly, then asserts 403.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import stache_ai.api.main as main_mod
from stache_ai import identity
from stache_ai.identity import ForbiddenError


@pytest.fixture(autouse=True)
def _default_authorizer():
    """Every test here exercises a denial from inside the route body, not
    from the route-level auth.authorize() call - keep that call permissive."""
    identity.reset_authorizer()
    yield
    identity.reset_authorizer()


@pytest.fixture
def client():
    return TestClient(main_mod.app)


def test_capture_forwards_forbidden_from_ingestion_service(client):
    """capture.py wraps service.submit() in a blanket try/except."""
    service = MagicMock()
    service.submit = AsyncMock(side_effect=ForbiddenError("capture denied"))
    with patch("stache_ai.api.routes.capture.get_ingestion_service", return_value=service):
        resp = client.post("/api/capture", json={"text": "hello"})
    assert resp.status_code == 403, resp.text
    assert resp.json() == {"detail": "capture denied"}


def test_list_documents_forwards_forbidden_from_pipeline(client):
    """documents.py list_documents wraps pipeline.list_documents() in a blanket except."""
    pipeline = MagicMock()
    pipeline.document_index_provider = MagicMock()
    pipeline.list_documents = MagicMock(side_effect=ForbiddenError("list denied"))
    with patch("stache_ai.api.routes.documents.get_pipeline", return_value=pipeline):
        resp = client.get("/api/documents")
    assert resp.status_code == 403, resp.text
    assert resp.json() == {"detail": "list denied"}


def test_delete_document_by_id_forwards_forbidden_from_pipeline(client):
    """documents.py delete_document_by_id wraps pipeline.soft_delete_document()."""
    pipeline = MagicMock()
    pipeline.document_index_provider = MagicMock()
    pipeline.soft_delete_document = MagicMock(side_effect=ForbiddenError("delete denied"))
    with patch("stache_ai.api.routes.documents.get_pipeline", return_value=pipeline):
        resp = client.delete("/api/documents/id/doc-1")
    assert resp.status_code == 403, resp.text
    assert resp.json() == {"detail": "delete denied"}


def test_update_document_metadata_forwards_forbidden_from_pipeline(client):
    """documents.py update_document_metadata wraps pipeline.update_document()."""
    pipeline = MagicMock()
    pipeline.update_document = MagicMock(side_effect=ForbiddenError("update denied"))
    with patch("stache_ai.api.routes.documents.get_pipeline", return_value=pipeline):
        resp = client.patch("/api/documents/doc-1", json={"filename": "new.pdf"})
    assert resp.status_code == 403, resp.text
    assert resp.json() == {"detail": "update denied"}


def test_create_insight_forwards_forbidden_from_pipeline(client):
    """insights.py create_insight wraps pipeline.create_insight()."""
    pipeline = MagicMock()
    pipeline.create_insight = AsyncMock(side_effect=ForbiddenError("insight denied"))
    with patch("stache_ai.api.routes.insights.get_pipeline", return_value=pipeline):
        resp = client.post("/api/insights", json={"content": "x", "namespace": "ns"})
    assert resp.status_code == 403, resp.text
    assert resp.json() == {"detail": "insight denied"}


def test_create_namespace_forwards_forbidden_from_provider(client):
    """namespaces.py create_namespace wraps provider.create()."""
    pipeline = MagicMock()
    pipeline.namespace_provider.create = MagicMock(side_effect=ForbiddenError("namespace denied"))
    with patch("stache_ai.api.routes.namespaces.get_pipeline", return_value=pipeline):
        resp = client.post("/api/namespaces", json={"id": "ns", "name": "NS"})
    assert resp.status_code == 403, resp.text
    assert resp.json() == {"detail": "namespace denied"}


def test_list_namespaces_forwards_forbidden_from_stats_helper(client):
    """namespaces.py get_namespace_stats swallows Exception into zero counts;
    a ForbiddenError from the document index must still deny the request."""
    pipeline = MagicMock()
    pipeline.namespace_provider.list = MagicMock(return_value=[{"id": "ns1", "name": "NS1"}])
    pipeline.document_index_provider.count_by_namespace = MagicMock(
        side_effect=ForbiddenError("stats denied")
    )
    with patch("stache_ai.api.routes.namespaces.get_pipeline", return_value=pipeline):
        resp = client.get("/api/namespaces")
    assert resp.status_code == 403, resp.text
    assert resp.json() == {"detail": "stats denied"}


def test_query_forwards_forbidden_from_pipeline(client):
    """query.py wraps pipeline.query() (awaited) in a blanket except."""
    pipeline = MagicMock()
    pipeline.query = AsyncMock(side_effect=ForbiddenError("query denied"))
    with patch("stache_ai.api.routes.query.get_pipeline", return_value=pipeline):
        resp = client.post("/api/query", json={"query": "hi"})
    assert resp.status_code == 403, resp.text
    assert resp.json() == {"detail": "query denied"}


def test_list_trash_forwards_forbidden_from_pipeline(client):
    """trash.py list_trash_documents wraps pipeline.list_trash()."""
    pipeline = MagicMock()
    pipeline.document_index_provider = MagicMock()
    pipeline.list_trash = MagicMock(side_effect=ForbiddenError("trash denied"))
    with patch("stache_ai.api.routes.trash.get_pipeline", return_value=pipeline):
        resp = client.get("/api/trash/")
    assert resp.status_code == 403, resp.text
    assert resp.json() == {"detail": "trash denied"}


def test_upload_forwards_forbidden_from_pipeline(client):
    """upload.py wraps pipeline.ingest_file() (awaited) in a blanket except."""
    pipeline = MagicMock()
    pipeline.ingest_file = AsyncMock(side_effect=ForbiddenError("upload denied"))
    with patch("stache_ai.api.routes.upload.get_pipeline", return_value=pipeline):
        resp = client.post(
            "/api/upload",
            files={"file": ("t.txt", b"hello", "text/plain")},
        )
    assert resp.status_code == 403, resp.text
    assert resp.json() == {"detail": "upload denied"}


def test_batch_upload_forwards_forbidden_from_pipeline(client):
    """upload.py batch_upload_documents' per-file loop must not swallow a
    denial into a per-file failure entry - it should abort the whole batch."""
    pipeline = MagicMock()
    pipeline.ingest_file = AsyncMock(side_effect=ForbiddenError("batch denied"))
    with patch("stache_ai.api.routes.upload.get_pipeline", return_value=pipeline):
        resp = client.post(
            "/api/upload/batch",
            files={"files": ("t.txt", b"hello", "text/plain")},
        )
    assert resp.status_code == 403, resp.text
    assert resp.json() == {"detail": "batch denied"}


def test_approve_pending_forwards_forbidden_from_pipeline(client, tmp_path, monkeypatch):
    """pending.py approve_pending wraps pipeline.ingest_text() (awaited)."""
    from stache_ai.config import settings

    monkeypatch.setattr(settings, "queue_dir", str(tmp_path))
    item_id = "item-1"
    (tmp_path / f"{item_id}.json").write_text(json.dumps({
        "id": item_id,
        "original_filename": "scan.pdf",
        "suggested_filename": "scan",
        "suggested_namespace": "ns",
        "extracted_text": "text",
        "full_text_length": 4,
        "created_at": "2026-01-01T00:00:00Z",
    }))
    (tmp_path / f"{item_id}.pdf").write_bytes(b"%PDF-1.4")

    pipeline = MagicMock()
    pipeline.ingest_text = AsyncMock(side_effect=ForbiddenError("approve denied"))
    with patch("stache_ai.api.routes.pending.load_document", return_value="extracted text"), \
         patch("stache_ai.api.routes.pending.get_pipeline", return_value=pipeline):
        resp = client.post(
            f"/api/pending/{item_id}/approve",
            json={"filename": "scan", "namespace": "ns"},
        )
    assert resp.status_code == 403, resp.text
    assert resp.json() == {"detail": "approve denied"}

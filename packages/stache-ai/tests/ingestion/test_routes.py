"""Route tests for /api/ingest, /api/jobs, and the /api/capture shim."""

import base64
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from stache_ai.config import Settings
from stache_ai.ingestion.base import Job, JobStatus
from stache_ai.ingestion.factory import IngestionServiceFactory


@pytest.fixture
def pipeline():
    p = AsyncMock()
    p.ingest_text.return_value = {"doc_id": "doc-1", "action": "ingested_new", "chunks_created": 3}
    p.ingest_file.return_value = {"doc_id": "doc-file", "chunks_created": 9}
    return p


@pytest.fixture
def service(pipeline, tmp_path):
    cfg = Settings(
        ingest_blob_provider="filesystem",
        ingest_blob_root=str(tmp_path / "blobs"),
    )
    return IngestionServiceFactory.build(cfg, pipeline)


@pytest.fixture
def client(service):
    from stache_ai.api.main import app
    with patch("stache_ai.api.routes.ingest.get_ingestion_service", return_value=service), \
         patch("stache_ai.api.routes.capture.get_ingestion_service", return_value=service):
        yield TestClient(app)


# ---- POST /api/ingest ----

def test_ingest_text_born_terminal(client):
    resp = client.post("/api/ingest", json={"text": "a quick note", "namespace": "default"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "done"
    assert data["doc_id"] == "doc-1"
    assert data["chunks_created"] == 3
    assert data["requested_by"] == "anonymous"


def test_ingest_dedup_skipped(client, pipeline):
    pipeline.ingest_text.return_value = {"doc_id": "dup", "action": "skipped", "chunks_created": 0}
    resp = client.post("/api/ingest", json={"text": "dup"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "skipped"
    assert resp.json()["doc_id"] == "dup"


def test_ingest_file_base64(client):
    payload = base64.b64encode(b"%PDF fake").decode()
    resp = client.post("/api/ingest", json={
        "filename": "r.pdf", "content_type": "application/pdf", "data_base64": payload,
    })
    assert resp.status_code == 200
    assert resp.json()["doc_id"] == "doc-file"


def test_ingest_requires_text_or_data(client):
    resp = client.post("/api/ingest", json={"namespace": "default"})
    assert resp.status_code == 400


def test_ingest_rejects_both_text_and_data(client):
    resp = client.post("/api/ingest", json={"text": "x", "data_base64": base64.b64encode(b"y").decode()})
    assert resp.status_code == 400


def test_ingest_rejects_bad_base64(client):
    resp = client.post("/api/ingest", json={
        "filename": "r.pdf", "content_type": "application/pdf", "data_base64": "!!!not base64!!!",
    })
    assert resp.status_code == 400


# ---- GET /api/jobs ----

def test_get_job_owner(client):
    job_id = client.post("/api/ingest", json={"text": "hello"}).json()["job_id"]
    resp = client.get(f"/api/jobs/{job_id}")
    assert resp.status_code == 200
    assert resp.json()["job_id"] == job_id


def test_get_job_missing_404(client):
    assert client.get("/api/jobs/nope").status_code == 404


def test_get_job_other_owner_404(client, service):
    # Job owned by someone else; anonymous caller must not see it.
    service.jobstore.create(Job(
        job_id="secret", status=JobStatus.DONE, namespace="default", source="api",
        filename="x", content_type="text", requested_by="bob",
        created_at="t", updated_at="t",
    ))
    assert client.get("/api/jobs/secret").status_code == 404


def test_list_jobs_scoped(client):
    client.post("/api/ingest", json={"text": "one"})
    client.post("/api/ingest", json={"text": "two"})
    resp = client.get("/api/jobs")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2
    assert all(j["requested_by"] == "anonymous" for j in data["jobs"])


def test_list_jobs_invalid_status_400(client):
    assert client.get("/api/jobs?status=bogus").status_code == 400


# ---- /api/capture shim ----

def test_capture_shim_legacy_shape(client):
    resp = client.post("/api/capture", json={"text": "captured thought"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["doc_id"] == "doc-1"
    assert data["chunks_created"] == 3
    assert data["action"] == "ingested_new"


def test_capture_shim_shares_service_path(client, pipeline):
    client.post("/api/capture", json={"text": "shared path", "metadata": {"topic": "x"}})
    # Worker called the same pipeline through the service.
    pipeline.ingest_text.assert_awaited()
    assert pipeline.ingest_text.call_args.kwargs["metadata"] == {"topic": "x"}

"""Route -> pipeline path tests (Phase 1e: no provider bypasses in routes).

Verifies that:
1. Rewritten document/trash/namespace routes call the new context-aware
   pipeline operations with a RequestContext carrying the authenticated
   principal's user_id (identity middleware -> request.state -> context).
2. The permanent-delete route fires notify_document_deleted exactly once
   (regression for the unified hard-delete implementation).
3. No route source file reaches into a provider's raw ``.client`` or imports
   qdrant_client (finding 5.10).
"""

import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import stache_ai.api.main as main_mod
import stache_ai.api.routes as routes_pkg
import stache_ai.api.routes.namespaces as namespaces_mod
from stache_ai.identity import Principal, PrincipalExtractor
from stache_ai.middleware.context import RequestContext
from stache_ai.rag.pipeline import RAGPipeline

USER_ID = "principal-42"


class _FixedExtractor(PrincipalExtractor):
    """Identity middleware extractor returning a fixed authenticated principal."""

    def extract(self, request):
        return Principal(user_id=USER_ID, claims={"ext": "opaque"})


@pytest.fixture
def client():
    """Test client with the identity middleware authenticating as USER_ID."""
    with patch.object(main_mod, "_principal_extractor", _FixedExtractor()):
        yield TestClient(main_mod.app)


def _assert_principal_context(mock_method):
    """Assert the last call passed a RequestContext for the authenticated user."""
    assert mock_method.call_args is not None, f"{mock_method} was not called"
    context = mock_method.call_args.kwargs.get("context")
    assert isinstance(context, RequestContext), (
        f"{mock_method} was called without a RequestContext (got {type(context)})"
    )
    assert context.user_id == USER_ID
    return context


# ---------------------------------------------------------------------------
# documents.py routes
# ---------------------------------------------------------------------------

@pytest.fixture
def documents_pipeline():
    """Fully mocked pipeline exposing the new context-aware operations."""
    pipeline = MagicMock()
    pipeline.document_index_provider = MagicMock()
    pipeline.list_documents = MagicMock(return_value={"documents": [], "next_key": None})
    pipeline.get_document_record = MagicMock(return_value={
        "doc_id": "doc-1",
        "filename": "f.txt",
        "namespace": "default",
        "chunk_count": 1,
        "created_at": "2026-01-01T00:00:00Z",
        "summary": "s",
        "headings": [],
        "metadata": {},
    })
    pipeline.get_document_chunks = MagicMock(return_value=[])
    pipeline.discover_documents = MagicMock(return_value=[])
    pipeline.soft_delete_document = MagicMock(return_value={
        "doc_id": "doc-1",
        "namespace": "default",
        "deleted_at": "2026-01-01T00:00:00Z",
        "deleted_at_ms": 1,
        "purge_after": "2026-02-01T00:00:00Z",
    })
    pipeline.permanently_delete_document = AsyncMock(return_value={
        "doc_id": "doc-1", "namespace": "default", "chunks_deleted": 2,
    })
    pipeline.delete_documents_by_filename = AsyncMock(return_value={"chunks_deleted": 3})
    return pipeline


@pytest.fixture
def documents_client(client, documents_pipeline):
    with patch("stache_ai.api.routes.documents.get_pipeline", return_value=documents_pipeline):
        yield client


def test_list_documents_uses_pipeline_with_principal_context(documents_client, documents_pipeline):
    response = documents_client.get("/api/documents")
    assert response.status_code == 200
    context = _assert_principal_context(documents_pipeline.list_documents)
    kwargs = documents_pipeline.list_documents.call_args.kwargs
    assert kwargs["namespace"] is None
    assert kwargs["limit"] == 100
    assert context.source == "api"


def test_discover_documents_uses_pipeline_with_principal_context(documents_client, documents_pipeline):
    response = documents_client.get("/api/documents/discover?query=leadership&namespace=ns1")
    assert response.status_code == 200
    context = _assert_principal_context(documents_pipeline.discover_documents)
    assert documents_pipeline.discover_documents.call_args.kwargs["query"] == "leadership"
    assert context.namespace == "ns1"


def test_get_chunks_uses_pipeline_with_principal_context(documents_client, documents_pipeline):
    response = documents_client.get("/api/documents/chunks?point_ids=a,b")
    assert response.status_code == 200
    _assert_principal_context(documents_pipeline.get_document_chunks)
    assert documents_pipeline.get_document_chunks.call_args.args[0] == ["a", "b"]


def test_get_document_uses_pipeline_with_principal_context(documents_client, documents_pipeline):
    response = documents_client.get("/api/documents/id/doc-1?namespace=ns1")
    assert response.status_code == 200
    context = _assert_principal_context(documents_pipeline.get_document_record)
    assert documents_pipeline.get_document_record.call_args.args == ("doc-1", "ns1")
    assert context.namespace == "ns1"


def test_soft_delete_uses_pipeline_with_principal_context(documents_client, documents_pipeline):
    response = documents_client.delete("/api/documents/id/doc-1?namespace=ns1")
    assert response.status_code == 200
    context = _assert_principal_context(documents_pipeline.soft_delete_document)
    kwargs = documents_pipeline.soft_delete_document.call_args.kwargs
    assert kwargs["doc_id"] == "doc-1"
    assert kwargs["namespace"] == "ns1"
    assert context.namespace == "ns1"
    # Permanent path must not run on soft delete
    documents_pipeline.permanently_delete_document.assert_not_called()


def test_permanent_delete_uses_pipeline_with_principal_context(documents_client, documents_pipeline):
    response = documents_client.delete("/api/documents/id/doc-1?namespace=ns1&permanent=true")
    assert response.status_code == 200
    assert response.json()["chunks_deleted"] == 2
    _assert_principal_context(documents_pipeline.permanently_delete_document)
    assert documents_pipeline.permanently_delete_document.call_args.args == ("doc-1", "ns1")
    documents_pipeline.soft_delete_document.assert_not_called()


def test_delete_by_filename_uses_pipeline_with_principal_context(documents_client, documents_pipeline):
    response = documents_client.delete("/api/documents?filename=f.txt&namespace=ns1")
    assert response.status_code == 200
    assert response.json()["chunks_deleted"] == 3
    context = _assert_principal_context(documents_pipeline.delete_documents_by_filename)
    kwargs = documents_pipeline.delete_documents_by_filename.call_args.kwargs
    assert kwargs["filename"] == "f.txt"
    assert kwargs["namespace"] == "ns1"
    assert context.namespace == "ns1"


# ---------------------------------------------------------------------------
# trash.py routes
# ---------------------------------------------------------------------------

@pytest.fixture
def trash_pipeline():
    pipeline = MagicMock()
    pipeline.document_index_provider = MagicMock()
    pipeline.list_trash = MagicMock(return_value={"items": [], "next_key": None, "count": 0})
    pipeline.restore_document = MagicMock(return_value={
        "doc_id": "doc-1", "namespace": "ns1", "status": "active",
    })
    pipeline.purge_trash_entry = MagicMock(return_value={
        "doc_id": "doc-1", "namespace": "ns1", "chunk_count": 4, "cleanup_job_id": "job-1",
    })
    return pipeline


@pytest.fixture
def trash_client(client, trash_pipeline):
    with patch("stache_ai.api.routes.trash.get_pipeline", return_value=trash_pipeline):
        yield client


def test_list_trash_uses_pipeline_with_principal_context(trash_client, trash_pipeline):
    response = trash_client.get("/api/trash/?namespace=ns1")
    assert response.status_code == 200
    context = _assert_principal_context(trash_pipeline.list_trash)
    assert trash_pipeline.list_trash.call_args.kwargs["namespace"] == "ns1"
    assert context.namespace == "ns1"


def test_restore_uses_pipeline_with_principal_context(trash_client, trash_pipeline):
    response = trash_client.post(
        "/api/trash/restore",
        json={"doc_id": "doc-1", "namespace": "ns1", "deleted_at_ms": 123},
    )
    assert response.status_code == 200
    context = _assert_principal_context(trash_pipeline.restore_document)
    kwargs = trash_pipeline.restore_document.call_args.kwargs
    assert kwargs["doc_id"] == "doc-1"
    assert kwargs["deleted_at_ms"] == 123
    assert context.namespace == "ns1"


def test_trash_permanent_uses_pipeline_with_principal_context(trash_client, trash_pipeline):
    response = trash_client.post(
        "/api/trash/permanent",
        json={"doc_id": "doc-1", "namespace": "ns1", "deleted_at_ms": 123, "filename": "f.txt"},
    )
    assert response.status_code == 200
    assert response.json()["cleanup_job_id"] == "job-1"
    context = _assert_principal_context(trash_pipeline.purge_trash_entry)
    kwargs = trash_pipeline.purge_trash_entry.call_args.kwargs
    assert kwargs["doc_id"] == "doc-1"
    assert kwargs["filename"] == "f.txt"
    assert context.namespace == "ns1"


# ---------------------------------------------------------------------------
# namespaces.py routes
# ---------------------------------------------------------------------------

@pytest.fixture
def namespaces_pipeline():
    pipeline = MagicMock()
    pipeline.namespace_provider = MagicMock()
    pipeline.namespace_provider.list.return_value = []
    pipeline.namespace_provider.get.return_value = None
    pipeline.document_index_provider = MagicMock()
    pipeline.document_index_provider.count_by_namespace.return_value = {
        "doc_count": 0, "chunk_count": 0,
    }
    return pipeline


@pytest.fixture
def namespaces_client(client, namespaces_pipeline):
    with patch("stache_ai.api.routes.namespaces.get_pipeline", return_value=namespaces_pipeline):
        yield client


def test_no_module_level_namespace_provider_singleton():
    """The route module must not build its own provider instance (one shared
    instance lives on the pipeline)."""
    assert not hasattr(namespaces_mod, "_namespace_provider")


def test_get_namespace_provider_returns_pipeline_instance(namespaces_pipeline):
    with patch("stache_ai.api.routes.namespaces.get_pipeline", return_value=namespaces_pipeline):
        assert namespaces_mod.get_namespace_provider() is namespaces_pipeline.namespace_provider


def test_list_namespaces_passes_principal_context_to_provider(namespaces_client, namespaces_pipeline):
    response = namespaces_client.get("/api/namespaces?include_stats=false")
    assert response.status_code == 200
    _assert_principal_context(namespaces_pipeline.namespace_provider.list)


def test_create_namespace_passes_principal_context_to_provider(namespaces_client, namespaces_pipeline):
    namespaces_pipeline.namespace_provider.create.return_value = {
        "id": "ns1", "name": "NS1", "description": "", "parent_id": None,
    }
    response = namespaces_client.post(
        "/api/namespaces", json={"id": "ns1", "name": "NS1"},
    )
    assert response.status_code == 200
    context = _assert_principal_context(namespaces_pipeline.namespace_provider.create)
    assert context.namespace == "ns1"


def test_delete_namespace_passes_principal_context_to_provider(namespaces_client, namespaces_pipeline):
    namespaces_pipeline.namespace_provider.get.return_value = {"id": "ns1", "name": "NS1"}
    namespaces_pipeline.namespace_provider.delete.return_value = True
    namespaces_pipeline.documents_provider.delete_by_metadata.return_value = {"deleted": 0}
    namespaces_pipeline.summaries_provider.delete_by_metadata.return_value = {"deleted": 0}

    response = namespaces_client.delete("/api/namespaces/ns1")
    assert response.status_code == 200
    _assert_principal_context(namespaces_pipeline.namespace_provider.delete)
    # Vector purges from this route must also carry the caller's context
    _assert_principal_context(namespaces_pipeline.documents_provider.delete_by_metadata)


# ---------------------------------------------------------------------------
# Regression: unified hard delete fires delete observers exactly once
# ---------------------------------------------------------------------------

def _pipeline_with_real_hard_delete():
    """MagicMock pipeline running the REAL unified hard-delete implementation."""
    pipeline = MagicMock()
    pipeline.document_index_provider = MagicMock()
    pipeline.document_index_provider.get_chunk_ids.return_value = ["c1", "c2"]
    pipeline.notify_document_deleted = AsyncMock()
    for name in ("permanently_delete_document", "_hard_delete_document", "delete_documents_by_filename"):
        setattr(pipeline, name, getattr(RAGPipeline, name).__get__(pipeline))
    return pipeline


def test_permanent_delete_route_fires_delete_observers_exactly_once(client):
    pipeline = _pipeline_with_real_hard_delete()

    with patch("stache_ai.api.routes.documents.get_pipeline", return_value=pipeline):
        response = client.delete("/api/documents/id/doc-1?namespace=ns1&permanent=true")

    assert response.status_code == 200
    assert response.json()["chunks_deleted"] == 2
    pipeline.notify_document_deleted.assert_awaited_once()
    args, kwargs = pipeline.notify_document_deleted.call_args
    assert args[0] == "doc-1"
    assert args[1] == "ns1"
    assert kwargs["context"].user_id == USER_ID


def test_delete_by_filename_route_shares_unified_hard_delete(client):
    """Finding 2.7: filename-based delete funnels through the same hard-delete
    implementation (observers fire once, vectors + index both cleaned)."""
    pipeline = _pipeline_with_real_hard_delete()
    pipeline.document_index_provider.get_document_by_source_path.return_value = {
        "doc_id": "doc-1", "chunk_ids": ["c1", "c2", "c3"],
    }

    with patch("stache_ai.api.routes.documents.get_pipeline", return_value=pipeline):
        response = client.delete("/api/documents?filename=f.txt&namespace=ns1")

    assert response.status_code == 200
    assert response.json()["chunks_deleted"] == 3
    pipeline.vectordb_provider.delete.assert_called_once()
    pipeline.document_index_provider.delete_document.assert_called_once()
    pipeline.notify_document_deleted.assert_awaited_once()


# ---------------------------------------------------------------------------
# Static source checks (finding 5.10): no raw client access in routes
# ---------------------------------------------------------------------------

def _route_sources():
    routes_dir = Path(routes_pkg.__file__).parent
    return sorted(p for p in routes_dir.glob("*.py"))


def test_routes_never_access_raw_provider_client():
    pattern = re.compile(r"\.client\.")
    offenders = []
    for path in _route_sources():
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if pattern.search(line):
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert not offenders, (
        "Routes must call provider methods via the pipeline, never a raw "
        f"provider .client: {offenders}"
    )


def test_routes_never_import_qdrant_client():
    offenders = []
    for path in _route_sources():
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if "qdrant_client" in line:
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert not offenders, (
        f"Routes must not import provider-specific SDKs: {offenders}"
    )


# ---------------------------------------------------------------------------
# Context threading: document update, insights, namespace path/ancestors
# ---------------------------------------------------------------------------

def test_update_document_passes_principal_context(documents_client, documents_pipeline):
    documents_pipeline.update_document = MagicMock(return_value={
        "success": True, "doc_id": "doc-1", "namespace": "default",
        "updated_chunks": 1, "updated_document": True,
    })
    response = documents_client.patch(
        "/api/documents/doc-1?current_namespace=default",
        json={"filename": "renamed.txt"},
    )
    assert response.status_code == 200
    context = _assert_principal_context(documents_pipeline.update_document)
    assert context.namespace == "default"


@pytest.fixture
def insights_pipeline():
    pipeline = MagicMock()
    pipeline.create_insight = AsyncMock(return_value={
        "insight_id": "i-1", "success": True, "namespace": "ns1",
        "created_at": "2026-01-01T00:00:00Z", "tags": None,
    })
    pipeline.search_insights = AsyncMock(return_value={"insights": [], "count": 0})
    pipeline.delete_insight = MagicMock(return_value={
        "success": True, "insight_id": "i-1", "namespace": "ns1",
    })
    return pipeline


@pytest.fixture
def insights_client(client, insights_pipeline):
    with patch("stache_ai.api.routes.insights.get_pipeline", return_value=insights_pipeline):
        yield client


def test_create_insight_passes_principal_context(insights_client, insights_pipeline):
    response = insights_client.post(
        "/api/insights", json={"content": "note", "namespace": "ns1"},
    )
    assert response.status_code == 200
    context = _assert_principal_context(insights_pipeline.create_insight)
    assert context.namespace == "ns1"


def test_search_insights_passes_principal_context(insights_client, insights_pipeline):
    response = insights_client.get("/api/insights/search?query=q&namespace=ns1")
    assert response.status_code == 200
    _assert_principal_context(insights_pipeline.search_insights)


def test_delete_insight_passes_principal_context(insights_client, insights_pipeline):
    response = insights_client.delete("/api/insights/i-1?namespace=ns1")
    assert response.status_code == 200
    _assert_principal_context(insights_pipeline.delete_insight)


def test_get_namespace_passes_context_to_path_and_ancestors(namespaces_client, namespaces_pipeline):
    provider = namespaces_pipeline.namespace_provider
    provider.get.return_value = {"id": "ns1", "name": "NS 1", "parent_id": None}
    provider.get_path.return_value = "NS 1"
    provider.get_ancestors.return_value = []
    response = namespaces_client.get("/api/namespaces/ns1")
    assert response.status_code == 200
    _assert_principal_context(provider.get_path)
    _assert_principal_context(provider.get_ancestors)

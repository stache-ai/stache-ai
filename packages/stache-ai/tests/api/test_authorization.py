"""Route-level enforcement tests for the pluggable authorization seam (S1).

The OSS core ships only the neutral seam: routes call the configured
authorizer with an operation string and an opaque resource dict, and a denial
surfaces as a 403 with a JSON ``detail``. These tests wire a deny-all
authorizer through the real config/entry-point path (register_provider +
settings) to prove every enforcement point actually enforces.
"""

import pytest
from fastapi.testclient import TestClient

import stache_ai.api.main as main_mod
from stache_ai import identity
from stache_ai.config import settings
from stache_ai.providers import plugin_loader


class DenyAllAuthorizer(identity.AuthorizationProvider):
    """Test authorizer that denies everything and records what it saw."""

    seen: list = []

    def __init__(self, config=None):
        self._config = config

    def authorize(self, principal, operation, resource=None):
        DenyAllAuthorizer.seen.append((principal, operation, resource))
        raise identity.ForbiddenError(f"operation '{operation}' denied")


@pytest.fixture
def deny_all_client(monkeypatch):
    """TestClient with a deny-all authorizer wired via the real config path."""
    DenyAllAuthorizer.seen = []
    plugin_loader.register_provider("authorizer", "deny-all-test", DenyAllAuthorizer)
    monkeypatch.setattr(settings, "authorization_provider", "deny-all-test")
    identity.reset_authorizer()
    try:
        yield TestClient(main_mod.app)
    finally:
        identity.reset_authorizer()
        plugin_loader.reset()


# Every mutating route with the operation string it must present.
MUTATING_CALLS = [
    ("capture", "POST", "/api/capture", {"json": {"text": "hi"}}),
    ("ingest", "POST", "/api/ingest",
     {"json": {"text": "hi", "content_type": "text"}}),
    ("ingest", "POST", "/api/ingest",
     {"json": {"upload": True, "filename": "f.pdf", "content_type": "application/pdf"}}),
    ("upload", "POST", "/api/upload",
     {"files": {"file": ("t.txt", b"hello", "text/plain")}}),
    ("upload", "POST", "/api/upload/batch",
     {"files": {"files": ("t.txt", b"hello", "text/plain")}}),
    ("approve_pending", "POST", "/api/pending/item-1/approve",
     {"json": {"filename": "f", "namespace": "ns"}}),
    ("reject_pending", "DELETE", "/api/pending/item-1", {}),
    ("update_document", "PATCH", "/api/documents/doc-1",
     {"json": {"filename": "new.pdf"}}),
    ("delete_document", "DELETE", "/api/documents/id/doc-1", {}),
    ("delete_document", "DELETE", "/api/documents",
     {"params": {"filename": "f.pdf", "namespace": "ns"}}),
    ("delete_document", "DELETE", "/api/documents/orphaned",
     {"params": {"all_orphaned": "true"}}),
    ("restore_document", "POST", "/api/trash/restore",
     {"json": {"doc_id": "d", "namespace": "ns", "deleted_at_ms": 1}}),
    ("purge_trash", "POST", "/api/trash/permanent",
     {"json": {"doc_id": "d", "namespace": "ns", "deleted_at_ms": 1}}),
    ("regenerate_summary", "POST", "/api/documents/migrate-summaries", {}),
    ("create_namespace", "POST", "/api/namespaces",
     {"json": {"id": "ns", "name": "NS"}}),
    ("update_namespace", "PUT", "/api/namespaces/ns", {"json": {"name": "X"}}),
    ("delete_namespace", "DELETE", "/api/namespaces/ns", {}),
    ("create_insight", "POST", "/api/insights",
     {"json": {"content": "x", "namespace": "ns"}}),
    ("delete_insight", "DELETE", "/api/insights/i-1", {"params": {"namespace": "ns"}}),
]

# Reads enforced cheaply with the already-extracted principal.
READ_CALLS = [
    ("query", "POST", "/api/query", {"json": {"query": "hi"}}),
    ("query", "GET", "/api/insights/search",
     {"params": {"query": "hi", "namespace": "ns"}}),
    ("read_document", "GET", "/api/documents", {}),
    ("read_document", "GET", "/api/documents/id/doc-1", {}),
    ("read_document", "GET", "/api/trash/", {}),
    ("read_namespace", "GET", "/api/namespaces", {}),
    ("read_job", "GET", "/api/jobs", {}),
    ("read_job", "GET", "/api/jobs/j-1", {}),
]


@pytest.mark.parametrize("operation,method,path,kwargs", MUTATING_CALLS)
def test_mutating_routes_denied_with_403(deny_all_client, operation, method, path, kwargs):
    resp = deny_all_client.request(method, path, **kwargs)
    assert resp.status_code == 403, f"{method} {path} -> {resp.status_code}: {resp.text}"
    assert resp.json() == {"detail": f"operation '{operation}' denied"}
    # The route presented the expected neutral operation string.
    assert DenyAllAuthorizer.seen[-1][1] == operation


@pytest.mark.parametrize("operation,method,path,kwargs", READ_CALLS)
def test_read_routes_denied_with_403(deny_all_client, operation, method, path, kwargs):
    resp = deny_all_client.request(method, path, **kwargs)
    assert resp.status_code == 403, f"{method} {path} -> {resp.status_code}: {resp.text}"
    assert resp.json() == {"detail": f"operation '{operation}' denied"}
    assert DenyAllAuthorizer.seen[-1][1] == operation


def test_resource_dict_carries_namespace(deny_all_client):
    deny_all_client.post("/api/capture", json={"text": "hi", "namespace": "ns-7"})
    principal, operation, resource = DenyAllAuthorizer.seen[-1]
    assert operation == "capture"
    assert resource == {"namespace": "ns-7"}


def test_default_configuration_allows_everything():
    """Nothing configured -> AllowAllAuthorizer -> existing behavior unchanged."""
    identity.reset_authorizer()
    try:
        assert isinstance(identity.get_authorizer(), identity.AllowAllAuthorizer)
        client = TestClient(main_mod.app)
        # A representative read route succeeds with no authorizer configured.
        resp = client.get("/api/jobs")
        assert resp.status_code == 200
    finally:
        identity.reset_authorizer()


def test_reset_authorizer_isolates_configuration(monkeypatch):
    """A deny-all left over from one test must not leak past reset_authorizer."""
    plugin_loader.register_provider("authorizer", "deny-all-test", DenyAllAuthorizer)
    monkeypatch.setattr(settings, "authorization_provider", "deny-all-test")
    identity.reset_authorizer()
    try:
        assert isinstance(identity.get_authorizer(), DenyAllAuthorizer)
    finally:
        monkeypatch.setattr(settings, "authorization_provider", None)
        identity.reset_authorizer()
        plugin_loader.reset()
    assert isinstance(identity.get_authorizer(), identity.AllowAllAuthorizer)
    identity.reset_authorizer()


def test_misconfigured_authorizer_aborts_startup_path(monkeypatch):
    """Fail-closed: a configured-but-unknown name raises instead of degrading."""
    monkeypatch.setattr(settings, "authorization_provider", "not-installed")
    identity.reset_authorizer()
    try:
        with pytest.raises(RuntimeError, match="Refusing to fall back"):
            identity.get_authorizer()
    finally:
        identity.reset_authorizer()

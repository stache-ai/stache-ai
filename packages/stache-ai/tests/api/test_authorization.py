"""Route-level enforcement tests for the pluggable authorization seam (S1).

The OSS core ships only the neutral seam: routes call the configured
authorizer with an operation string and an opaque resource dict, and a denial
surfaces as a 403 with a JSON ``detail``. These tests wire a deny-all
authorizer through the real config/entry-point path (register_provider +
settings) to prove every enforcement point actually enforces.
"""

import ast
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import stache_ai.api.main as main_mod
import stache_ai.api.routes as routes_pkg
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
    # /capture shares the ingestion service + worker with /ingest, so it
    # enforces the SAME canonical content-write op "ingest" (AUTHZ F4/F5).
    ("ingest", "POST", "/api/capture", {"json": {"text": "hi"}}),
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
    ("read_pending", "GET", "/api/pending", {}),
    ("read_pending", "GET", "/api/pending/item-1", {}),
    ("read_pending", "GET", "/api/pending/item-1/thumbnail", {}),
    ("read_pending", "GET", "/api/pending/item-1/pdf", {}),
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


class LimitRejectingAuthorizer(identity.AuthorizationProvider):
    """Test authorizer that rejects with the neutral limit signal.

    Any deployment guard/processor/provider may raise LimitExceededError; using
    the authorizer seam here is just a convenient wired-through raise site.
    """

    def __init__(self, config=None):
        self._config = config

    def authorize(self, principal, operation, resource=None):
        raise identity.LimitExceededError("slow down")


@pytest.fixture
def limit_client(monkeypatch):
    plugin_loader.register_provider("authorizer", "limit-test", LimitRejectingAuthorizer)
    monkeypatch.setattr(settings, "authorization_provider", "limit-test")
    identity.reset_authorizer()
    try:
        yield TestClient(main_mod.app)
    finally:
        identity.reset_authorizer()
        plugin_loader.reset()


@pytest.mark.parametrize("method,path,kwargs", [
    ("POST", "/api/capture", {"json": {"text": "hi"}}),
    ("POST", "/api/query", {"json": {"query": "hi"}}),
    ("DELETE", "/api/documents/id/doc-1", {}),
])
def test_limit_exceeded_maps_to_429_with_retry_after(limit_client, method, path, kwargs):
    """A LimitExceededError raised mid-request reaches the app handler as 429
    with a Retry-After header, instead of being rewritten into a 500 by a
    route's blanket except."""
    resp = limit_client.request(method, path, **kwargs)
    assert resp.status_code == 429, f"{method} {path} -> {resp.status_code}: {resp.text}"
    assert resp.json() == {"detail": "slow down"}
    assert resp.headers.get("Retry-After") == "60"


def test_resource_dict_carries_namespace(deny_all_client):
    deny_all_client.post("/api/capture", json={"text": "hi", "namespace": "ns-7"})
    principal, operation, resource = DenyAllAuthorizer.seen[-1]
    assert operation == "ingest"
    assert resource == {"namespace": "ns-7"}


class NamespaceScopedAuthorizer(identity.AuthorizationProvider):
    """Allows every op EXCEPT writes whose resource namespace is denied.

    Models a deployment authorizer that scopes by namespace: it lets the
    caller act on their source namespace but rejects the relocation destination,
    proving the routes authorize the DESTINATION, not just the source (F1).
    """

    denied_namespaces: set = set()
    seen: list = []

    def __init__(self, config=None):
        self._config = config

    def authorize(self, principal, operation, resource=None):
        NamespaceScopedAuthorizer.seen.append((operation, resource))
        ns = (resource or {}).get("namespace")
        if ns in NamespaceScopedAuthorizer.denied_namespaces:
            raise identity.ForbiddenError(f"namespace '{ns}' denied")


@pytest.fixture
def ns_scoped_client(monkeypatch):
    NamespaceScopedAuthorizer.seen = []
    NamespaceScopedAuthorizer.denied_namespaces = set()
    plugin_loader.register_provider("authorizer", "ns-scoped-test", NamespaceScopedAuthorizer)
    monkeypatch.setattr(settings, "authorization_provider", "ns-scoped-test")
    identity.reset_authorizer()
    try:
        yield TestClient(main_mod.app)
    finally:
        identity.reset_authorizer()
        plugin_loader.reset()


def test_document_relocation_authorizes_destination_namespace(ns_scoped_client):
    """AUTHZ F1: moving a doc into a namespace the caller may read/update from
    but NOT write to is blocked by the destination "ingest" check."""
    NamespaceScopedAuthorizer.denied_namespaces = {"dest-ns"}
    resp = ns_scoped_client.patch(
        "/api/documents/doc-1?current_namespace=src-ns",
        json={"namespace": "dest-ns"},
    )
    assert resp.status_code == 403, resp.text
    assert resp.json() == {"detail": "namespace 'dest-ns' denied"}
    # The source passed; the destination write op is what denied.
    assert ("update_document", {"namespace": "src-ns"}) in NamespaceScopedAuthorizer.seen
    assert ("ingest", {"namespace": "dest-ns"}) in NamespaceScopedAuthorizer.seen


def test_namespace_reparent_authorizes_destination_parent(ns_scoped_client):
    """AUTHZ F1: reparenting under a parent the caller doesn't control is
    blocked by the destination-parent check."""
    NamespaceScopedAuthorizer.denied_namespaces = {"new-parent"}
    resp = ns_scoped_client.put(
        "/api/namespaces/child-ns",
        json={"name": "Child", "parent_id": "new-parent"},
    )
    assert resp.status_code == 403, resp.text
    assert resp.json() == {"detail": "namespace 'new-parent' denied"}
    assert ("update_namespace", {"namespace": "child-ns"}) in NamespaceScopedAuthorizer.seen
    assert ("update_namespace",
            {"namespace": "new-parent", "child_id": "child-ns"}) in NamespaceScopedAuthorizer.seen


def test_namespace_create_authorizes_destination_parent(ns_scoped_client):
    """AUTHZ F1: creating a namespace under a parent the caller doesn't control
    is blocked by the destination-parent check."""
    NamespaceScopedAuthorizer.denied_namespaces = {"locked-parent"}
    resp = ns_scoped_client.post(
        "/api/namespaces",
        json={"id": "new-child", "name": "New", "parent_id": "locked-parent"},
    )
    assert resp.status_code == 403, resp.text
    assert resp.json() == {"detail": "namespace 'locked-parent' denied"}
    assert ("create_namespace",
            {"namespace": "locked-parent", "child_id": "new-child"}) in NamespaceScopedAuthorizer.seen


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


# ---------------------------------------------------------------------------
# Static sweep: every blanket ``except Exception`` in a route module must not
# swallow a ForbiddenError raised deeper in the call (a plugged authorizer or
# a provider denying mid-request). A route that calls ``auth.authorize()``
# and then does real work in a broad try/except needs a preceding
# ``except ForbiddenError: raise`` in the SAME try statement, or the denial
# gets rewritten into a 500 by the blanket handler.
#
# Entries below are the only except-Exception blocks that legitimately don't
# need one, because nothing reachable in the guarded body can raise
# ForbiddenError. Keep this allowlist short and remove entries once the
# guarded code changes to make the justification stale.
# ---------------------------------------------------------------------------

_FORBIDDEN_SWEEP_ALLOWLIST = {
    # No auth.authorize() call anywhere in this route; it's an unauthenticated
    # health probe that only reports provider connectivity.
    ("health.py", "except Exception"): "no authorization check in this route",
    # Reads local queue JSON files off disk (json.load / Pydantic parsing) -
    # no authorizer or provider call happens inside this loop.
    ("pending.py", "except Exception"): "local file read only, no provider/authorizer call",
}


def _is_bare_exception_handler(handler: ast.ExceptHandler) -> bool:
    return isinstance(handler.type, ast.Name) and handler.type.id == "Exception"


def _is_reraise_handler(handler: ast.ExceptHandler, exc_name: str) -> bool:
    if not (isinstance(handler.type, ast.Name) and handler.type.id == exc_name):
        return False
    # Body must be a bare `raise` (comments are not AST nodes, so a leading
    # comment is fine) - a re-raise, not a handler that swallows/transforms.
    return len(handler.body) == 1 and isinstance(handler.body[0], ast.Raise) \
        and handler.body[0].exc is None


def _is_forbidden_reraise_handler(handler: ast.ExceptHandler) -> bool:
    return _is_reraise_handler(handler, "ForbiddenError")


def _is_limit_reraise_handler(handler: ast.ExceptHandler) -> bool:
    return _is_reraise_handler(handler, "LimitExceededError")


def test_route_modules_reraise_forbidden_before_blanket_except():
    """Static sweep making FIX 1 durable against future route additions.

    Every ``except Exception`` in ``api/routes/*.py`` must be preceded, in the
    same try statement, by BOTH an ``except ForbiddenError: raise`` AND an
    ``except LimitExceededError: raise`` -- otherwise a denial (403) or a
    configured-limit rejection (429) raised inside the route body (by a plugged
    authorizer, guard, processor, or provider) would be swallowed into a 500
    instead of surfacing with its correct status. Both neutral exceptions must
    be enforced machine-side so neither can regress.
    """
    routes_dir = Path(routes_pkg.__file__).parent
    violations = []

    for path in sorted(routes_dir.glob("*.py")):
        source = path.read_text()
        tree = ast.parse(source, filename=str(path))
        identity_imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.module == "stache_ai.identity"
            for alias in node.names
        }

        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            for idx, handler in enumerate(node.handlers):
                if not _is_bare_exception_handler(handler):
                    continue
                key = (path.name, "except Exception")
                if key in _FORBIDDEN_SWEEP_ALLOWLIST:
                    continue
                preceding = node.handlers[:idx]
                missing = []
                if not any(_is_forbidden_reraise_handler(h) for h in preceding):
                    missing.append("except ForbiddenError: raise")
                if not any(_is_limit_reraise_handler(h) for h in preceding):
                    missing.append("except LimitExceededError: raise")
                if not missing:
                    continue
                violations.append(
                    f"{path.name}:{handler.lineno} `except Exception` with no "
                    f"preceding {' and '.join(missing)} in the same try "
                    f"(identity imports: {sorted(identity_imports)})"
                )

    assert not violations, "Unguarded except-Exception block(s):\n" + "\n".join(violations)

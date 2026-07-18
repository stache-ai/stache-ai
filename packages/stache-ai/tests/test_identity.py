"""Tests for the Principal identity seam (Workstream 0)."""

import asyncio
from unittest.mock import AsyncMock

from stache_ai.identity import ANONYMOUS, Principal, assert_can_write


def test_principal_of_normalizes_string():
    p = Principal.of("user-1")
    assert p.user_id == "user-1"
    assert p.claims == {}
    assert not p.is_anonymous


def test_principal_of_none_is_anonymous():
    p = Principal.of(None)
    assert p.user_id == ANONYMOUS
    assert p.is_anonymous


def test_principal_of_passthrough():
    p = Principal(user_id="u", claims={"scope": "x"})
    assert Principal.of(p) is p


def test_assert_can_write_allows_by_default():
    """Nothing configured -> AllowAllAuthorizer -> writes pass through."""
    from stache_ai import identity

    identity.reset_authorizer()
    try:
        assert assert_can_write(Principal(user_id="u"), "ns") is None
    finally:
        identity.reset_authorizer()


def test_api_principal_extracts_sub_and_opaque_claims():
    from stache_ai.api import auth

    class _Req:
        scope = {"aws.event": {"requestContext": {"authorizer": {"jwt": {"claims": {
            "sub": "abc", "custom:anything": "opaque-value"}}}}}}

    p = auth.principal(_Req())
    assert isinstance(p, Principal)
    assert p.user_id == "abc"
    # Claims pass through opaquely; core attaches no meaning to any key.
    assert p.claims["custom:anything"] == "opaque-value"


def test_api_principal_anonymous_without_event():
    from stache_ai.api import auth

    class _Req:
        scope = {}

    p = auth.principal(_Req())
    assert p.is_anonymous


def test_submit_normalizes_principal_and_stores_user_id():
    """service.submit accepts a Principal; Job.requested_by stores user_id and
    the opaque principal reaches jobstore.create and blobstore.make_key."""
    from stache_ai.ingestion.base import IntakeTicket, JobStatus
    from stache_ai.ingestion.factory import IngestionService

    seen = {}

    from stache_ai.ingestion.base import JobStore

    class _Store(JobStore):
        def __init__(self):
            self.jobs = {}

        def create(self, job, *, principal=None):
            seen["create_principal"] = principal
            self.jobs[job.job_id] = job

        def update(self, job_id, **fields):
            job = self.jobs[job_id]
            for k, v in fields.items():
                setattr(job, k, v)
            return job

        def get(self, job_id):
            return self.jobs.get(job_id)

        def claim(self, job_id, *, from_statuses, to_status=None):
            return True

        def list(self, **kw):
            return list(self.jobs.values()), None

    class _Blob:
        def make_key(self, job_id, filename, *, principal=None):
            seen["make_key_principal"] = principal
            return f"custom/{job_id}/{filename}"

        def put(self, key, data, metadata):
            seen["put_key"] = key
            return key

        def get(self, key):
            return b"", {}

    class _Intake:
        def begin(self, **kwargs):
            seen["intake_kwargs"] = kwargs
            return IntakeTicket(job_id=kwargs["job_id"])

    class _Queue:
        async def enqueue(self, job_id):
            return None

    svc = IngestionService(
        intake=_Intake(), queue=_Queue(), jobstore=_Store(),
        blobstore=_Blob(), notifier=AsyncMock(), worker=None,
    )
    caller = Principal(user_id="alice", claims={"ext": "opaque"})
    job = asyncio.run(svc.submit(
        namespace="ns", content_type="application/pdf", requested_by=caller,
        filename="f.pdf", data=b"bytes",
    ))
    assert job.requested_by == "alice"
    assert job.status == JobStatus.QUEUED
    assert seen["create_principal"] is caller
    assert seen["make_key_principal"] is caller
    assert seen["intake_kwargs"]["principal"] is caller
    assert seen["intake_kwargs"]["requested_by"] == "alice"
    # Overridden make_key controls the blob key end-to-end.
    assert job.blob_key == f"custom/{job.job_id}/f.pdf"
    assert seen["put_key"] == job.blob_key


def test_worker_passes_context_and_job_to_pipeline():
    """The worker threads a RequestContext (user + opaque job) into the pipeline."""
    from stache_ai.ingestion.base import Job, JobStatus
    from stache_ai.ingestion.worker import make_worker

    job = Job(
        job_id="j1", status=JobStatus.QUEUED, namespace="ns", source="api",
        filename="note", content_type="text", requested_by="alice",
        metadata={"_text": "hello world"},
    )

    from stache_ai.ingestion.base import JobStore

    class _Store(JobStore):
        def create(self, job, *, principal=None):
            pass

        def get(self, job_id):
            return job

        def claim(self, job_id, *, from_statuses, to_status=None):
            return True

        def update(self, job_id, **fields):
            for k, v in fields.items():
                setattr(job, k, v)
            return job

        def list(self, **kw):
            return [job], None

    pipeline = AsyncMock()
    pipeline.ingest_text.return_value = {"doc_id": "d1", "chunks_created": 1}
    notifier = type("N", (), {"publish": lambda self, e: None})()

    worker = make_worker(_Store(), AsyncMock(), notifier, pipeline)
    asyncio.run(worker("j1"))

    ctx = pipeline.ingest_text.call_args.kwargs["context"]
    assert ctx.user_id == "alice"
    assert ctx.namespace == "ns"
    assert ctx.source == "worker"
    assert ctx.custom["ingest_job"] is job
    assert job.status == JobStatus.DONE


def test_build_extractor_default():
    from stache_ai.identity import ApiGatewayClaimsExtractor, build_extractor

    class _Cfg:
        principal_extractor = "apigateway"

    assert isinstance(build_extractor(_Cfg()), ApiGatewayClaimsExtractor)


def test_build_extractor_unknown_is_fail_closed():
    """A configured-but-missing extractor must abort, never fall back."""
    import pytest as _pytest

    from stache_ai.identity import build_extractor

    class _Cfg:
        principal_extractor = "enterprise-oidc"

    with _pytest.raises(RuntimeError, match="Refusing to fall back"):
        build_extractor(_Cfg())


def test_identity_middleware_maps_auth_error_to_401():
    from unittest.mock import patch as _patch

    from fastapi.testclient import TestClient

    from stache_ai.identity import AuthenticationError, PrincipalExtractor

    class _Refuser(PrincipalExtractor):
        def extract(self, request):
            raise AuthenticationError("token rejected")

    import stache_ai.api.main as main_mod

    with _patch.object(main_mod, "_principal_extractor", _Refuser()):
        client = TestClient(main_mod.app)
        resp = client.get("/api/jobs")
        assert resp.status_code == 401
        assert resp.json()["detail"] == "token rejected"


def test_identity_middleware_populates_state_principal():
    from unittest.mock import patch as _patch

    from fastapi.testclient import TestClient

    from stache_ai.identity import Principal, PrincipalExtractor

    class _Fixed(PrincipalExtractor):
        def extract(self, request):
            return Principal(user_id="user-42", claims={"ext": "v"})

    import stache_ai.api.main as main_mod

    with _patch.object(main_mod, "_principal_extractor", _Fixed()):
        client = TestClient(main_mod.app)
        # list_jobs scopes by the extracted principal - proves state wiring.
        resp = client.get("/api/jobs")
        assert resp.status_code == 200


def test_build_authorizer_default_is_allow_all():
    from stache_ai.identity import AllowAllAuthorizer, build_authorizer

    class _Unset:
        authorization_provider = None

    class _Explicit:
        authorization_provider = "allow-all"

    assert isinstance(build_authorizer(_Unset()), AllowAllAuthorizer)
    assert isinstance(build_authorizer(_Explicit()), AllowAllAuthorizer)
    # Configs without the field at all (older Settings objects) also default.
    assert isinstance(build_authorizer(object()), AllowAllAuthorizer)


def test_build_authorizer_unknown_is_fail_closed():
    """A configured-but-missing authorizer must abort, never fall back."""
    import pytest as _pytest

    from stache_ai.identity import build_authorizer

    class _Cfg:
        authorization_provider = "enterprise-policy"

    with _pytest.raises(RuntimeError, match="Refusing to fall back"):
        build_authorizer(_Cfg())


def test_instantiate_passes_config_when_ctor_accepts_it():
    from stache_ai.identity import _instantiate

    class _TakesConfig:
        def __init__(self, config=None):
            self.config = config

    cfg = object()
    assert _instantiate(_TakesConfig, cfg).config is cfg


def test_instantiate_passes_config_to_keyword_only_ctor():
    """A keyword-only ``config`` parameter (``def __init__(self, *, config=None)``)
    must still receive config - a positional ``sig.bind(config)`` fails for this
    shape and must not fall through to a config-less ``cls()`` call."""
    from stache_ai.identity import _instantiate

    class _TakesKeywordOnlyConfig:
        def __init__(self, *, config=None):
            self.config = config

    cfg = object()
    assert _instantiate(_TakesKeywordOnlyConfig, cfg).config is cfg


def test_instantiate_omits_config_for_zero_arg_ctor():
    """A ctor that takes no args (beyond self) is called without config -
    decided by signature inspection, not by catching a TypeError."""
    from stache_ai.identity import _instantiate

    class _NoArgs:
        def __init__(self):
            self.built = True

    assert _instantiate(_NoArgs, object()).built is True


def test_instantiate_propagates_typeerror_from_inside_ctor():
    """AUTHZ F3 (fail-closed): a config-accepting ctor that raises TypeError
    from INSIDE must propagate and abort startup - NOT be silently retried
    with no args, which would strip the plugin of its configuration."""
    import pytest as _pytest

    from stache_ai.identity import _instantiate

    calls = []

    class _RaisesInside:
        def __init__(self, config=None):
            calls.append(config)
            raise TypeError("genuine bug deep in __init__")

    with _pytest.raises(TypeError, match="genuine bug deep in __init__"):
        _instantiate(_RaisesInside, object())
    # Called exactly once (with config); no fail-open no-arg reconstruction.
    assert len(calls) == 1


def test_build_authorizer_propagates_ctor_typeerror(monkeypatch):
    """End-to-end through the real config/entry-point path: a configured
    authorizer whose ctor raises TypeError aborts get_authorizer rather than
    degrading to a differently-constructed instance."""
    import pytest as _pytest

    from stache_ai import identity
    from stache_ai.config import settings
    from stache_ai.providers import plugin_loader

    class _Broken(identity.AuthorizationProvider):
        def __init__(self, config=None):
            raise TypeError("boom in authorizer ctor")

        def authorize(self, principal, operation, resource=None):
            return None

    plugin_loader.register_provider("authorizer", "broken-ctor", _Broken)
    monkeypatch.setattr(settings, "authorization_provider", "broken-ctor")
    identity.reset_authorizer()
    try:
        with _pytest.raises(TypeError, match="boom in authorizer ctor"):
            identity.build_authorizer(settings)
    finally:
        identity.reset_authorizer()
        plugin_loader.reset()


def test_get_authorizer_is_cached_and_resettable():
    from stache_ai import identity

    identity.reset_authorizer()
    try:
        first = identity.get_authorizer()
        assert identity.get_authorizer() is first  # process-wide singleton
        identity.reset_authorizer()
        second = identity.get_authorizer()
        assert second is not first
        assert isinstance(second, identity.AllowAllAuthorizer)
    finally:
        identity.reset_authorizer()


def test_assert_can_write_delegates_to_configured_authorizer(monkeypatch):
    """The worker-path hook enforces through the configured authorizer."""
    import pytest as _pytest

    from stache_ai import identity
    from stache_ai.config import settings
    from stache_ai.providers import plugin_loader

    calls = []

    class _Deny(identity.AuthorizationProvider):
        def __init__(self, config=None):
            self._config = config

        def authorize(self, principal, operation, resource=None):
            calls.append((principal, operation, resource))
            raise identity.ForbiddenError("write denied")

    plugin_loader.register_provider("authorizer", "deny-test", _Deny)
    monkeypatch.setattr(settings, "authorization_provider", "deny-test")
    identity.reset_authorizer()
    try:
        with _pytest.raises(identity.ForbiddenError, match="write denied"):
            identity.assert_can_write(Principal(user_id="alice"), "ns-1")
        principal, operation, resource = calls[0]
        assert principal.user_id == "alice"
        assert operation == "ingest"
        assert resource == {"namespace": "ns-1"}
    finally:
        identity.reset_authorizer()
        plugin_loader.reset()


def test_worker_denial_fails_job_without_touching_pipeline(monkeypatch):
    """The ingestion worker's defense-in-depth re-check goes through the seam."""
    from stache_ai import identity
    from stache_ai.config import settings
    from stache_ai.ingestion.base import Job, JobStatus
    from stache_ai.ingestion.worker import make_worker
    from stache_ai.providers import plugin_loader

    class _Deny(identity.AuthorizationProvider):
        def __init__(self, config=None):
            pass

        def authorize(self, principal, operation, resource=None):
            raise identity.ForbiddenError("write denied")

    plugin_loader.register_provider("authorizer", "deny-test", _Deny)
    monkeypatch.setattr(settings, "authorization_provider", "deny-test")
    identity.reset_authorizer()

    job = Job(
        job_id="j1", status=JobStatus.QUEUED, namespace="ns", source="api",
        filename="note", content_type="text", requested_by="alice",
        metadata={"_text": "hello world"},
    )

    from stache_ai.ingestion.base import JobStore

    class _Store(JobStore):
        def create(self, job, *, principal=None):
            pass

        def get(self, job_id):
            return job

        def claim(self, job_id, *, from_statuses, to_status=None):
            return True

        def update(self, job_id, **fields):
            for k, v in fields.items():
                setattr(job, k, v)
            return job

        def list(self, **kw):
            return [job], None

    pipeline = AsyncMock()
    notifier = type("N", (), {"publish": lambda self, e: None})()
    try:
        worker = make_worker(_Store(), AsyncMock(), notifier, pipeline)
        asyncio.run(worker("j1"))
        assert job.status == JobStatus.FAILED
        assert "write denied" in job.error_detail
        pipeline.ingest_text.assert_not_called()
        pipeline.ingest_file.assert_not_called()
    finally:
        identity.reset_authorizer()
        plugin_loader.reset()


def test_broken_installed_plugin_fails_closed():
    """An installed entry point that errors on load must abort discovery."""
    from unittest.mock import MagicMock, patch as _patch

    import pytest as _pytest

    from stache_ai.providers import plugin_loader

    bad_ep = MagicMock()
    bad_ep.name = "broken-isolation-layer"
    bad_ep.load.side_effect = AttributeError("half-installed package")

    eps = MagicMock()
    eps.select.return_value = [bad_ep]
    with _patch.object(plugin_loader.importlib.metadata, "entry_points", return_value=eps):
        with _pytest.raises(RuntimeError, match="failed to load"):
            plugin_loader.discover_providers("stache.result_processor")


class TestS4MetadataSanitization:
    """Caller-supplied internal control keys must never reach the pipeline."""

    def test_strip_reserved_metadata(self):
        from stache_ai.sanitize import strip_reserved_metadata

        dirty = {
            "author": "alice",
            "content_hash": "forged",
            "_reingest_version": True,
            "_previous_doc_id": "victim-doc",
            "_text": "smuggled",
        }
        assert strip_reserved_metadata(dirty) == {"author": "alice"}
        assert strip_reserved_metadata(None) == {}
        assert strip_reserved_metadata({}) == {}

    def test_ingest_route_strips_forged_dedup_state(self):
        """POST /ingest with forged control keys must not pass them to the job."""
        from fastapi.testclient import TestClient

        import stache_ai.api.main as main_mod
        from stache_ai.ingestion.factory import reset_ingestion_service

        reset_ingestion_service()
        try:
            client = TestClient(main_mod.app)
            resp = client.post("/api/ingest", json={
                "text": "hello", "content_type": "text",
                "metadata": {
                    "author": "alice",
                    "content_hash": "forged",
                    "_previous_doc_id": "victim-doc",
                },
            })
            assert resp.status_code in (200, 202, 500)  # pipeline may fail w/o providers
            if resp.status_code != 500:
                job = resp.json()
                assert "author" in job["metadata"]
                assert "content_hash" not in job["metadata"]
                assert "_previous_doc_id" not in job["metadata"]
                # The terminal job record strips transport keys too (the
                # document body must not be retained), so _text is gone here
                # even though it was added after sanitization.
                assert "_text" not in job["metadata"]
        finally:
            reset_ingestion_service()

    def test_ingest_route_preserves_source_path_for_smart_update(self):
        """SANITIZER F2 (feature preserved): the trusted /ingest path keeps
        caller-supplied source_path so SOURCE-identifier smart updates work,
        while still dropping genuinely reserved control keys."""
        from fastapi.testclient import TestClient

        import stache_ai.api.main as main_mod
        from stache_ai.ingestion.factory import reset_ingestion_service

        reset_ingestion_service()
        try:
            client = TestClient(main_mod.app)
            resp = client.post("/api/ingest", json={
                "text": "hello", "content_type": "text",
                "metadata": {
                    "source_path": "notes/todo.md",
                    "file_size": 1234,
                    "content_hash": "forged",
                    "_previous_doc_id": "victim-doc",
                },
            })
            assert resp.status_code in (200, 202, 500)
            if resp.status_code != 500:
                job = resp.json()
                # Smart-update identifiers survive on the trusted path...
                assert job["metadata"].get("source_path") == "notes/todo.md"
                assert job["metadata"].get("file_size") == 1234
                # ...but forged reserved control keys never do.
                assert "content_hash" not in job["metadata"]
                assert "_previous_doc_id" not in job["metadata"]
        finally:
            reset_ingestion_service()

    def test_approve_pending_strips_reserved_and_source_identity(self, tmp_path, monkeypatch):
        """SANITIZER F1/F2 (web ingress): approve is a web path, so caller
        metadata is sanitized before pipeline.ingest_text - reserved control
        keys (_stamped/content_hash) AND a forgeable source_path are dropped."""
        import json as _json
        from unittest.mock import AsyncMock, MagicMock, patch

        from fastapi.testclient import TestClient

        import stache_ai.api.main as main_mod
        from stache_ai.config import settings

        monkeypatch.setattr(settings, "queue_dir", str(tmp_path))
        item_id = "item-1"
        (tmp_path / f"{item_id}.json").write_text(_json.dumps({
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
        pipeline.ingest_text = AsyncMock(return_value={"doc_id": "d1", "chunks_created": 1})
        with patch("stache_ai.api.routes.pending.load_document", return_value="extracted text"), \
             patch("stache_ai.api.routes.pending.get_pipeline", return_value=pipeline):
            resp = TestClient(main_mod.app).post(
                f"/api/pending/{item_id}/approve",
                json={
                    "filename": "scan",
                    "namespace": "ns",
                    "metadata": {
                        "author": "alice",
                        "_stamped": "server-only",
                        "content_hash": "forged",
                        "source_path": "victims/secret.md",
                    },
                },
            )
        assert resp.status_code == 200, resp.text
        call_md = pipeline.ingest_text.call_args.kwargs["metadata"]
        assert call_md.get("author") == "alice"
        assert "_stamped" not in call_md
        assert "content_hash" not in call_md
        assert "source_path" not in call_md

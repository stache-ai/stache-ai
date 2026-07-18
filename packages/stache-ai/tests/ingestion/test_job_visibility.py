"""Job visibility + queued-work principal seams on JobStore.

``visible_to`` scopes the single-job fetch (an invisible job reads exactly
like a missing one), and ``principal_for`` reconstructs the acting principal
for the worker's authorization re-check. Deployment-specific stores override
both from attributes they stamped at create time; these tests pin the OSS
defaults and the service/route plumbing around them.
"""

from unittest.mock import MagicMock

from stache_ai.identity import Principal
from stache_ai.ingestion.base import Job, JobStatus
from stache_ai.ingestion.providers.inline import EphemeralJobStore


def _job(job_id="j-1", requested_by="alice"):
    return Job(
        job_id=job_id,
        status=JobStatus.QUEUED,
        namespace="default",
        source="api",
        filename="f.txt",
        content_type="text",
        requested_by=requested_by,
    )


class TestVisibleTo:
    def test_requester_sees_own_job(self):
        store = EphemeralJobStore()
        assert store.visible_to(_job(), Principal(user_id="alice")) is True

    def test_other_user_does_not_see_job(self):
        store = EphemeralJobStore()
        assert store.visible_to(_job(), Principal(user_id="bob")) is False

    def test_no_principal_sees_nothing(self):
        store = EphemeralJobStore()
        assert store.visible_to(_job(), None) is False


class TestPrincipalFor:
    def test_default_rebuilds_id_only_principal(self):
        store = EphemeralJobStore()
        principal = store.principal_for(_job(requested_by="alice"))
        assert principal.user_id == "alice"
        assert principal.claims == {}


class TestServiceGetJobScoping:
    def _service(self, store):
        from stache_ai.ingestion.factory import IngestionService
        service = IngestionService.__new__(IngestionService)
        service.jobstore = store
        return service

    def test_visible_job_returned(self):
        store = EphemeralJobStore()
        job = _job()
        store.create(job)
        service = self._service(store)
        assert service.get_job("j-1", principal=Principal(user_id="alice")) is job

    def test_invisible_job_reads_as_missing(self):
        store = EphemeralJobStore()
        store.create(_job())
        service = self._service(store)
        assert service.get_job("j-1", principal=Principal(user_id="bob")) is None

    def test_no_principal_preserves_unscoped_fetch(self):
        # Internal callers (worker, wait loops) fetch without a principal.
        store = EphemeralJobStore()
        job = _job()
        store.create(job)
        service = self._service(store)
        assert service.get_job("j-1") is job

    def test_store_override_wins(self):
        store = EphemeralJobStore()
        store.create(_job())
        store.visible_to = MagicMock(return_value=False)
        service = self._service(store)
        assert service.get_job("j-1", principal=Principal(user_id="alice")) is None
        store.visible_to.assert_called_once()


class TestWorkerUsesPrincipalFor:
    def test_worker_recheck_uses_store_principal(self, monkeypatch):
        """The worker's S1 re-check must see the store-reconstructed principal
        (claims included), not a bare id-only one it builds itself."""
        import asyncio

        from stache_ai.ingestion import worker as worker_mod

        rehydrated = Principal(user_id="alice", claims={"ext": "opaque"})
        seen = {}

        def fake_assert_can_write(principal, namespace):
            seen["principal"] = principal

        monkeypatch.setattr(worker_mod, "assert_can_write", fake_assert_can_write)

        job = _job()
        job.metadata["_text"] = "hello"
        job.content_type = "text"
        store = EphemeralJobStore()
        store.create(job)
        store.principal_for = MagicMock(return_value=rehydrated)

        pipeline = MagicMock()

        async def fake_ingest_text(**kwargs):
            seen["context"] = kwargs.get("context")
            return {"doc_id": "d-1", "chunks_created": 1}

        pipeline.ingest_text = fake_ingest_text
        notifier = MagicMock()

        process = worker_mod.make_worker(store, MagicMock(), notifier, pipeline)
        asyncio.run(process("j-1"))

        assert seen["principal"] is rehydrated
        store.principal_for.assert_called_once()
        # The same principal travels on the pipeline context's opaque surface.
        assert seen["context"].custom["principal"] is rehydrated

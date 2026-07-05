"""Tests for DynamoJobStore (Phase 2 async ingestion tier) using moto."""

from __future__ import annotations

import types

import boto3
import pytest
from moto import mock_aws

from stache_ai.ingestion.base import Job, JobStatus
from stache_ai_dynamodb.ingest_jobstore import DynamoJobStore

TABLE_NAME = "test-jobs"
REGION = "us-east-1"


def _make_config():
    return types.SimpleNamespace(
        ingest_jobstore_dynamodb_table=TABLE_NAME,
        aws_region=REGION,
    )


def _make_job(
    job_id,
    *,
    status=JobStatus.QUEUED,
    requested_by="alice",
    created_at="2026-06-20T00:00:00+00:00",
    updated_at="2026-06-20T00:00:00+00:00",
    **kwargs,
):
    return Job(
        job_id=job_id,
        status=status,
        namespace=kwargs.pop("namespace", "docs"),
        source=kwargs.pop("source", "cli"),
        filename=kwargs.pop("filename", "f.pdf"),
        content_type=kwargs.pop("content_type", "application/pdf"),
        requested_by=requested_by,
        created_at=created_at,
        updated_at=updated_at,
        **kwargs,
    )


@pytest.fixture
def jobstore():
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        ddb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[{"AttributeName": "job_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "job_id", "AttributeType": "S"},
                {"AttributeName": "GSI1PK", "AttributeType": "S"},
                {"AttributeName": "GSI1SK", "AttributeType": "S"},
                {"AttributeName": "GSI2PK", "AttributeType": "S"},
                {"AttributeName": "GSI2SK", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "GSI1",
                    "KeySchema": [
                        {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "GSI2",
                    "KeySchema": [
                        {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield DynamoJobStore(_make_config())


def test_create_and_get_roundtrip(jobstore):
    job = _make_job("j1", size_bytes=1234, metadata={"a": "b"})
    jobstore.create(job)
    got = jobstore.get("j1")
    assert got is not None
    assert got.job_id == "j1"
    assert got.status == JobStatus.QUEUED
    assert got.size_bytes == 1234
    assert got.metadata == {"a": "b"}
    assert got.requested_by == "alice"


def test_get_missing_returns_none(jobstore):
    assert jobstore.get("nope") is None


def test_update_changes_fields_and_refreshes_gsi2(jobstore):
    jobstore.create(_make_job("j1", status=JobStatus.QUEUED))
    updated = jobstore.update(
        "j1",
        status=JobStatus.DONE,
        doc_id="doc-99",
        chunks_created=7,
        updated_at="2026-06-20T01:00:00+00:00",
    )
    assert updated.status == JobStatus.DONE
    assert updated.doc_id == "doc-99"
    assert updated.chunks_created == 7

    got = jobstore.get("j1")
    assert got.status == JobStatus.DONE
    assert got.doc_id == "doc-99"

    # GSI2 must reflect the new status: querying DONE returns it, QUEUED does not.
    done_jobs, _ = jobstore.list(status=JobStatus.DONE)
    assert [j.job_id for j in done_jobs] == ["j1"]
    queued_jobs, _ = jobstore.list(status=JobStatus.QUEUED)
    assert queued_jobs == []


def test_update_missing_raises_keyerror(jobstore):
    with pytest.raises(KeyError):
        jobstore.update("ghost", status=JobStatus.DONE)


def test_list_by_requested_by_newest_first(jobstore):
    jobstore.create(_make_job("a", requested_by="bob", created_at="2026-06-20T00:00:01+00:00"))
    jobstore.create(_make_job("b", requested_by="bob", created_at="2026-06-20T00:00:03+00:00"))
    jobstore.create(_make_job("c", requested_by="bob", created_at="2026-06-20T00:00:02+00:00"))
    jobstore.create(_make_job("x", requested_by="other", created_at="2026-06-20T00:00:09+00:00"))

    jobs, cursor = jobstore.list(requested_by="bob")
    assert [j.job_id for j in jobs] == ["b", "c", "a"]
    assert cursor is None


def test_list_by_status(jobstore):
    jobstore.create(_make_job("a", status=JobStatus.QUEUED, updated_at="2026-06-20T00:00:01+00:00"))
    jobstore.create(_make_job("b", status=JobStatus.PROCESSING, updated_at="2026-06-20T00:00:02+00:00"))
    jobstore.create(_make_job("c", status=JobStatus.QUEUED, updated_at="2026-06-20T00:00:03+00:00"))

    jobs, _ = jobstore.list(status=JobStatus.QUEUED)
    assert {j.job_id for j in jobs} == {"a", "c"}
    # newest-first by updated_at (GSI2SK)
    assert [j.job_id for j in jobs] == ["c", "a"]


def test_list_with_both_requested_by_and_status(jobstore):
    jobstore.create(_make_job("a", requested_by="bob", status=JobStatus.QUEUED))
    jobstore.create(_make_job("b", requested_by="bob", status=JobStatus.DONE))
    jobstore.create(_make_job("c", requested_by="other", status=JobStatus.QUEUED))

    jobs, _ = jobstore.list(requested_by="bob", status=JobStatus.QUEUED)
    assert [j.job_id for j in jobs] == ["a"]


def test_pagination_cursor_roundtrip(jobstore):
    for i in range(5):
        jobstore.create(
            _make_job(
                f"j{i}",
                requested_by="bob",
                created_at=f"2026-06-20T00:00:0{i}+00:00",
            )
        )

    page1, cursor = jobstore.list(requested_by="bob", limit=2)
    assert len(page1) == 2
    assert cursor is not None

    page2, cursor2 = jobstore.list(requested_by="bob", limit=2, cursor=cursor)
    assert len(page2) == 2
    assert cursor2 is not None

    page3, cursor3 = jobstore.list(requested_by="bob", limit=2, cursor=cursor2)
    assert len(page3) == 1

    seen = {j.job_id for j in page1 + page2 + page3}
    assert seen == {"j0", "j1", "j2", "j3", "j4"}


def test_list_stuck_returns_only_active_past_cutoff(jobstore):
    cutoff = "2026-06-20T12:00:00+00:00"
    # Stuck: active status, updated before cutoff
    jobstore.create(_make_job("stuck-q", status=JobStatus.QUEUED, updated_at="2026-06-20T10:00:00+00:00"))
    jobstore.create(_make_job("stuck-p", status=JobStatus.PROCESSING, updated_at="2026-06-20T11:00:00+00:00"))
    # Fresh: active but updated after cutoff
    jobstore.create(_make_job("fresh", status=JobStatus.PROCESSING, updated_at="2026-06-20T13:00:00+00:00"))
    # Terminal: should never be reaped even though old
    jobstore.create(_make_job("done", status=JobStatus.DONE, updated_at="2026-06-20T09:00:00+00:00"))

    stuck = jobstore.list_stuck(cutoff)
    assert {j.job_id for j in stuck} == {"stuck-q", "stuck-p"}


def test_roundtrip_is_json_serializable(jobstore):
    """DynamoDB deserializes numbers as Decimal; the store must convert back.

    Regression: JSONResponse(job.to_dict()) in POST /ingest 500'd with
    'Object of type Decimal is not JSON serializable' on the deployed stack.
    """
    import json as _json

    jobstore.create(_make_job(
        "j-dec", size_bytes=4096, chunks_created=3,
        metadata={"pages": 12, "ratio": 0.5, "nested": {"n": 7}, "tags": [1, 2]},
    ))

    job = jobstore.get("j-dec")
    _json.dumps(job.to_dict())  # must not raise
    assert type(job.size_bytes) is int
    assert type(job.chunks_created) is int
    assert type(job.metadata["pages"]) is int
    assert type(job.metadata["ratio"]) is float
    assert type(job.metadata["nested"]["n"]) is int
    assert all(type(v) is int for v in job.metadata["tags"])

    # update() round-trips through get(); listing paths must convert too.
    updated = jobstore.update("j-dec", chunks_created=5)
    _json.dumps(updated.to_dict())
    listed, _ = jobstore.list(requested_by="alice")
    for j in listed:
        _json.dumps(j.to_dict())

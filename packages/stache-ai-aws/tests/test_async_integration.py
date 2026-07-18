"""End-to-end async-tier integration: real S3/SQS/DynamoDB providers via entry
points, mocked with moto.
"""

import asyncio
import json
import types
from unittest.mock import AsyncMock

import boto3
from moto import mock_aws

from stache_ai.ingestion.base import JobStatus
from stache_ai.ingestion.factory import IngestionServiceFactory, reset_ingestion_service
import stache_ai.ingestion.factory as factory_mod

from stache_ai_aws import sqs_worker

REGION = "us-east-1"
JOBS_TABLE = "it-ingest-jobs"
BUCKET = "it-originals"
QUEUE = "it-ingest-queue"


def _provision():
    """Create the table, bucket, and queue in moto; return the queue URL."""
    ddb = boto3.client("dynamodb", region_name=REGION)
    ddb.create_table(
        TableName=JOBS_TABLE,
        BillingMode="PAY_PER_REQUEST",
        KeySchema=[{"AttributeName": "job_id", "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": "job_id", "AttributeType": "S"},
            {"AttributeName": "GSI1PK", "AttributeType": "S"},
            {"AttributeName": "GSI1SK", "AttributeType": "S"},
            {"AttributeName": "GSI2PK", "AttributeType": "S"},
            {"AttributeName": "GSI2SK", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {"IndexName": "GSI1",
             "KeySchema": [{"AttributeName": "GSI1PK", "KeyType": "HASH"},
                           {"AttributeName": "GSI1SK", "KeyType": "RANGE"}],
             "Projection": {"ProjectionType": "ALL"}},
            {"IndexName": "GSI2",
             "KeySchema": [{"AttributeName": "GSI2PK", "KeyType": "HASH"},
                           {"AttributeName": "GSI2SK", "KeyType": "RANGE"}],
             "Projection": {"ProjectionType": "ALL"}},
        ],
    )
    boto3.client("s3", region_name=REGION).create_bucket(Bucket=BUCKET)
    return boto3.client("sqs", region_name=REGION).create_queue(QueueName=QUEUE)["QueueUrl"]


def _config(queue_url):
    """Factory + provider config. AWS keys live on this injected config (the
    providers' env-backed settings are the production path)."""
    return types.SimpleNamespace(
        ingest_queue_provider="sqs",
        ingest_jobstore_provider="dynamodb",
        ingest_blob_provider="s3",
        ingest_intake_provider="inline",
        ingest_notifier_provider="null",
        ingest_queue_sqs_url=queue_url,
        ingest_jobstore_dynamodb_table=JOBS_TABLE,
        ingest_blob_s3_bucket=BUCKET,
        ingest_blob_s3_prefix="originals",
        aws_region=REGION,
    )


def _pipeline():
    p = AsyncMock()
    p.ingest_text.return_value = {"doc_id": "doc-async", "action": "ingested_new", "chunks_created": 4}
    p.ingest_file.return_value = {"doc_id": "doc-file", "chunks_created": 8}
    return p


def _drive(service, body):
    """Feed one SQS record to the worker Lambda against a pre-wired service."""
    factory_mod._service = service           # make get_ingestion_service() return our wired service
    try:
        return sqs_worker.lambda_handler(
            {"Records": [{"messageId": "m1", "body": body}]}, None
        )
    finally:
        reset_ingestion_service()


@mock_aws
def test_async_submit_is_queued_then_worker_completes(monkeypatch):
    monkeypatch.setenv("INGEST_BLOB_S3_PREFIX", "originals")
    queue_url = _provision()
    pipeline = _pipeline()
    service = IngestionServiceFactory.build(_config(queue_url), pipeline)

    # Providers resolved via real entry points.
    from stache_ai_aws.blob import S3BlobStore
    from stache_ai_aws.queue import SqsQueue
    from stache_ai_dynamodb.ingest_jobstore import DynamoJobStore
    assert isinstance(service.blobstore, S3BlobStore)
    assert isinstance(service.queue, SqsQueue)
    assert isinstance(service.jobstore, DynamoJobStore)

    # Submit text -> NOT born terminal in the async tier: job persists as QUEUED,
    # and a message lands on SQS (worker runs out-of-band).
    job = asyncio.run(service.submit(
        namespace="default", content_type="text", requested_by="alice", text="hello async",
    ))
    assert job.status == JobStatus.QUEUED
    assert pipeline.ingest_text.await_count == 0      # worker hasn't run yet

    sqs = boto3.client("sqs", region_name=REGION)
    msgs = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=1).get("Messages", [])
    assert len(msgs) == 1 and msgs[0]["Body"] == job.job_id

    resp = _drive(service, job.job_id)

    assert resp == {"batchItemFailures": []}
    done = service.get_job(job.job_id)
    assert done.status == JobStatus.DONE
    assert done.doc_id == "doc-async"
    assert done.chunks_created == 4


@mock_aws
def test_async_file_round_trips_through_s3(monkeypatch):
    monkeypatch.setenv("INGEST_BLOB_S3_PREFIX", "originals")
    queue_url = _provision()
    pipeline = _pipeline()
    service = IngestionServiceFactory.build(_config(queue_url), pipeline)

    job = asyncio.run(service.submit(
        namespace="default", content_type="application/pdf", requested_by="bob",
        filename="r.pdf", data=b"%PDF-1.4 bytes",
    ))
    assert job.status == JobStatus.QUEUED
    assert job.blob_key  # stored to S3

    _drive(service, job.job_id)

    done = service.get_job(job.job_id)
    assert done.status == JobStatus.DONE
    assert done.doc_id == "doc-file"
    # The worker read the original back out of S3 and handed a real path to ingest_file.
    assert pipeline.ingest_file.await_count == 1


@mock_aws
def test_producer_s3_drop_path(monkeypatch):
    """An object dropped under the originals prefix (producer path) is ingested
    via an S3-event SQS record."""
    monkeypatch.setenv("INGEST_BLOB_S3_PREFIX", "originals")
    import stache_ai.config as cfg
    from stache_ai.config import Settings
    monkeypatch.setattr(cfg, "settings", Settings(ingest_producer_drops_enabled=True))
    queue_url = _provision()
    pipeline = _pipeline()
    service = IngestionServiceFactory.build(_config(queue_url), pipeline)

    # Producer writes the original directly to S3 with pinned stache-* metadata.
    boto3.client("s3", region_name=REGION).put_object(
        Bucket=BUCKET, Key="originals/feed/article.txt", Body=b"producer content",
        Metadata={"stache-namespace": "news", "stache-filename": "article.txt",
                  "stache-requested_by": "media-pipeline", "stache-content_type": "text"},
    )
    s3_event = {
        "Records": [{
            "eventSource": "aws:s3",
            "s3": {"object": {"key": "originals/feed/article.txt"}},
        }]
    }
    resp = _drive(service, json.dumps(s3_event))

    assert resp == {"batchItemFailures": []}
    # A producer job was created and completed.
    jobs, _ = service.list_jobs(limit=50)
    assert len(jobs) == 1
    assert jobs[0].source == "producer"
    assert jobs[0].status in (JobStatus.DONE, JobStatus.SKIPPED)

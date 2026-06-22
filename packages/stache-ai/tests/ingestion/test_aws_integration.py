"""End-to-end async-tier integration: real S3/SQS/DynamoDB providers via entry
points, mocked with moto. Skips unless stache-ai-aws + stache-ai-dynamodb are
installed (entry points discoverable).
"""

import asyncio

import pytest

from stache_ai.providers import plugin_loader

_HAVE_AWS = (
    "s3" in plugin_loader.get_available_providers("ingest_blob")
    and "sqs" in plugin_loader.get_available_providers("ingest_queue")
    and "dynamodb" in plugin_loader.get_available_providers("ingest_jobstore")
)

pytestmark = pytest.mark.skipif(
    not _HAVE_AWS, reason="stache-ai-aws / stache-ai-dynamodb not installed"
)

moto = pytest.importorskip("moto")
boto3 = pytest.importorskip("boto3")
from moto import mock_aws  # noqa: E402

from unittest.mock import AsyncMock  # noqa: E402

from stache_ai.config import Settings  # noqa: E402
from stache_ai.ingestion.base import JobStatus  # noqa: E402
from stache_ai.ingestion.factory import IngestionServiceFactory  # noqa: E402

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


def _settings(queue_url):
    return Settings(
        ingest_queue_provider="sqs",
        ingest_jobstore_provider="dynamodb",
        ingest_blob_provider="s3",
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


@mock_aws
def test_async_submit_is_queued_then_worker_completes():
    queue_url = _provision()
    pipeline = _pipeline()
    service = IngestionServiceFactory.build(_settings(queue_url), pipeline)

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

    # Drive the worker Lambda with that SQS record.
    from stache_ai.ingestion import sqs_worker
    from stache_ai.ingestion.factory import reset_ingestion_service
    import stache_ai.ingestion.factory as factory_mod
    factory_mod._service = service           # make get_ingestion_service() return our wired service
    try:
        resp = sqs_worker.lambda_handler({"Records": [{"messageId": "m1", "body": job.job_id}]}, None)
    finally:
        reset_ingestion_service()

    assert resp == {"batchItemFailures": []}
    done = service.get_job(job.job_id)
    assert done.status == JobStatus.DONE
    assert done.doc_id == "doc-async"
    assert done.chunks_created == 4


@mock_aws
def test_async_file_round_trips_through_s3():
    queue_url = _provision()
    pipeline = _pipeline()
    service = IngestionServiceFactory.build(_settings(queue_url), pipeline)

    job = asyncio.run(service.submit(
        namespace="default", content_type="application/pdf", requested_by="bob",
        filename="r.pdf", data=b"%PDF-1.4 bytes",
    ))
    assert job.status == JobStatus.QUEUED
    assert job.blob_key  # stored to S3

    from stache_ai.ingestion import sqs_worker
    from stache_ai.ingestion.factory import reset_ingestion_service
    import stache_ai.ingestion.factory as factory_mod
    factory_mod._service = service
    try:
        sqs_worker.lambda_handler({"Records": [{"messageId": "m1", "body": job.job_id}]}, None)
    finally:
        reset_ingestion_service()

    done = service.get_job(job.job_id)
    assert done.status == JobStatus.DONE
    assert done.doc_id == "doc-file"
    # The worker read the original back out of S3 and handed a real path to ingest_file.
    assert pipeline.ingest_file.await_count == 1


@mock_aws
def test_producer_s3_drop_path():
    """An object dropped under the originals prefix (producer path) is ingested
    via an S3-event SQS record."""
    queue_url = _provision()
    pipeline = _pipeline()
    service = IngestionServiceFactory.build(_settings(queue_url), pipeline)

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
    import json
    from stache_ai.ingestion import sqs_worker
    from stache_ai.ingestion.factory import reset_ingestion_service
    import stache_ai.ingestion.factory as factory_mod
    factory_mod._service = service
    try:
        resp = sqs_worker.lambda_handler(
            {"Records": [{"messageId": "m1", "body": json.dumps(s3_event)}]}, None)
    finally:
        reset_ingestion_service()

    assert resp == {"batchItemFailures": []}
    # A producer job was created and completed.
    jobs, _ = service.list_jobs(limit=50)
    assert len(jobs) == 1
    assert jobs[0].source == "producer"
    assert jobs[0].status in (JobStatus.DONE, JobStatus.SKIPPED)

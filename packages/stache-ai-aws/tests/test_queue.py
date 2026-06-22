import asyncio
import types

import boto3
from moto import mock_aws

from stache_ai_aws.queue import SqsQueue


@mock_aws
def test_enqueue_sends_one_message():
    region = "us-east-1"
    sqs = boto3.client("sqs", region_name=region)
    queue_url = sqs.create_queue(QueueName="ingest-queue")["QueueUrl"]

    cfg = types.SimpleNamespace(
        ingest_queue_sqs_url=queue_url,
        aws_region=region,
    )

    asyncio.run(SqsQueue(cfg).enqueue("job-123"))

    resp = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10)
    messages = resp.get("Messages", [])
    assert len(messages) == 1
    assert messages[0]["Body"] == "job-123"

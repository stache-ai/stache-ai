"""SQS-backed QueueProvider for non-blocking ingestion submit."""

from __future__ import annotations

import boto3

from stache_ai.ingestion.base import QueueProvider

from .settings import resolve


class SqsQueue(QueueProvider):
    def __init__(self, config):
        self._url = resolve(config, "ingest_queue_sqs_url")
        self._sqs = boto3.client("sqs", region_name=config.aws_region)

    async def enqueue(self, job_id: str) -> None:
        # Non-blocking submit: hand off to SQS; the worker Lambda runs the pipeline.
        self._sqs.send_message(QueueUrl=self._url, MessageBody=job_id)

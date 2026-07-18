"""DynamoDB-backed JobStore for the async ingestion tier (Phase 2).

Implements the Phase 1 ``JobStore`` seam against a single DynamoDB table with
two GSIs:

- GSI1 (``GSI1PK`` = ``requested_by``, ``GSI1SK`` = ``created_at``): owner listing.
- GSI2 (``GSI2PK`` = ``status``,       ``GSI2SK`` = ``updated_at``): status listing
  and the reaper's "stuck jobs" scan.

Serialization reuses ``Job.to_dict()`` / ``Job.from_dict()`` from Phase 1.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from stache_ai.ingestion.base import (
    IngestTextTooLargeError,
    Job,
    JobStatus,
    JobStore,
)

logger = logging.getLogger(__name__)


def _todecimal(value):
    """Inverse of _undecimal for writes: DynamoDB rejects Python floats."""
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _todecimal(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_todecimal(v) for v in value]
    return value


def _undecimal(value):
    """Convert boto3's Decimal deserialization back to int/float.

    DynamoDB numbers come back as Decimal, which is not JSON serializable and
    breaks ``JSONResponse(job.to_dict())`` in the API routes. Applied to every
    item read so Job fields and nested metadata stay plain Python numbers.
    """
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    if isinstance(value, dict):
        return {k: _undecimal(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_undecimal(v) for v in value]
    return value


class DynamoJobStore(JobStore):
    """Persistent JobStore backed by DynamoDB."""

    # DynamoDB caps a single item at 400KB total (attribute names + values).
    # Reserve headroom for the other Job fields and DynamoDB's attribute-name
    # overhead so an inline ``_text`` payload cannot push the item over the wire
    # limit; submit enforces this and returns 413 before the write is attempted.
    max_inline_payload_bytes = 350_000

    def __init__(self, config):
        # The table name lives in this package's env config, not core settings;
        # an attribute on the injected config (tests) takes precedence.
        self._table_name = (
            getattr(config, "ingest_jobstore_dynamodb_table", None)
            or os.environ.get("INGEST_JOBSTORE_DYNAMODB_TABLE", "")
        )
        self._ddb = boto3.resource("dynamodb", region_name=config.aws_region)
        self._table = self._ddb.Table(self._table_name)

    def create(self, job: Job, *, principal=None) -> None:
        # Strip None / empty-string values: DynamoDB rejects empty strings and
        # there is no reason to persist absent optional fields.
        item = _todecimal(
            {k: v for k, v in job.to_dict().items() if v is not None and v != ""})
        item["GSI1PK"] = job.requested_by or "anonymous"
        item["GSI1SK"] = job.created_at
        item["GSI2PK"] = job.status.value
        item["GSI2SK"] = job.updated_at
        try:
            self._table.put_item(Item=item)
        except ClientError as e:
            # An oversize item (chiefly an inline _text past the 400KB cap)
            # surfaces as ValidationException; remap it to 413 rather than a 500.
            # submit's cap normally rejects this earlier, so this is belt-and-braces.
            if e.response["Error"]["Code"] == "ValidationException":
                raise IngestTextTooLargeError(
                    "job payload exceeds the DynamoDB 400KB item limit"
                ) from e
            raise

    def update(self, job_id: str, **fields) -> Job:
        job = self.get(job_id)
        if job is None:
            raise KeyError(job_id)
        for k, v in fields.items():
            setattr(job, k, v)
        # Idempotent overwrite that refreshes the GSI sort/partition keys.
        self.create(job)
        return job

    def claim(self, job_id: str, *, from_statuses, to_status=None) -> bool:
        """Atomic compare-and-swap claim (overrides the non-atomic base impl).

        A single conditional ``update_item`` flips status (and the GSI2 partition
        key that mirrors it) only if the stored status is still one of
        ``from_statuses``. DynamoDB serializes the condition check with the write,
        so exactly one concurrent consumer wins; the rest get
        ConditionalCheckFailed and return False. This is what makes duplicate SQS
        delivery and the enqueue/S3-event double-trigger safe.
        """
        from datetime import datetime, timezone

        from botocore.exceptions import ClientError

        to_status = to_status or JobStatus.PROCESSING
        now = datetime.now(timezone.utc).isoformat()
        placeholders = {f":from{i}": s.value for i, s in enumerate(from_statuses)}
        try:
            self._table.update_item(
                Key={"job_id": job_id},
                UpdateExpression="SET #s = :to, GSI2PK = :to, GSI2SK = :now, updated_at = :now",
                ConditionExpression=(
                    "attribute_exists(job_id) AND #s IN (" + ", ".join(placeholders) + ")"
                ),
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":to": to_status.value, ":now": now, **placeholders},
            )
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def get(self, job_id: str) -> Job | None:
        resp = self._table.get_item(Key={"job_id": job_id})
        item = resp.get("Item")
        # Stored item carries extra GSI* keys; Job.from_dict ignores unknowns.
        return Job.from_dict(_undecimal(item)) if item else None

    @staticmethod
    def _decode_cursor(cursor):
        # Cursors are opaque, ephemeral, and URL-safe base64 (see _page). A
        # corrupt/garbage cursor must be a client error (400), not a 500, so
        # normalize any decode failure to ValueError for the route to map.
        try:
            return json.loads(base64.urlsafe_b64decode(cursor))
        except Exception as e:
            raise ValueError("invalid cursor") from e

    def list(self, *, requested_by=None, status=None, limit=50, cursor=None,
             principal=None):
        kwargs = {"Limit": limit, "ScanIndexForward": False}
        if cursor:
            kwargs["ExclusiveStartKey"] = self._decode_cursor(cursor)
        if requested_by is not None:
            kwargs.update(
                IndexName="GSI1",
                KeyConditionExpression=Key("GSI1PK").eq(requested_by),
            )
        elif status is not None:
            kwargs.update(
                IndexName="GSI2",
                KeyConditionExpression=Key("GSI2PK").eq(status.value),
            )
        else:
            scan_kwargs = {"Limit": limit}
            if cursor:
                scan_kwargs["ExclusiveStartKey"] = self._decode_cursor(cursor)
            resp = self._table.scan(**scan_kwargs)
            return self._page(resp)
        resp = self._table.query(**kwargs)
        jobs, nxt = self._page(resp)
        # When both filters are given we index by owner, then filter status
        # client-side within the page.
        if requested_by is not None and status is not None:
            jobs = [j for j in jobs if j.status == status]
        return jobs, nxt

    def list_stuck(self, older_than_iso: str) -> list[Job]:
        out: list[Job] = []
        for st in (JobStatus.QUEUED, JobStatus.UPLOADING, JobStatus.PROCESSING):
            resp = self._table.query(
                IndexName="GSI2",
                KeyConditionExpression=Key("GSI2PK").eq(st.value)
                & Key("GSI2SK").lt(older_than_iso),
            )
            out += [Job.from_dict(_undecimal(i)) for i in resp.get("Items", [])]
        return out

    def _page(self, resp):
        jobs = [Job.from_dict(_undecimal(i)) for i in resp.get("Items", [])]
        lek = resp.get("LastEvaluatedKey")
        # URL-safe base64: a standard-base64 "+" arrives as a space from clients
        # that don't percent-encode the cursor, silently corrupting the decode.
        cur = base64.urlsafe_b64encode(json.dumps(_undecimal(lek)).encode()).decode() if lek else None
        return jobs, cur

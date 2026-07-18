"""S3-backed BlobStore for retained ingestion originals."""

from __future__ import annotations

import boto3

from stache_ai.ingestion.base import BlobStore

from .settings import resolve


class S3BlobStore(BlobStore):
    def __init__(self, config):
        self._bucket = resolve(config, "ingest_blob_s3_bucket")
        self._prefix = (resolve(config, "ingest_blob_s3_prefix") or "").strip("/")
        self._s3 = boto3.client("s3", region_name=config.aws_region)

    def _full(self, key: str) -> str:
        return f"{self._prefix}/{key}" if self._prefix else key

    def put(self, key: str, data: bytes, metadata: dict) -> str:
        meta = {
            f"stache-{k}": str(v)
            for k, v in (metadata or {}).items()
            if v is not None
        }
        self._s3.put_object(
            Bucket=self._bucket, Key=self._full(key), Body=data, Metadata=meta
        )
        return key  # store the logical key in the Job

    def get(self, key: str) -> tuple[bytes, dict]:
        obj = self._s3.get_object(Bucket=self._bucket, Key=self._full(key))
        body = obj["Body"].read()  # StreamingBody: read once (CLAUDE.md lesson #4)
        meta = {
            k.replace("stache-", "", 1): v
            for k, v in obj.get("Metadata", {}).items()
        }
        return body, meta

    def head(self, key: str) -> dict:
        """Return blob metadata only, without downloading the body."""
        obj = self._s3.head_object(Bucket=self._bucket, Key=self._full(key))
        return {
            k.replace("stache-", "", 1): v
            for k, v in obj.get("Metadata", {}).items()
        }

    def presign_put(self, key: str, *, headers: dict, expiry: int) -> str:
        return self._s3.generate_presigned_url(
            "put_object",
            Params={"Bucket": self._bucket, "Key": self._full(key), **headers},
            ExpiresIn=expiry,
        )

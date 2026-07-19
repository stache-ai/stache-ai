"""S3-backed BlobStore for retained ingestion originals."""

from __future__ import annotations

from typing import Optional
from urllib.parse import quote

import boto3

from stache_ai.ingestion.base import BlobStore

from .settings import resolve


def _content_disposition(filename: str) -> str:
    """Build a safe ``Content-Disposition: attachment`` header value.

    A stored filename is attacker-influenced. Interpolated raw into
    ``filename="..."`` a double-quote/backslash can break out of the quoted
    string and a CR/LF can inject header lines or spoof the save-as name;
    non-ASCII bytes make the header invalid. We strip those from the quoted
    ASCII ``filename`` and, when the original has non-ASCII, additionally emit an
    RFC 5987 ``filename*=UTF-8''<pct-encoded>`` so capable clients still get the
    real (e.g. accented) name.
    """
    ascii_name = "".join(
        ch for ch in filename
        if " " <= ch and ord(ch) < 0x7F and ch not in '"\\'
    ) or "download"
    disposition = f'attachment; filename="{ascii_name}"'
    if any(ord(ch) > 0x7F for ch in filename):
        disposition += f"; filename*=UTF-8''{quote(filename, safe='')}"
    return disposition


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

    def presign_get(self, key: str, *, expiry: int,
                    download_filename: Optional[str] = None) -> str:
        params = {"Bucket": self._bucket, "Key": self._full(key)}
        if download_filename:
            params["ResponseContentDisposition"] = _content_disposition(
                download_filename)
        return self._s3.generate_presigned_url(
            "get_object", Params=params, ExpiresIn=expiry,
        )

    @property
    def capabilities(self) -> set[str]:
        # "presign_download": presign_get returns a usable download URL.
        # "blob_read": durably stores and serves bytes (get() returns what put()
        # wrote) -- the extracted-text persistence is gated on this so the null
        # tier, which retains nothing, is never recorded as a text_blob_key.
        return {"presign_download", "blob_read"}

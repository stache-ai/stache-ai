import types
from unittest.mock import MagicMock

import boto3
import pytest
from moto import mock_aws

from stache_ai_aws.blob import S3BlobStore, _content_disposition


def _config():
    return types.SimpleNamespace(
        ingest_blob_s3_bucket="test-bucket",
        ingest_blob_s3_prefix="originals",
        aws_region="us-east-1",
    )


@mock_aws
def test_put_get_roundtrip_and_metadata_mapping():
    cfg = _config()
    boto3.client("s3", region_name=cfg.aws_region).create_bucket(Bucket=cfg.ingest_blob_s3_bucket)

    store = S3BlobStore(cfg)
    logical_key = store.put(
        "abc/file.txt",
        b"hello world",
        {"namespace": "docs", "requested_by": "alice", "skip": None},
    )

    # put returns the LOGICAL key, not the prefixed one
    assert logical_key == "abc/file.txt"

    body, meta = store.get("abc/file.txt")
    assert body == b"hello world"
    # metadata round-trips with the stache- prefix stripped, None values skipped
    assert meta == {"namespace": "docs", "requested_by": "alice"}
    assert all(not k.startswith("stache-") for k in meta)


@mock_aws
def test_object_stored_under_prefix():
    cfg = _config()
    s3 = boto3.client("s3", region_name=cfg.aws_region)
    s3.create_bucket(Bucket=cfg.ingest_blob_s3_bucket)

    store = S3BlobStore(cfg)
    store.put("abc/file.txt", b"data", {})

    # object lives at originals/abc/file.txt
    obj = s3.get_object(Bucket=cfg.ingest_blob_s3_bucket, Key="originals/abc/file.txt")
    assert obj["Body"].read() == b"data"


@mock_aws
def test_head_returns_metadata_without_error():
    cfg = _config()
    boto3.client("s3", region_name=cfg.aws_region).create_bucket(Bucket=cfg.ingest_blob_s3_bucket)

    store = S3BlobStore(cfg)
    store.put("abc/file.txt", b"data", {"namespace": "docs"})

    meta = store.head("abc/file.txt")
    assert meta == {"namespace": "docs"}


@mock_aws
def test_no_prefix():
    cfg = _config()
    cfg.ingest_blob_s3_prefix = ""
    s3 = boto3.client("s3", region_name=cfg.aws_region)
    s3.create_bucket(Bucket=cfg.ingest_blob_s3_bucket)

    store = S3BlobStore(cfg)
    store.put("abc/file.txt", b"data", {})

    obj = s3.get_object(Bucket=cfg.ingest_blob_s3_bucket, Key="abc/file.txt")
    assert obj["Body"].read() == b"data"


@mock_aws
def test_presign_put_returns_url_with_bucket():
    cfg = _config()
    boto3.client("s3", region_name=cfg.aws_region).create_bucket(Bucket=cfg.ingest_blob_s3_bucket)

    store = S3BlobStore(cfg)
    url = store.presign_put(
        "abc/file.txt",
        headers={"ContentType": "text/plain"},
        expiry=3600,
    )
    assert isinstance(url, str)
    assert cfg.ingest_blob_s3_bucket in url


@mock_aws
def test_presign_put_drops_none_metadata_value():
    """A None-valued metadata entry must never reach botocore.

    SigV4 metadata validation calls ``value.encode("ascii")``; a None value
    (e.g. an unresolved namespace) raises AttributeError -> HTTP 500 at upload
    time. presign_put drops any None-valued key before signing.
    """
    cfg = _config()
    boto3.client("s3", region_name=cfg.aws_region).create_bucket(Bucket=cfg.ingest_blob_s3_bucket)

    store = S3BlobStore(cfg)
    # Spy on the boto client so we can inspect exactly what it was handed.
    store._s3 = MagicMock()
    store._s3.generate_presigned_url.return_value = "https://signed.example/put"

    store.presign_put(
        "abc/file.txt",
        headers={
            "ContentType": "text/plain",
            "Metadata": {
                "stache-namespace": None,       # the unresolved namespace
                "stache-requested_by": "alice",
                "stache-filename": "doc.txt",
            },
        },
        expiry=3600,
    )

    params = store._s3.generate_presigned_url.call_args.kwargs["Params"]
    meta = params["Metadata"]
    # The None entry is gone; no None values reach botocore at all.
    assert "stache-namespace" not in meta
    assert None not in meta.values()
    assert meta == {"stache-requested_by": "alice", "stache-filename": "doc.txt"}


@mock_aws
def test_presign_put_preserves_metadata_without_none():
    """Metadata with no None values is passed through unchanged."""
    cfg = _config()
    boto3.client("s3", region_name=cfg.aws_region).create_bucket(Bucket=cfg.ingest_blob_s3_bucket)

    store = S3BlobStore(cfg)
    store._s3 = MagicMock()
    store._s3.generate_presigned_url.return_value = "https://signed.example/put"

    store.presign_put(
        "abc/file.txt",
        headers={"ContentType": "text/plain", "Metadata": {"stache-namespace": "docs"}},
        expiry=3600,
    )

    params = store._s3.generate_presigned_url.call_args.kwargs["Params"]
    assert params["Metadata"] == {"stache-namespace": "docs"}


@mock_aws
def test_presign_get_returns_url_and_advertises_capability():
    cfg = _config()
    boto3.client("s3", region_name=cfg.aws_region).create_bucket(Bucket=cfg.ingest_blob_s3_bucket)

    store = S3BlobStore(cfg)
    assert "presign_download" in store.capabilities

    url = store.presign_get("abc/file.txt", expiry=300)
    assert isinstance(url, str)
    assert cfg.ingest_blob_s3_bucket in url
    # Signs against the prefixed key.
    assert "originals/abc/file.txt" in url


def test_content_disposition_strips_embedded_quote():
    # A stored filename with a double-quote must not produce an unescaped quote
    # in the header value: it could break out of filename="..." and spoof the
    # browser's save-as name. The only quotes left are the two delimiters.
    header = _content_disposition('pwned".exe')
    assert header == 'attachment; filename="pwned.exe"'
    assert header.count('"') == 2


def test_content_disposition_strips_crlf_and_backslash():
    header = _content_disposition("a\r\nb\\c.pdf")
    assert "\r" not in header and "\n" not in header
    assert "\\" not in header


def test_content_disposition_non_ascii_emits_rfc5987():
    header = _content_disposition("résumé.pdf")
    # ASCII-folded quoted name for legacy clients ...
    assert 'filename="rsum.pdf"' in header
    # ... plus an RFC 5987 param carrying the real UTF-8 bytes for capable ones.
    assert "filename*=UTF-8''r%C3%A9sum%C3%A9.pdf" in header


@mock_aws
def test_presign_get_sets_content_disposition_filename():
    cfg = _config()
    boto3.client("s3", region_name=cfg.aws_region).create_bucket(Bucket=cfg.ingest_blob_s3_bucket)

    store = S3BlobStore(cfg)
    url = store.presign_get("abc/file.txt", expiry=300, download_filename="Report Q3.pdf")
    # ResponseContentDisposition is signed into the query string (URL-encoded).
    assert "response-content-disposition" in url.lower()
    assert "attachment" in url.lower()

import types

import boto3
import pytest
from moto import mock_aws

from stache_ai_aws.blob import S3BlobStore


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

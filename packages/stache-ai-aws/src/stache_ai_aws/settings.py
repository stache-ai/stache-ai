"""Env-backed configuration for the AWS async ingestion tier.

These keys live in this package, not in stache-ai core, so core carries no
AWS-specific configuration. Resolution order: an attribute on the injected
config object wins (tests and embedders pass explicit configs); otherwise the
value comes from the environment / ``.env``.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings


class AwsIngestSettings(BaseSettings):
    ingest_blob_s3_bucket: str = ""          # S3 bucket for retained originals
    ingest_blob_s3_prefix: str = "originals"  # Key prefix within the originals bucket
    ingest_queue_sqs_url: str = ""            # SQS queue URL for ingestion jobs
    # Presigned upload URL expiry (seconds). MUST stay below
    # INGEST_REAPER_STUCK_MINUTES*60 (default 30*60=1800): a client that uploads
    # after the reaper has already failed the UPLOADING job would otherwise be
    # silently dropped. Default 1500s (25 min) keeps that margin.
    ingest_intake_s3_presign_expiry: int = 1500

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"


def resolve(config, name: str):
    """Read ``name`` from the injected config if present, else from the env."""
    val = getattr(config, name, None)
    return val if val is not None else getattr(AwsIngestSettings(), name)

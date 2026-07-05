"""S3 presigned-PUT IntakeProvider (client-side upload flow)."""

from __future__ import annotations

from stache_ai.ingestion.base import IntakeProvider, IntakeTicket

from .blob import S3BlobStore


class S3PresignIntake(IntakeProvider):
    def __init__(self, config):
        self._blob = S3BlobStore(config)
        self._expiry = getattr(config, "ingest_intake_s3_presign_expiry", 3600)

    def begin(self, *, job_id: str, filename: str, namespace: str,
              content_type: str, size: int, requested_by: str,
              metadata: dict) -> IntakeTicket:
        key = f"{job_id}/{filename}"
        # Pin metadata + content type into the presign signature so the client
        # cannot alter them on upload.
        headers = {
            "ContentType": content_type,
            "Metadata": {
                "stache-namespace": namespace,
                "stache-requested_by": requested_by,
                "stache-filename": filename,
            },
        }
        url = self._blob.presign_put(key, headers=headers, expiry=self._expiry)
        return IntakeTicket(
            job_id=job_id,
            upload_url=url,
            required_headers={"Content-Type": content_type},
            expires_at=None,
        )

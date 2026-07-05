"""S3 presigned-PUT IntakeProvider (client-side upload flow)."""

from __future__ import annotations

import os
import urllib.parse

from stache_ai.ingestion.base import IntakeProvider, IntakeTicket

from .blob import S3BlobStore
from .settings import resolve


def _ascii_safe(value: str) -> bool:
    return value.isascii() and value.isprintable()


class S3PresignIntake(IntakeProvider):
    def __init__(self, config):
        self._blob = S3BlobStore(config)
        self._expiry = resolve(config, "ingest_intake_s3_presign_expiry")

    def begin(self, *, job_id: str, filename: str, namespace: str,
              content_type: str, size: int, requested_by: str,
              metadata: dict) -> IntakeTicket:
        # Sanitize to a basename (identical to factory.begin_upload) so a filename
        # containing "/" presigns the same key the worker later reads; a mismatch
        # between the ticket key and job.blob_key would guarantee a FAILED job.
        safe_name = os.path.basename(filename) or "upload.bin"
        key = f"{job_id}/{safe_name}"
        # The pinned filename is folded into the SigV4 signature AND echoed back
        # by the browser on the PUT; browsers reject header values that aren't
        # ISO-8859-1 (fetch/XHR forbid them) and SigV4 metadata should be ASCII,
        # so percent-encode a non-ASCII name (e.g. "résumé.pdf"). ASCII names stay
        # readable; the producer path unquotes symmetrically on read.
        stache_filename = (
            filename if _ascii_safe(filename) else urllib.parse.quote(filename, safe="")
        )
        # Pin metadata + content type into the presign signature so the client
        # cannot alter them on upload.
        pinned_meta = {
            "stache-namespace": namespace,
            "stache-requested_by": requested_by,
            "stache-filename": stache_filename,
        }
        headers = {"ContentType": content_type, "Metadata": pinned_meta}
        url = self._blob.presign_put(key, headers=headers, expiry=self._expiry)
        # S3 signs the x-amz-meta-* headers too, so the client MUST echo every
        # signed header back on the PUT or S3 rejects it with SignatureDoesNotMatch.
        # required_headers therefore carries ALL of them, not just Content-Type.
        required_headers = {"Content-Type": content_type}
        required_headers.update(
            {f"x-amz-meta-{k}": v for k, v in pinned_meta.items()}
        )
        return IntakeTicket(
            job_id=job_id,
            upload_url=url,
            required_headers=required_headers,
            expires_at=None,
        )

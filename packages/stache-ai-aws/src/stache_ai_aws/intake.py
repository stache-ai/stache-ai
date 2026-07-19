"""S3 presigned-PUT IntakeProvider (client-side upload flow)."""

from __future__ import annotations

import os
import urllib.parse

from stache_ai.ingestion.base import IntakeProvider, IntakeTicket

from .settings import resolve


def _ascii_safe(value: str) -> bool:
    return value.isascii() and value.isprintable()


class S3PresignIntake(IntakeProvider):
    def __init__(self, config):
        # Resolve the CONFIGURED blob provider (the same store the pipeline and
        # async worker use) rather than hardcoding the base S3BlobStore. A
        # deployment may swap in a blob provider whose make_key composes keys
        # differently; if the intake presigns with the base layout instead, the
        # object lands at a key the worker's provider-specific parse_job_id
        # cannot invert and the upload job stalls forever. Lazy import to avoid
        # any import cycle.
        from stache_ai.ingestion.factory import _build_blobstore
        self._blob = _build_blobstore(config)
        self._expiry = resolve(config, "ingest_intake_s3_presign_expiry")

    def begin(self, *, job_id: str, filename: str, namespace: str,
              content_type: str, size: int, requested_by: str,
              metadata: dict, principal=None) -> IntakeTicket:
        # Sanitize to a basename (identical to factory.begin_upload) so a filename
        # containing "/" presigns the same key the worker later reads; a mismatch
        # between the ticket key and job.blob_key would guarantee a FAILED job.
        # Compute the key ONCE here via the seam and hand it back in the ticket so
        # the factory records the identical key -- the worker inverts it with
        # BlobStore.parse_job_id, so a make_key override survives the round trip.
        safe_name = os.path.basename(filename) or "upload.bin"
        key = self._blob.make_key(job_id, safe_name, principal=principal)
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
            blob_key=key,
        )

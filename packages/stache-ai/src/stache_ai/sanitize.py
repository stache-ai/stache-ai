"""Sanitization of client-supplied input at the API boundary."""

from __future__ import annotations

# Metadata keys that are only ever set by server-side code. Underscore-prefixed
# keys are the internal-control convention (dedup/reingest state, transport
# fields, organization flags); ``content_hash`` is the dedup identity itself.
# This is the ONE definition of "reserved" - the ingestion worker imports the
# predicate below so route intake and the worker cannot drift on what a client
# may not set (finding INGESTION F2).
RESERVED_METADATA_KEYS = {"content_hash"}

# Server-derived source-identity / smart-update keys. A trusted CLI/API caller
# legitimately supplies ``source_path`` (and its file-stat companions) so the
# deduplication guard can perform SOURCE-identifier smart updates
# (REINGEST_VERSION) instead of the conservative hash-only SKIP used for web
# uploads. A WEB caller must NOT be able to forge them: a forged ``source_path``
# resolves via the namespace's GSI2 to whatever document already owns that path
# and, on a hash mismatch, soft-deletes it (see middleware/guards/
# deduplication.py). They are therefore stripped at every web ingress and
# preserved only where ``allow_source_identity=True`` - the trusted CLI/API
# /ingest path (finding SANITIZER F2).
SOURCE_IDENTITY_KEYS = {"source_path", "file_size", "file_modified_at"}


def is_reserved_metadata_key(key) -> bool:
    """Whether ``key`` is server-controlled and must never be client-set.

    The single source of truth shared by the API sanitizer and the ingestion
    worker: underscore-prefixed internal-control keys plus the explicit
    reserved names (``content_hash``). Source-identity keys are handled
    separately by ``strip_reserved_metadata`` because they are legitimately
    honored on the trusted CLI/API path.
    """
    return isinstance(key, str) and (key.startswith("_") or key in RESERVED_METADATA_KEYS)


def strip_reserved_metadata(metadata: dict | None, *, allow_source_identity: bool = False) -> dict:
    """Drop caller-supplied internal control keys (findings S4 / SANITIZER F1-F2).

    Underscore-prefixed keys and explicit reserved names are written by
    guards, routes, and the ingestion transport AFTER this runs. Accepting
    them from the client would let a caller forge dedup and error-recovery
    state (e.g. point ``_previous_doc_id`` at someone else's document).

    ``source_path``/``file_size``/``file_modified_at`` drive SOURCE-identifier
    smart updates and are honored only when ``allow_source_identity=True`` (the
    trusted CLI/API /ingest path). Every web ingress leaves the default so a web
    caller cannot forge a source path onto another caller's document.
    """
    if not metadata:
        return {}
    return {
        k: v
        for k, v in metadata.items()
        if not is_reserved_metadata_key(k)
        and (allow_source_identity or k not in SOURCE_IDENTITY_KEYS)
    }

"""Sanitization of client-supplied input at the API boundary."""

from __future__ import annotations

# Metadata keys that are only ever set by server-side code. Underscore-prefixed
# keys are the internal-control convention (dedup/reingest state, transport
# fields, organization flags); ``content_hash`` is the dedup identity itself.
RESERVED_METADATA_KEYS = {"content_hash"}


def strip_reserved_metadata(metadata: dict | None) -> dict:
    """Drop caller-supplied internal control keys (finding S4).

    Underscore-prefixed keys and explicit reserved names are written by
    guards, routes, and the ingestion transport AFTER this runs. Accepting
    them from the client would let a caller forge dedup and error-recovery
    state (e.g. point ``_previous_doc_id`` at someone else's document).
    """
    if not metadata:
        return {}
    return {
        k: v
        for k, v in metadata.items()
        if not (isinstance(k, str) and (k.startswith("_") or k in RESERVED_METADATA_KEYS))
    }

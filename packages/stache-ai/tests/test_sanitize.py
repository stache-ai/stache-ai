"""Unit tests for the API-boundary metadata sanitizer.

Covers the shared reserved-key predicate (one definition for the API and the
ingestion worker) and the source-identity handling that closes the SANITIZER F2
forgery vector without breaking CLI/API SOURCE-identifier smart updates.
"""

from stache_ai.sanitize import (
    SOURCE_IDENTITY_KEYS,
    is_reserved_metadata_key,
    strip_reserved_metadata,
)


def test_reserved_predicate_covers_underscore_and_content_hash():
    assert is_reserved_metadata_key("_previous_doc_id")
    assert is_reserved_metadata_key("content_hash")
    # Source-identity keys are NOT reserved - they are honored on the trusted
    # path, so the shared predicate (also used by the worker) must exclude them.
    assert not is_reserved_metadata_key("source_path")
    assert not is_reserved_metadata_key("author")
    assert not is_reserved_metadata_key(42)  # non-str keys are not reserved


def test_strip_removes_reserved_but_keeps_plain_metadata():
    dirty = {
        "author": "alice",
        "content_hash": "forged",
        "_reingest_version": True,
        "_previous_doc_id": "victim-doc",
        "_text": "smuggled",
    }
    assert strip_reserved_metadata(dirty) == {"author": "alice"}
    assert strip_reserved_metadata(None) == {}
    assert strip_reserved_metadata({}) == {}


def test_web_path_strips_forged_source_identity():
    """SANITIZER F2 (forgery closed): the default (web) call strips every
    source-identity key so a web caller cannot forge a source_path onto
    another caller's document."""
    forged = {
        "author": "mallory",
        "source_path": "victims/secret.md",
        "file_size": 999,
        "file_modified_at": "2020-01-01T00:00:00Z",
    }
    cleaned = strip_reserved_metadata(forged)
    assert cleaned == {"author": "mallory"}
    for key in SOURCE_IDENTITY_KEYS:
        assert key not in cleaned


def test_trusted_path_preserves_source_identity_for_smart_update():
    """SANITIZER F2 (feature preserved): the CLI/API path opts in with
    allow_source_identity=True so SOURCE-identifier smart updates keep working;
    genuinely reserved control keys are STILL stripped even there."""
    payload = {
        "author": "alice",
        "source_path": "notes/todo.md",
        "file_size": 1234,
        "file_modified_at": "2026-07-01T00:00:00Z",
        "content_hash": "forged",       # still stripped
        "_previous_doc_id": "victim",   # still stripped
    }
    cleaned = strip_reserved_metadata(payload, allow_source_identity=True)
    assert cleaned == {
        "author": "alice",
        "source_path": "notes/todo.md",
        "file_size": 1234,
        "file_modified_at": "2026-07-01T00:00:00Z",
    }

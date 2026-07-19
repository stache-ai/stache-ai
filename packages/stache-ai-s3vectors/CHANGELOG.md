# Changelog

All notable changes to stache-ai-s3vectors will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.1] - 2026-07-19

### Fixed

- **`get_by_ids` now includes `namespace` in each returned chunk**: previously `namespace` was stripped from the output dict, so callers could not recover a chunk's namespace (only `text`/`content` and the remaining metadata came back). This broke stache-ai's `reconstructed_text`, which resolves a document's namespace from its chunks to fetch the clean stored text — with `namespace` absent it fell back to the overlap-duplicating chunk join. The output now matches the base `get_by_ids` contract (`[{"id", "text", **metadata}, ...]`); only the raw `text` key stays excluded (it is already surfaced as `text`/`content`).

## [0.2.0] - 2026-07-04

### Added

- **`context=` parameter**: `S3VectorsProvider` data methods (`insert`, `search`, `delete`, `delete_by_metadata`, `get_collection_info`, `count_by_filter`, `list_by_filter`, `get_by_ids`, `get_vectors_with_embeddings`, `update_status`, and the summary search helper) accept an optional keyword-only `context` parameter (request context passed through from stache-ai's pipeline). This provider ignores it.

### Requires

- `stache-ai>=0.3.0`

## [0.1.2] - 2026-01-25

### Added

- Soft-delete support with automatic status filtering in search queries
- Default "active" status for all newly inserted vectors
- `get_vectors_with_embeddings` method for document update operations
- Status-based filtering to exclude soft-deleted vectors from search results

### Changed

- Search queries now automatically filter out vectors with `status != "active"` or missing status field
- Insert operations now set `status: "active"` by default if not provided

## [0.1.1] - 2026-01-16

### Fixed

- Fixed multi-field filter format for S3 Vectors API - now correctly converts `{"key1": "val1", "key2": "val2"}` to `{"$and": [{"key1": "val1"}, {"key2": "val2"}]}` format required by S3 Vectors

## [0.1.0] - 2025-12-25

### Added

- Initial release
- S3 Vectors provider for Stache AI vector database
- Support for vector insert, search, and delete operations
- Metadata filtering support
- Namespace-based index management

# Changelog

All notable changes to stache-ai-s3vectors will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

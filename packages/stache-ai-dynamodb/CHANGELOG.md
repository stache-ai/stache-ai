# Changelog

All notable changes to stache-ai-dynamodb will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.3] - 2026-01-26

### Added

- **`get_document_by_source_path()` method**: O(1) lookup of documents by source path using GSI2
  - Enables simplified deduplication without separate identifier records
  - Automatically filters out soft-deleted documents (status != active)

### Changed

- **GSI2 partition key**: Now supports optional `source_path` parameter for deduplication lookups
  - Format: `NS#{namespace}#SRC#{source_path}` when source_path provided
  - Falls back to filename-based GSI2PK for backward compatibility

- **`create_document()` signature**: Now accepts `source_path`, `content_hash`, and `chunk_count` parameters
  - These fields stored directly in DOC# records for deduplication

- **GSI2 index name**: Fixed reference from "GSI2-FilenameCreated" to "GSI2" to match SAM template

## [0.1.2] - 2026-01-25

### Added

- Hash-based deduplication support with identifier reservation records
- Soft delete and trash management operations
- Document update metadata operations

## [0.1.1] - 2026-01-16

### Changed

- Document index and namespace provider improvements for enterprise integration
- Enhanced error handling in document operations

## [0.1.0] - 2025-12-25

### Added

- Initial release
- DynamoDB namespace provider for Stache AI
- DynamoDB document index provider
- Support for hierarchical namespaces
- Document metadata storage and retrieval

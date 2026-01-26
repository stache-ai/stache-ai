# Changelog

All notable changes to stache-ai-mongodb will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2026-01-25

### Added

- Document metadata update support via `update_document_metadata` method
- Namespace migration with transaction support (with automatic fallback for non-replica sets)
- Support for updating document filename and custom metadata fields
- Atomic operations using MongoDB transactions where available

### Note

- Hash-based deduplication and trash/restore features are not supported in this provider
- Methods for deduplication (`reserve_identifier`, `get_document_by_identifier`, etc.) and trash operations (`soft_delete_document`, `restore_document`, etc.) raise `NotImplementedError`
- Use DynamoDB provider for full deduplication and trash/restore functionality

## [0.1.0] - 2025-12-25

### Added

- Initial release
- MongoDB namespace provider implementation
- MongoDB document index provider with full-text search capabilities
- Support for document metadata storage and retrieval

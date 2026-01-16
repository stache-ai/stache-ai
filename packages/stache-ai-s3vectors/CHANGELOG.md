# Changelog

All notable changes to stache-ai-s3vectors will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

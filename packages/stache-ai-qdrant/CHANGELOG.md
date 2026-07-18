# Changelog

All notable changes to stache-ai-qdrant will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-07-04

### Added

- **`context=` parameter**: `QdrantVectorDBProvider` data methods accept an optional keyword-only `context` parameter (request context passed through from stache-ai's pipeline). This provider ignores it.
- **`scan_by_metadata`**: New method for full-collection metadata scans via `client.scroll`, advertised through the `"metadata_scan"` capability. Replaces the pattern of API routes reaching into this provider's raw Qdrant client for maintenance scans (orphaned-chunk cleanup, summary migration).

### Requires

- `stache-ai>=0.3.0`

## [0.1.1] - 2026-01-25

### Added

- Document update operations support
- `get_vectors_with_embeddings` method for retrieving vectors with full embedding data for updates
- `max_batch_size` property (1000) for batch operation limits
- Namespace filtering support in vector retrieval

## [0.1.0] - 2025-12-25

### Added

- Initial release
- Qdrant vector database provider for Stache AI
- Support for vector insert, search, and delete operations
- Advanced metadata filtering and server-side filtering capabilities
- Collection management and export functionality

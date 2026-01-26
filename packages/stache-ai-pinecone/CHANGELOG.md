# Changelog

All notable changes to stache-ai-pinecone will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2026-01-25

### Added

- Document update operations support
- `get_by_ids` method for fetching vectors by IDs with metadata
- `get_vectors_with_embeddings` method for retrieving vectors with full embedding data
- `max_batch_size` property (1000) for batch operation limits

## [0.1.0] - 2025-12-25

### Added

- Initial release
- Pinecone vector database provider for Stache AI
- Support for vector insert, search, and delete operations
- Metadata filtering and namespace management

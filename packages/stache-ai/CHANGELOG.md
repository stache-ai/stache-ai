# Changelog

All notable changes to stache-ai will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.9] - 2026-01-26

### Changed

- **Simplified Deduplication Architecture**: Removed over-engineered SOURCE#/HASH# identifier reservation records
  - Deduplication now uses GSI2 lookup on DOC# records directly (O(1) lookup by source_path)
  - `source_path` and `content_hash` stored directly in DOC# records
  - 67% fewer DynamoDB writes per ingestion (3 → 1)
  - No more orphaned reservation records or race condition complexity

- **DeduplicationGuard Middleware**: Now uses `get_document_by_source_path()` instead of identifier-based lookups
  - Same functionality (SKIP, REINGEST_VERSION, NEW) with simpler implementation

- **Base Provider Interface**: Added `get_document_by_source_path()` method with fallback for backward compatibility

## [0.1.8] - 2026-01-25

### Added

- **Hash-Based Deduplication**: Content-addressable storage prevents duplicate ingestion
  - SHA-256 hashing of document content with smart fingerprint strategies
  - `IngestGuard` middleware for pre-ingestion duplicate detection
  - `SKIP` vs `REINGEST_VERSION` modes for handling duplicates
  - Source path and file modification time tracking for intelligent updates
  - Document identifier reservation with atomic operations

- **Soft Delete and Trash Management**: Universal soft-delete with 30-day retention
  - `soft_delete_document`, `restore_document`, `list_trash` operations
  - Status-based filtering (`active`, `deleting`, `purging`, `purged`)
  - Trash entries with expiration timestamps and audit metadata
  - `permanently_delete_document` for explicit trash emptying
  - Automatic cleanup workers for expired trash items

- **Error Recovery Architecture**: Automatic rollback on failed updates
  - `ErrorProcessor` middleware type for post-error handling
  - `ReingestRecoveryProcessor` auto-restores old documents if new version fails
  - Prevents data loss from partial ingestion failures

- **Document Update Operations**: Provider-agnostic metadata updates
  - `update_document_metadata` in all vector DB providers (S3 Vectors, Qdrant, Pinecone, MongoDB)
  - Support for namespace migration, filename updates, custom metadata
  - `get_vectors_with_embeddings` for efficient document re-writes
  - `max_batch_size` property for batch operation limits

- **Trash Management Routes**: New FastAPI endpoints
  - `GET /api/trash` - List documents in trash with namespace filtering
  - `POST /api/trash/{doc_id}/restore` - Restore from trash
  - `DELETE /api/trash/{doc_id}` - Permanent delete with cleanup job creation

- **Cleanup Workers**: Async background processing
  - `cleanup_worker.py` for permanent vector deletion
  - Job-based architecture with failure tracking
  - Scheduled workers for expired trash processing

### Changed

- **VectorDBProvider Base Class**: `update_status` method now has default no-op implementation (no longer abstract)
  - Providers without status filtering log warnings but don't break instantiation
  - S3 Vectors implements full status-based soft delete

- **DocumentIndexProvider Base Class**: Added `filename` parameter to `complete_permanent_delete` signature
  - Required for providers using filename in trash entry primary keys

- **Pipeline Ingestion**: Enhanced with deduplication and error recovery
  - Pre-ingestion checks via IngestGuard middleware
  - Post-error recovery via ErrorProcessor middleware
  - Automatic chunk cleanup on ingestion failures

- **Search Operations**: S3 Vectors now automatically filters out soft-deleted vectors
  - Status filter applied to all search queries (`status=active OR status NOT EXISTS`)
  - Backward compatible with legacy vectors without status field

### Fixed

- Provider instantiation errors for Qdrant and Pinecone (removed abstract method requirement for `update_status`)
- Signature mismatch in `complete_permanent_delete` (now consistent across base class and implementations)

### Notes

- **MongoDB Provider Limitations**: Hash deduplication and trash/restore features not supported
  - Methods raise `NotImplementedError` with clear error messages
  - Use DynamoDB provider for full feature support

- **Default Configuration**: Deduplication enabled by default (`DEDUP_ENABLED=true`)
  - Soft-delete operations require document index provider support
  - Status filtering in vector DBs is provider-dependent (full support in S3 Vectors)

## [0.1.7] - 2026-01-16

### Added

- **Concept Operations**: New `do_search_concepts`, `do_search_concepts_with_docs`, `do_get_concept_documents`, `do_get_document_concepts`, and `do_get_related_documents` operations for enterprise concept discovery
- **DeleteObserver Middleware**: Built-in delete observer support in middleware chain

### Fixed

- Fixed `embed_query()` usage in concept search operations (was incorrectly passing list to single-string API)
- License format updated to modern pyproject.toml string format

## [0.1.6] - 2026-01-14

### Added

- Concept discovery operations integration with enterprise middleware

## [0.1.5] - 2026-01-11

### Added

- **PostIngestProcessor Middleware**: New middleware type for generating artifacts after document ingestion
  - `PostIngestProcessor` base class with enforced skip-on-error semantics
  - `HeuristicSummaryGenerator` built-in implementation for document summarization
  - Entry point: `stache.postingest_processor` for plugin registration
  - `PostIngestResult` dataclass for structured artifact output

- **Middleware Chain Enhancements**:
  - `MiddlewareChain.run_postingest()` method for processing post-ingest chains
  - Support for async middleware execution
  - Comprehensive error handling with optional skip-on-error behavior

### Changed

- Document summary generation refactored from pipeline into middleware architecture
- Summary generation now controlled via `enable_summary_generation` config flag
- Pipeline's `_create_document_summary()` removed in favor of middleware-based approach

### Fixed

- Thread-safe lazy loading for post-ingest processor properties

## [0.1.4] - 2026-01-06

### Changed

- Version bump for PyPI metadata consistency

## [0.1.3] - 2026-01-03

### Fixed

- Fixed broken GitHub URLs in PyPI metadata (stache-ai/stache → stache-ai/stache-ai)

## [0.1.2] - 2025-12-29

### Fixed

- Package metadata and documentation updates

## [0.1.1] - 2025-12-29

### Added

- **Middleware Plugin Architecture**: Extensible hooks for enterprise customization
  - `Enricher` - Pre-process content before chunking (e.g., audio transcription, URL fetching)
  - `ChunkObserver` - Monitor chunks after storage (e.g., quota tracking, auditing)
  - `QueryProcessor` - Transform queries before search (e.g., query expansion, ACL filters)
  - `ResultProcessor` - Filter/transform results after search (e.g., PII redaction, re-ranking)
  - `DeleteObserver` - Validate and audit deletions (e.g., compliance logging)

- **Plugin Discovery via Entry Points**: External packages can register middleware using standard Python entry points:
  - `stache.enrichment`
  - `stache.chunk_observer`
  - `stache.query_processor`
  - `stache.result_processor`
  - `stache.delete_observer`

- **Request Context**: `RequestContext` and `QueryContext` classes for passing request metadata through middleware chains

- **Middleware Testing Utilities**: Mock classes for testing custom middleware (`MockEnricher`, `MockQueryProcessor`, etc.)

- **Developer Documentation**: Comprehensive plugin developer guide at `docs/middleware-plugin-guide.md`

### Changed

- Pipeline methods now support middleware hooks at ingest, query, and delete paths
- Thread-safe lazy initialization for middleware properties

## [0.1.0] - 2025-12-15

### Added

- Initial release
- RAG pipeline with chunking, embedding, and retrieval
- Provider plugin architecture (LLM, embeddings, vector DB, namespace)
- FastAPI REST API
- CLI tools (`stache-admin`, `stache-import`)
- Support for multiple file formats (PDF, DOCX, EPUB, Markdown, etc.)
- Auto-split embedding for large chunks

# Changelog

All notable changes to stache-ai will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

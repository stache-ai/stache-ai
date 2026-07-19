# Changelog

All notable changes to stache-ai will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.1] - 2026-07-18

### Added

- **Original-file download endpoint**: `GET /api/documents/{doc_id}/original` returns a short-lived presigned download URL (`{"url": ...}`) for a document's retained original, authorizing the same `read_document` op as the other document routes. Returns 404 when the record has no `blob_key` (old document, pasted text) or the active blob store cannot presign; the bytes never stream through the app. URL lifetime is set by the new `INGEST_BLOB_DOWNLOAD_EXPIRY` config (default 300s).
- **`BlobStore.presign_get` seam**: additive `presign_get(key, *, expiry, download_filename=None)` on the `BlobStore` ABC (default returns None), advertised via a new `presign_download` entry in the `BlobStore.capabilities` set (mirrors the `VectorDBProvider` capability mechanism). Implemented on the AWS `S3BlobStore` (`generate_presigned_url("get_object", ...)` with `ResponseContentDisposition` for the save-as name).
- **Doc→original linkage**: the document index record now persists `blob_key` and `content_type`; `DocumentIndexProvider.create_document` accepts both (threaded from the ingestion job via `context.custom["ingest_job"]`). Forward-only — pre-existing documents simply lack `blob_key`.
- **`has_original` flag**: documents-list items and query-result sources now carry `has_original` (true iff the record has a `blob_key` and the blob store advertises `presign_download`), so clients can show a download affordance without a probe request.
- **Clean extracted-text storage + retrieval**: the full extracted/plain text is now persisted to the blob store at ingest (a sibling `{blob_key}.text` blob for extracted files, a job-scoped `extracted.txt` blob for pasted text) and its key recorded as `text_blob_key` on the document record. `GET /api/documents/chunks` now serves `reconstructed_text` from that stored text instead of joining the chunks with `\n\n` — the old join duplicated every `chunk_overlap` region and injected spurious breaks — falling back to the join only when no text blob exists. `GET /api/documents/{doc_id}/original?format=text` presigns the clean text blob (404 when absent). The text bytes live in S3, never as a DynamoDB attribute, so metadata reads stay cheap and never hit the 400KB item cap.

### Fixed

- **No-namespace upload no longer 500s**: an ingest/capture/upload request with no namespace (the frontend sends `namespace: null`, and `default_namespace` is unset on staging) previously resolved the namespace to `None`, which was pinned into S3 object metadata and blew up botocore's ascii validation (`None.encode(...)` → HTTP 500). The route entry points now fall back to the literal `"default"` namespace, and authorization and the downstream ingest agree on that one value. As defense in depth, `S3BlobStore.presign_put` now drops any `None`-valued metadata entry before signing, so no `None` can ever reach botocore.
- **`pollJob` tolerates transient poll failures**: the presigned-upload poller threw on the first failed `getJob`, so a single dropped connection / API-Gateway 5xx during the ~10s ingest would fail an upload that actually succeeded server-side. It now tolerates up to `maxConsecutiveErrors` (default 4) consecutive poll failures before giving up, resetting the counter on any successful poll; the overall timeout and exponential backoff are unchanged.
- **`reconstructed_text` now serves the stored clean text for S3 Vectors deployments**: `_reconstructed_text` resolves a document's namespace from its chunks, but the s3vectors `get_by_ids` was stripping `namespace` from every returned chunk, so the resolved namespace was `None` and `get_document_record` rejected it — silently falling back to the overlap-duplicating chunk join even for a faithful full-document fetch. Namespace resolution is now robust: it takes the first truthy namespace among the matching chunks (top-level or nested under `metadata`), and returns the join without a record lookup when none can be resolved (never a lookup with a falsy namespace). Paired with the s3vectors provider now including `namespace` in `get_by_ids` output.

## [0.3.0] - 2026-07-04

### Added

- **Caller identity seam**: New `Principal` dataclass (`user_id` + opaque `claims`) in `stache_ai.identity`, returned by `api.auth.principal()`. Core attaches no meaning to claims — deployment-specific extensions read them.
- **Pluggable principal extraction**: `stache.principal_extractor` entry point group plus `PRINCIPAL_EXTRACTOR` config. Default `ApiGatewayClaimsExtractor` preserves the existing single-user posture. Identity middleware wires the extractor into every request; `AuthenticationError` maps to a 401. A configured-but-unloadable extractor aborts startup instead of silently degrading to anonymous.
- **Pluggable authorization**: `stache.authorizer` entry point group plus `AUTHORIZATION_PROVIDER` config, `AuthorizationProvider` ABC, and the default `AllowAllAuthorizer` (no enforcement, matching current behavior). `ForbiddenError` maps to a 403. Every API route now calls through the authorization seam with a neutral operation string (e.g. `ingest`, `read_pending`). A configured-but-unloadable authorizer aborts startup rather than falling back to allow-all.
- **`context=` on provider data methods**: `VectorDBProvider`, `DocumentIndexProvider`, `NamespaceProvider`, and `RerankerProvider` methods all gained a keyword-only `context: RequestContext | None = None` parameter, threaded from routes and the pipeline through to every provider call. First-party providers accept and ignore it unless they have a reason to act on it.
- **`context=` on `LLMProvider`/`EmbeddingProvider`**: completes the provider context threading. `EmbeddingProvider.embed`/`embed_batch`/`embed_query` and `LLMProvider.generate`/`generate_with_model`/`generate_structured`/`generate_with_tools` gained a keyword-only `context=None`; `generate_with_context`/`generate_with_context_and_model` gained a keyword-only `request_context=None` (their `context` positional already denotes the RAG chunk list). Threaded through the pipeline embed/generate call sites (ingest, query synthesis, summary regeneration) and the auto-split embedding wrapper. First-party providers accept it and forward it across their own nested generate/embed calls — the per-package providers (Bedrock, Anthropic, OpenAI, Cohere, Ollama, Mixedbread) as well as the in-tree `fallback`/`none` providers shipped in core (`stache_ai.providers.llm`/`stache_ai.providers.embeddings`) — and otherwise ignore it.
- **`LimitExceededError` → HTTP 429**: new neutral `stache_ai.identity.LimitExceededError`, raised when an operation is rejected by a configured rate/resource limit, mapped by an app exception handler to `429` with a `Retry-After` header. Mirrors the existing `ForbiddenError` → 403 seam; routes re-raise it ahead of their blanket handler, and a static AST sweep test enforces the re-raise (alongside `ForbiddenError`) so it cannot regress. OSS attaches no meaning to which limit was hit.
- **`scan_by_metadata`**: New capability-gated `VectorDBProvider` method (advertise via the `"metadata_scan"` capability) for full-collection metadata scans, replacing routes that previously reached into a provider's raw client directly.
- **`principal=` on ingestion seams**: `JobStore.create`/`JobStore.list` and `IntakeProvider.begin` accept an optional `principal` kwarg. `BlobStore.make_key(job_id, filename, *, principal=None)` is now overridable so deployment-specific stores can vary key layout by caller.
- **Producer-drop gate**: `INGEST_PRODUCER_DROPS_ENABLED` config flag controls whether raw drops into the originals bucket (no pre-created job) are accepted.
- **Job visibility + queued-work identity seams**: `JobStore.visible_to(job, principal)` scopes the single-job fetch (`GET /api/jobs/{id}` treats an invisible job exactly like a missing one — 404, no existence leak) and `JobStore.principal_for(job)` reconstructs the acting principal for the worker's authorization re-check. Defaults preserve current behavior (requester-only visibility, id-only principal); deployment-specific stores may override both from attributes they stamp at `create` time. The worker also places the reconstructed principal on `context.custom["principal"]`.
- **`get_ancestors`/`get_path` on `NamespaceProvider`**: promoted to context-aware base-class methods (default parent walk over `get`); the four first-party implementations now share the base implementation. `pipeline.update_document`, the insight operations, and summary generation also gained/forward `context=`.

### Changed

- **Fail-closed plugin/provider loading**: a configured route plugin, principal extractor, or authorization/provider entry point that is installed but fails to load now aborts startup with a `RuntimeError` instead of logging a warning and continuing without it. Entry points backed by an optional dependency that simply isn't installed still skip normally.
- **Metadata sanitization**: caller-supplied `_`-prefixed metadata keys and `content_hash` are now stripped at API boundaries before routes/guards write their own internal-control values, closing a path where a caller could forge dedup/error-recovery state.
- **Pipeline ops layer**: document, trash, and namespace routes now go through the pipeline instead of calling providers directly, and delete is unified behind one code path.
- **Authorization denials always surface as 403**: every API route now re-raises `ForbiddenError` ahead of its blanket error handler, so a denial raised mid-request (by a plugged authorizer or a provider) reaches the app's 403 handler instead of being caught by a route's catch-all and rewritten into a 500.
- **Ingestion worker strips all reserved job metadata**: the worker now drops every `_`-prefixed `job.metadata` key (not just the transport keys) before calling the pipeline, so server-set state stamped on the job record can no longer leak into chunk/vector metadata.
- **Request context forwarded through nested provider/middleware calls**: `context=` is now threaded through the previously-missing inner data calls — namespace `get_tree`/delete-cascade/create-update across the first-party implementations, the deduplication guard on the default ingest path, document-index `get_chunk_ids` → `get_document` and metadata helpers, the reingest-recovery error processor, and the core operations layer. A signature-presence check alone does not catch a dropped inner forward, so the accompanying tests assert propagation by object identity through the known nested sites.
- **Relocation routes authorize the destination**: moving a document to another namespace, and reparenting/creating a namespace under another parent, now authorize the destination (the write target), not only the source — closing a gap where a caller allowed on the source could relocate into a namespace they may not write to. Read routes now also pass an opaque resource dict (owner/namespace when cheaply available) to the authorizer.
- **Plugin construction by signature inspection**: configured plugins/providers are instantiated by inspecting the constructor signature rather than catching a `TypeError` from a probe call, so a genuine `TypeError` raised inside a constructor that *does* accept config now propagates (fail-closed) instead of being silently retried with no arguments (which would strip the plugin of its configuration).
- **Ingress sanitization on every write path**: reserved-metadata sanitization now also runs on the pending-approve path, and source-identity keys (`source_path`, `file_modified_at`) are only honored on trusted CLI/API ingress; the worker and API boundary share one unified reserved-key definition so the two can no longer drift.
- **Producer drops secure-by-default**: `INGEST_PRODUCER_DROPS_ENABLED` now defaults to `false`. Raw drops into the originals bucket carry producer-asserted (unauthenticated) namespace/`requested_by`, so accepting them is now opt-in rather than on by default.
- **Unified content-write verb**: every path that submits content for ingestion (`POST /ingest`, `POST /capture`, the producer-drop path, and the worker's re-check) authorizes the single canonical `ingest` operation, so the route-presented op always equals the worker-enforced op.

### Fixed

- **Insight operations honor the guard/processor middleware seams**: `create_insight` now runs the ingest-guard chain (it stores a vector, like ingest) and `search_insights` now runs the query-processor chain (like `query`), mirroring the main paths. Previously a registered guard or query processor never fired on `POST /insights` or `GET /insights/search`, so a rejection (or a raised `LimitExceededError`/`ForbiddenError`) that blocks ingest/query was silently skipped there. A raised exception now propagates to the route's existing handlers; a reject blocks the operation.
- **Error/cleanup processors run on the ingest SKIP-return paths**: when `ingest_text` returns a SKIP (a guard blocked ingestion, or Step-2 identifier reservation detected a concurrent duplicate) it now runs the `ErrorProcessor` cleanup seam, the same seam the exception path runs. Previously the SKIP was a plain return that bypassed it, so any state a guard reserved for rollback was never released; guards now get the symmetric release hook on skip and on error.

## [0.2.0] - 2026-07-05

See [docs/release-0.2.md](../../docs/release-0.2.md) for the full release notes.

### Added

- **Async Ingestion Backbone**: provider-abstracted submit → poll pipeline behind
  five new seams (`IntakeProvider`, `QueueProvider`, `JobStore`, `BlobStore`,
  `Notifier`) with matching entry point groups (`stache.ingest_queue`,
  `stache.ingest_jobstore`, `stache.ingest_blob`, `stache.ingest_intake`,
  `stache.ingest_notifier`). Sync in-process tier is the default; the AWS async
  tier ships in `stache-ai-aws` 0.2.0 / `stache-ai-dynamodb` 0.1.6.
- **Unified ingestion API**: `POST /api/ingest` (text, base64 file, or presigned
  upload; optional server-side wait), `GET /api/jobs/{id}`, `GET /api/jobs`
  (requester-scoped, `cursor` pagination param with validated `limit` 1–200).
- `INGEST_PRODUCER_DROPS_ENABLED` (default `true`): kill switch for raw S3
  producer drops, whose namespace/`requested_by` come from producer-asserted
  (unauthenticated) object metadata.
- Oversized text submissions (`POST /api/ingest`, `POST /api/capture`) are
  rejected with **413** at the smaller of `MAX_INGEST_TEXT_BYTES` and any
  jobstore-declared inline-payload cap (DynamoDB: 350KB, under its 400KB item
  limit), so oversize text no longer 500s on the backend write; the completed
  (and reaper-failed) job record no longer retains the document body.
- **Request principals**: `requested_by` extracted from API Gateway JWT
  authorizer claims (falls back to `anonymous`); namespace write-authz hook
  stubbed for follow-up enforcement.
- `EmptyExtractionError`: empty/scanned/corrupt documents fail loudly instead of
  storing an empty `active` document with a hallucinated summary.
- Frontend Jobs page (`/jobs`) and presign-upload client helpers.

### Changed

- `POST /api/capture` routes through the ingestion service in wait-mode
  (response shape preserved; adds `job_id`/`status`). A wait-mode timeout now
  returns `action: "processing"` instead of a false `ingested_new`.
- Presigned upload `required_headers` now includes every signed header
  (`Content-Type` + pinned `x-amz-meta-stache-*`), not just `Content-Type`;
  the presign expiry default drops to 1500s (must stay under the reaper TTL).
  Non-ASCII filenames are percent-encoded into `x-amz-meta-stache-filename` so
  the browser can echo the signed header on the PUT (ISO-8859-1 only); the
  producer path unquotes them back to the original name.
- `POST /api/upload` returns 422 (was 500) when no text is extractable.
- Hierarchical chunking omits empty `headings`/`doc_item_labels` metadata keys
  (S3 Vectors rejects empty arrays).
- Concept-index resolution failures are logged at ERROR instead of silently
  skipping concept extraction.

### Removed

- AWS-specific ingestion code and settings from core: the SQS worker and reaper
  Lambda entrypoints now live in `stache-ai-aws`, and `INGEST_BLOB_S3_*`,
  `INGEST_QUEUE_SQS_URL`, `INGEST_JOBSTORE_DYNAMODB_TABLE`, and
  `INGEST_INTAKE_S3_PRESIGN_EXPIRY` are read by the plugin packages (env var
  names unchanged).

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

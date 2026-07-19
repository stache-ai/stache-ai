# Changelog

All notable changes to stache-ai-aws will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.2]

### Fixed

- **Presigned-upload intake honors the configured blob provider**: `S3PresignIntake` now resolves the blob store from `ingest_blob_provider` (via the ingestion factory) instead of hardcoding the base `S3BlobStore`. A deployment that swaps in a blob provider with a different key layout previously had its presigned uploads land at a key the async worker's `parse_job_id` could not invert, so the upload job stalled forever and no document was created. The intake now presigns the same key layout the pipeline and worker use.

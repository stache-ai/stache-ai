# Hash Deduplication & Trash/Restore

**Status**: Production ready, enabled by default (v0.1.x+1)
**Date**: January 25, 2026

## Overview

Stache provides automatic hash-based deduplication and a universal trash/restore system to prevent duplicate content and protect against accidental deletions.

### Key Features

- **Automatic Deduplication**: SHA-256 content hashing detects duplicate uploads
- **Smart Updates**: CLI/API automatically update files when content changes
- **Trash Safety Net**: 30-day retention for deleted documents with one-click restore
- **Error Recovery**: Failed updates automatically restore previous versions
- **Zero Configuration**: Enabled by default, works across all providers

## Deduplication

### How It Works

Stache computes a SHA-256 hash of document content and uses it to detect duplicates:

**Web Uploads** (Conservative Strategy):
- Uses content hash + filename as identifier
- Same file uploaded twice → **SKIP** (duplicate detected)
- Different content, same filename → **INGEST_NEW** (treated as separate document)
- User can manually delete old version if needed

**CLI/API/S3 Uploads** (Smart Strategy):
- Uses source file path as identifier
- Same path, same content → **SKIP** (no change)
- Same path, different content → **REINGEST_VERSION** (automatic update)
- Old version moved to trash, new version becomes active

### Examples

```bash
# First upload
stache ingest report.pdf --namespace finance
# Result: INGEST_NEW (new document created)

# Same file again (no changes)
stache ingest report.pdf --namespace finance
# Result: SKIP (duplicate detected, no cost)

# Updated file (content changed)
stache ingest report.pdf --namespace finance
# Result: REINGEST_VERSION (old version → trash, new version active)
```

### Decision Tree: SKIP vs UPDATE vs NEW

Stache decides how to handle uploads based on identifier strategy and content hash:

#### Web Uploads (Fingerprint Strategy)

```
Upload file via web UI
  │
  ├─ Hash: abc123, Filename: report.pdf
  │
  ├─ Document exists with hash abc123 + report.pdf?
  │   YES → SKIP (duplicate detected, no action)
  │   NO  → Continue...
  │
  ├─ Document exists with different hash + report.pdf?
  │   YES → INGEST_NEW (different content, keep both)
  │   NO  → INGEST_NEW (first time)
```

**Web Upload Rules**:
- ✅ **SKIP**: Exact same file uploaded again (same hash + filename)
- ✅ **INGEST_NEW**: Different file with same filename (different hash)
- ❌ **NEVER UPDATE**: Web uploads never auto-update existing documents

#### CLI/API Uploads (Source Path Strategy)

```
Upload file via CLI with source path
  │
  ├─ Source: /home/user/reports/Q4.pdf
  │  Hash: abc123
  │
  ├─ Document exists with source path /home/user/reports/Q4.pdf?
  │   NO  → INGEST_NEW (first upload)
  │   YES → Continue...
  │
  ├─ Existing document has hash abc123?
  │   YES → SKIP (no changes, duplicate)
  │   NO  → REINGEST_VERSION (content changed, auto-update)
  │       ├─ Soft delete old version (move to trash)
  │       └─ Ingest new version
```

**CLI/API Rules**:
- ✅ **SKIP**: Same file at same path (no changes)
- ✅ **REINGEST_VERSION**: Updated file at same path (different hash)
- ✅ **INGEST_NEW**: New file at new path

### Practical Examples

#### Scenario 1: Web Upload - Same File Twice

```bash
# User uploads report.pdf via web UI
Result: INGEST_NEW (doc_id: doc-123, hash: abc123)

# User uploads same report.pdf again
Result: SKIP
Reason: Identifier "HASH#default#abc123#report.pdf" already exists
Cost: $0 (no enrichment)
```

#### Scenario 2: Web Upload - Updated Report

```bash
# User uploads report.pdf (v1) via web UI
Result: INGEST_NEW (doc_id: doc-123, hash: abc123)

# User edits report.pdf locally, uploads again
Result: INGEST_NEW (doc_id: doc-456, hash: def456)
Reason: Different hash = different document (both kept)

# Cleanup: User must manually delete doc-123 from Documents page
```

#### Scenario 3: CLI - Same File Twice

```bash
# First upload
stache ingest /home/user/reports/Q4.pdf --namespace finance
Result: INGEST_NEW (doc_id: doc-789, hash: abc123)

# Same command again (no file changes)
stache ingest /home/user/reports/Q4.pdf --namespace finance
Result: SKIP
Reason: Source path "/home/user/reports/Q4.pdf" + hash abc123 already exists
Cost: $0
```

#### Scenario 4: CLI - Updated File (Smart Update)

```bash
# First upload
stache ingest /home/user/reports/Q4.pdf --namespace finance
Result: INGEST_NEW (doc_id: doc-789, hash: abc123)

# User edits Q4.pdf locally, runs same command
stache ingest /home/user/reports/Q4.pdf --namespace finance
Result: REINGEST_VERSION (new doc_id: doc-101, hash: def456)
Actions:
  1. Old doc-789 → trash (status: deleting)
  2. New doc-101 → active
  3. User can restore doc-789 from trash if needed
```

#### Scenario 5: REINGEST_VERSION with Error Recovery

```bash
# User updates Q4.pdf and re-uploads
stache ingest /home/user/reports/Q4.pdf --namespace finance

# Behind the scenes:
1. Hash computed: def456 (different from abc123)
2. Old doc-789 moved to trash
3. New ingestion starts...
4. LLM enrichment FAILS (API timeout)
5. ErrorProcessor detects REINGEST_VERSION failure
6. Old doc-789 automatically restored from trash
7. User sees error but data not lost

Result: FAILED (doc-789 still active)
User Action: Fix issue, retry upload
```

### Benefits

- **Cost Savings**: Skip duplicate enrichment and embedding costs
- **Version Control**: Automatic updates for files at same path
- **Data Integrity**: Hash verification ensures content accuracy
- **Performance**: Early detection (before expensive LLM enrichment)

## Trash & Restore

### 30-Day Retention

All deleted documents move to trash instead of permanent deletion:

- **Soft Delete**: Documents marked as "deleting", invisible in search
- **Retention Period**: 30 days (configurable via `SOFT_DELETE_TTL_DAYS`)
- **Auto-Purge**: Daily worker removes expired trash
- **Manual Purge**: Permanent delete available in UI

### Restore Process

Restore moves documents back to active state:

1. Document status: `deleting` → `active`
2. Vector status: `deleting` → `active` (search-visible)
3. Trash entry removed
4. Document immediately searchable

### Complete Deletion Workflow

Understanding the lifecycle of a deleted document:

```
┌─────────────────────────────────────────────────────────────────┐
│ Step 1: User Deletes Document                                   │
├─────────────────────────────────────────────────────────────────┤
│ Actions:                                                         │
│  • Document status: active → deleting                            │
│  • Vector status: active → deleting                              │
│  • Trash entry created with 30-day TTL                           │
│  • Document disappears from search results                       │
│  • Appears in Trash page                                         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 2: Retention Period (0-30 days)                            │
├─────────────────────────────────────────────────────────────────┤
│ User Options:                                                    │
│  A) Restore → Returns to active, searchable                      │
│  B) Wait → Auto-purge after 30 days                              │
│  C) Permanent Delete → Immediate cleanup                         │
└─────────────────────────────────────────────────────────────────┘
                    │           │           │
         ┌──────────┘           │           └──────────┐
         │ A) RESTORE            │ B) WAIT              │ C) PERMANENT
         ▼                       ▼                      ▼
┌─────────────────┐  ┌────────────────────┐  ┌──────────────────┐
│ Back to Active  │  │ Day 30: Auto-Purge │  │ User Confirms    │
│ • Status=active │  │ Daily worker runs  │  │ Manual Delete    │
│ • Searchable    │  │ Triggers delete    │  │ Immediate action │
└─────────────────┘  └────────┬───────────┘  └────────┬─────────┘
                              │                        │
                              └────────┬───────────────┘
                                       ▼
                        ┌──────────────────────────────┐
                        │ Step 3: Permanent Deletion   │
                        ├──────────────────────────────┤
                        │ Actions:                     │
                        │  • Cleanup job created       │
                        │  • Status: deleting→purging  │
                        │  • API returns immediately   │
                        └──────────┬───────────────────┘
                                   ▼
                        ┌──────────────────────────────┐
                        │ Step 4: Background Cleanup   │
                        ├──────────────────────────────┤
                        │ CleanupWorker Lambda:        │
                        │  • Deletes vectors (chunks)  │
                        │  • Updates doc: purged       │
                        │  • Deletes trash entry       │
                        │  • Creates tombstone         │
                        │ Time: <5min for 100 docs     │
                        └──────────────────────────────┘
```

### Trash Emptying: Three Ways

#### 1. Manual Restore (User Action)

```bash
# Via Web UI
Navigate to /trash → Click "Restore" button → Confirm

# Via CLI
stache restore doc-123 --namespace finance --deleted-at-ms 1706198400000

# Result
• Document status: deleting → active
• Vector status: deleting → active
• Trash entry deleted
• Immediately searchable in queries
```

#### 2. Manual Permanent Delete (User Action)

```bash
# Via Web UI
Navigate to /trash → Click "🗑️" button → See warning → Confirm

# Via API
POST /api/trash/permanent
{
  "doc_id": "doc-123",
  "namespace": "finance",
  "deleted_at_ms": 1706198400000
}

# Result
• Cleanup job created (job_id: cleanup-456)
• Document status: deleting → purging
• API returns immediately (async cleanup)
• Background worker deletes vectors
• Final status: purged (tombstone)
```

#### 3. Automatic Purge (Scheduled Worker)

```bash
# Daily at 2 AM UTC (EventBridge cron)
TrashPurgeWorker runs:
  1. Query: purge_after < now()
  2. Batch: 100 expired entries
  3. For each: trigger permanent delete
  4. Creates cleanup jobs for background processing

# Example Log
INFO: Found 15 expired trash entries
INFO: Triggering permanent delete: doc-123, doc-456, ...
INFO: Created 15 cleanup jobs
INFO: Auto-purge complete
```

### Trash Entry States

A document in trash can be in one of these states:

| Status | Meaning | User Actions | Auto-Purge |
|--------|---------|--------------|------------|
| `deleting` | Soft-deleted, restorable | Restore, Permanent Delete | After TTL |
| `purging` | Permanent delete in progress | None (wait) | N/A |
| `purged` | Hard deleted (tombstone) | None | N/A |

### Multiple Versions in Trash

Unique trash entries allow multiple deletions of the same file:

```bash
# Upload report.pdf
stache ingest report.pdf --namespace finance
# Result: doc-123 created

# Delete it
stache delete doc-123 --namespace finance
# Result: Trash entry "TRASH#finance#report.pdf#1706100000000"

# Re-upload same report.pdf (REINGEST_VERSION if source path)
stache ingest report.pdf --namespace finance
# Result: doc-456 created

# Delete it again
stache delete doc-456 --namespace finance
# Result: Trash entry "TRASH#finance#report.pdf#1706200000000"

# Both versions in trash simultaneously!
# User can restore either version independently
```

### Web UI

Access trash at `/trash` route:

**Features**:
- Table view with filename, namespace, deleted date, purge countdown
- Filter by namespace
- One-click restore with confirmation
- Permanent delete with strong warning
- Days until auto-purge (highlighted when < 7 days)

### API Endpoints

```bash
# List trash
GET /api/trash?namespace=finance

# Restore document
POST /api/trash/restore
{
  "doc_id": "abc-123",
  "namespace": "finance",
  "deleted_at_ms": 1706198400000
}

# Permanently delete
POST /api/trash/permanent
{
  "doc_id": "abc-123",
  "namespace": "finance",
  "deleted_at_ms": 1706198400000
}
```

### CLI Commands

```bash
# List trash
stache list-trash --namespace finance

# Restore document
stache restore abc-123 --namespace finance --deleted-at-ms 1706198400000

# Permanent delete
stache delete-permanent abc-123 --namespace finance --deleted-at-ms 1706198400000
```

## Error Recovery

### REINGEST_VERSION Safety

When updating a file (REINGEST_VERSION), Stache:

1. Soft-deletes old version (moves to trash)
2. Ingests new version
3. **If ingestion fails**: Automatically restores old version from trash
4. **If ingestion succeeds**: New version active, old in trash

This prevents data loss from partial updates or ingestion errors.

### Example Scenario

```bash
# User uploads updated report.pdf
stache ingest report.pdf --namespace finance

# Behind the scenes:
# 1. Hash computed → different from existing
# 2. Old version → trash (doc_id: old-123)
# 3. New version ingestion starts
# 4. Enrichment fails (LLM error)
# 5. ErrorProcessor restores old-123 from trash
# 6. User sees error, but no data lost
```

## Configuration

### Feature Flags

All features enabled by default in `config.py`:

```python
# Deduplication
dedup_enabled: bool = True  # Set False to disable
soft_delete_enabled: bool = True  # Set False for hard delete
trash_retention_days: int = 30  # Days before auto-purge

# Workers
cleanup_job_enabled: bool = True  # Background vector cleanup
trash_purge_enabled: bool = True  # Scheduled auto-purge
```

### Environment Variables

Override in deployment:

```bash
# Disable features
export DEDUP_ENABLED=false
export SOFT_DELETE_ENABLED=false

# Adjust retention
export TRASH_RETENTION_DAYS=7  # 7-day retention

# Disable workers (manual cleanup only)
export CLEANUP_JOB_ENABLED=false
export TRASH_PURGE_ENABLED=false
```

### Rollback Strategy

Instant disable if issues arise:

```bash
# Emergency disable
export DEDUP_ENABLED=false
export SOFT_DELETE_ENABLED=false

# Restart API
# Behavior reverts to: no dedup, hard delete
```

## Architecture

### Components

**Middleware**:
- `IngestGuard`: Pre-enrichment deduplication check
- `ErrorProcessor`: Auto-restore on REINGEST_VERSION failure

**Providers**:
- `DocumentIndexProvider`: Identifier reservation, trash CRUD
- `VectorDBProvider`: Status filtering (hide soft-deleted vectors)

**Workers**:
- `CleanupWorker`: Async permanent delete (vector cleanup)
- `TrashPurgeWorker`: Scheduled enforcement of TTL

**Frontend**:
- `Trash.vue`: User-facing trash management UI

### Data Flow

```
┌─────────────────────────────────────────────────────┐
│ User uploads file (via Web/CLI/API)                 │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│ IngestGuard computes hash, checks for duplicate     │
├─────────────────────────────────────────────────────┤
│ • No existing doc → Allow (INGEST_NEW)              │
│ • Existing, same hash → Reject (SKIP)               │
│ • Existing, diff hash, source path → Allow          │
│   (REINGEST_VERSION, soft-delete old)               │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│ Pipeline runs enrichers, chunks, inserts vectors    │
└─────────────────┬───────────────────────────────────┘
                  │
         Success ─┼─ Failure
                  │
    ┌─────────────┴─────────────┐
    ▼                            ▼
┌───────────┐          ┌──────────────────────┐
│ Complete  │          │ ErrorProcessor       │
│ (active)  │          │ restores old doc     │
└───────────┘          └──────────────────────┘
```

### Provider Support

All providers support deduplication and trash:

| Provider | Deduplication | Trash/Restore | Status Filtering |
|----------|---------------|---------------|------------------|
| DynamoDB | ✅ (transactions) | ✅ (atomic) | ✅ |
| S3 Vectors | ✅ | ✅ | ✅ (metadata filters) |
| Qdrant | ✅ | ✅ | ✅ (payload filters) |
| Pinecone | ✅ | ✅ | ✅ (metadata filters) |
| MongoDB | ✅ | ✅ | ✅ (query filters) |

## Performance

### Benchmarks

- **Hash computation**: <100ms for 10MB file
- **Soft delete**: <300ms (DynamoDB transaction)
- **Restore**: <300ms (DynamoDB transaction)
- **Status filter overhead**: <50ms per query
- **Cleanup worker**: <5min per 100 documents

### Optimization Tips

1. **Deduplication saves cost**: Skip duplicate enrichment (~$0.01-0.05 per document)
2. **Guards run early**: Before expensive LLM enrichment
3. **Async cleanup**: Permanent delete doesn't block API response
4. **Batch processing**: Workers process multiple jobs efficiently

## Monitoring

### CloudWatch Metrics

Key metrics for production monitoring:

```python
# Deduplication
dedup.skip_count  # Duplicates caught
dedup.reingest_count  # Smart updates
dedup.hash_duration_ms  # Hash computation time

# Trash
trash.soft_delete_count  # Documents moved to trash
trash.restore_count  # Successful restorations
trash.purge_count  # Auto-purge executions
trash.cleanup_duration_ms  # Cleanup job time
```

### Logs

Important log entries:

```
INFO: Duplicate detected, skipping ingestion (hash=abc123, namespace=finance)
INFO: REINGEST_VERSION: updating doc_id=old-123 (hash mismatch)
WARNING: REINGEST_VERSION failed, restoring old version (doc_id=old-123)
INFO: Document restored from trash (doc_id=old-123, namespace=finance)
INFO: Cleanup job created (job_id=cleanup-456, chunk_count=47)
```

## FAQ

**Q: Can I disable deduplication but keep trash?**
A: Yes, set `DEDUP_ENABLED=false` and `SOFT_DELETE_ENABLED=true`

**Q: What happens to documents after 30 days in trash?**
A: Daily worker automatically purges them (permanent delete)

**Q: Can I change retention period?**
A: Yes, set `TRASH_RETENTION_DAYS` environment variable

**Q: What if I accidentally permanent delete?**
A: Cannot restore after permanent delete. Manual database recovery required.

**Q: Does deduplication work across namespaces?**
A: No, identifiers are scoped to namespace (same file in different namespaces is separate)

**Q: How much storage does trash use?**
A: Only metadata, vectors remain in database until permanent delete

**Q: Can I manually trigger trash purge?**
A: Yes, invoke `TrashPurgeWorkerFunction` Lambda directly

**Q: Does SKIP cost anything?**
A: No enrichment/embedding costs, only hash computation (~1ms) and database lookup

## Troubleshooting

### Duplicates Not Detected

**Symptom**: Same file uploaded multiple times, not detected as duplicate

**Causes**:
1. `DEDUP_ENABLED=false` - Check config
2. Different source paths (CLI) - Use same path for updates
3. Web upload with different filename - Expected behavior (conservative strategy)

**Solution**: Ensure `DEDUP_ENABLED=true` and consistent source paths

### Restore Failed

**Symptom**: "Document not found in trash" error

**Causes**:
1. Already restored
2. Already permanently deleted
3. Auto-purged (>30 days)
4. Wrong `deleted_at_ms` timestamp

**Solution**: Check trash list for correct `deleted_at_ms` value

### Cleanup Worker Timeout

**Symptom**: Cleanup jobs stuck in pending state

**Causes**:
1. Large document (>1000 chunks)
2. Worker timeout too short
3. VectorDB slow response

**Solution**: Increase Lambda timeout in `template.yaml` or reduce batch size

## Migration Guide

### Existing Deployments

No migration required! Features work with existing data:

1. **Deploy** with features enabled (default)
2. **Existing vectors** without status field treated as active
3. **New vectors** get status="active" automatically
4. **Gradual rollout** via feature flags

### Testing in Staging

```bash
# Enable in staging first
export DEDUP_ENABLED=true
export SOFT_DELETE_ENABLED=true

# Test workflows
1. Upload duplicate → verify SKIP
2. Update file → verify REINGEST_VERSION
3. Delete doc → verify appears in trash
4. Restore doc → verify searchable
5. Permanent delete → verify cleanup job created

# Monitor logs for 3 days before prod rollout
```

## Additional Resources

- [API Reference](api-reference.md) - Complete API documentation
- [Document Management](document-management.md) - Web UI guide
- [Middleware Plugin Guide](../packages/stache-ai/docs/middleware-plugin-guide.md) - Custom middleware
- [Implementation Plan](../claude-stache-files/plans/20260125-dedup-trash-v2.md) - Technical details

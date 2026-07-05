# Stache 0.2 — Async Ingestion Backbone

**Release focus**: a portable, provider-abstracted ingestion pipeline with a
uniform submit → poll contract. The synchronous in-process tier remains the
default and requires no configuration; an AWS async tier (S3 + SQS + DynamoDB)
is available by installing plugins and flipping provider names.

| Package | Version | Notes |
|---------|---------|-------|
| `stache-ai` | 0.2.0 | Ingestion backbone, `/api/ingest` + jobs API, empty-extraction guard |
| `stache-ai-aws` | 0.2.0 | S3 blob store, SQS queue, S3 presign intake, worker/reaper Lambda entrypoints |
| `stache-ai-dynamodb` | 0.1.6 | `DynamoJobStore` (durable job records, atomic claims) |
| `stache-ai-s3vectors` | 0.1.4 | Empty-array metadata fix |

---

## Plugin Architecture

### Five new entry point groups

The ingestion backbone is built on five seams, each a provider group
discoverable via entry points (same registry as LLM/vectordb/namespace
providers):

| Group | Seam | Built-in (core) | AWS plugin |
|-------|------|-----------------|------------|
| `stache.ingest_queue` | `QueueProvider` — hand off a job for processing | `inline` (awaits worker in-process) | `sqs` |
| `stache.ingest_jobstore` | `JobStore` — persist job records | `ephemeral`, `sqlite` | `dynamodb` |
| `stache.ingest_blob` | `BlobStore` — retain original files | `null`, `filesystem` | `s3` |
| `stache.ingest_intake` | `IntakeProvider` — admission + presigned upload | `inline` | `s3presign` |
| `stache.ingest_notifier` | `Notifier` — job lifecycle events | `null` | (future: eventbridge) |

Registering a provider from an external package:

```toml
[project.entry-points."stache.ingest_queue"]
redis = "my_package.queue:RedisQueue"
```

Selection is config-only: `INGEST_QUEUE_PROVIDER=redis`. Unknown names raise a
clear error listing what is installed.

### Core is deployment-agnostic

`stache-ai` core contains **no cloud-provider code, config, or entrypoints**.
Everything AWS-specific lives in the plugin packages:

- `stache_ai_aws.sqs_worker.lambda_handler` — SQS-triggered worker Lambda
  (handles both direct job-id records and S3 object-created events, including
  the producer-drop path driven by `x-amz-meta-stache-*` object metadata).
- `stache_ai_aws.reaper.lambda_handler` — scheduled wrapper over the core
  provider-agnostic `stache_ai.ingestion.reaper.reap_stuck_jobs()`.
- `stache_ai_aws.settings.AwsIngestSettings` — env-backed settings for the AWS
  tier. Resolution order: an attribute on the injected config object wins
  (used by tests/embedders), otherwise the environment / `.env`.

Plugin authors targeting other backends implement the same seams plus their own
queue-consumer entrypoint; core never needs to change.

### JobStore contract: idempotent claims

Async tiers deliver the same job more than once by design (at-least-once
queues; blob-backed jobs fire both a direct enqueue and an object-created
event). Processing is gated on `JobStore.claim(job_id, from_statuses=...)` —
a compare-and-set that exactly one caller wins. The base-class default is a
non-atomic get+update (fine for the single-process sync tier); durable
jobstores **must** override it with an atomic conditional write, as
`DynamoJobStore` does.

---

## API Changes

### New: unified ingestion endpoint

`POST /api/ingest` — one contract for all tiers. Provide exactly one of:

- `text` — inline note (with optional `chunking_strategy`)
- `data_base64` — small file bytes (validated base64)
- `upload: true` + `filename` — presigned-upload flow: returns `upload_url` +
  `required_headers`; the client PUTs the file directly to blob storage and
  the object-created event drives ingestion. Returns 400 on the sync tier
  (no presign support). `required_headers` carries **every** header folded into
  the storage signature — `Content-Type` plus the pinned `x-amz-meta-stache-*`
  metadata — and the client must echo all of them verbatim on the PUT or the
  storage backend rejects it (SignatureDoesNotMatch).

Text/base64 submissions larger than `MAX_INGEST_TEXT_BYTES` are rejected with
**413**.

Optional `wait: true` blocks server-side until the job is terminal (bounded by
`INGEST_WAIT_DEFAULT_TIMEOUT`, default 25s). Response is the job record:
**200** if terminal (sync tier is always terminal), **202** if queued.

### New: job status endpoints

- `GET /api/jobs/{job_id}` — single job. Scoped to the requester; returns 404
  (not 403) on other users' jobs to avoid leaking existence.
- `GET /api/jobs?status=&limit=&cursor=` — the requester's jobs, newest first.
  Returns an opaque `cursor`; pass it back as the `cursor` query param for the
  next page. `limit` is validated (1–200).

Job statuses: `queued`, `uploading`, `processing`, `done`, `skipped` (dedup
hit), `failed`, `awaiting_review`, `cancelled`. Terminal = done / skipped /
failed / cancelled. Records carry `doc_id`, `chunks_created`, `error_detail`,
`source` (`cli | web | dropbox | producer | api`), and timestamps.

### Changed endpoints

- `POST /api/capture` now routes through the same `IngestionService` in
  wait-mode instead of calling the pipeline directly. The legacy response
  shape is preserved; `job_id` and `status` fields are added. If wait-mode
  times out with the job still non-terminal, the response is honest — `success:
  true` with `action: "processing"` and a `job_id`/`status` to poll — rather
  than claiming a completed ingest with a null `doc_id`.
- `POST /api/upload` returns **422** with an actionable message when a file
  yields no extractable text (empty, scanned/image-only, or corrupt —
  previously a generic 500). See `EmptyExtractionError` below.

### Request principals

`requested_by` is extracted from the API Gateway JWT authorizer claims
(Cognito `sub`), supporting both HTTP API v2 and REST API event shapes; it
falls back to `"anonymous"` off-Lambda. Client-supplied identity is never
trusted. Namespace write authorization is a deliberate no-op hook
(`auth.assert_can_write`) to be enforced in a follow-up.

### Empty-extraction guard

`stache_ai.types.EmptyExtractionError` (subclasses `ValueError`) is raised when
ingestion receives no meaningful text. Previously an empty extraction sailed
through and produced a healthy-looking `active` document with a hallucinated
summary. Sync routes map it to 4xx; the async worker records a `failed` job
with the reason.

---

## Configuration

### New core settings (all defaults are inert — sync tier)

| Setting | Default | Purpose |
|---------|---------|---------|
| `INGEST_QUEUE_PROVIDER` | `inline` | Queue seam provider |
| `INGEST_JOBSTORE_PROVIDER` | `ephemeral` | Job store (`sqlite` for restart-safe local) |
| `INGEST_BLOB_PROVIDER` | `null` | Original-file retention (`filesystem` for local) |
| `INGEST_INTAKE_PROVIDER` | `inline` | Intake / presign |
| `INGEST_NOTIFIER_PROVIDER` | `null` | Job event notifier |
| `INGEST_BLOB_ROOT` | `/tmp/stache-originals` | Filesystem blob root |
| `INGEST_JOBSTORE_SQLITE_PATH` | `/tmp/stache-jobs.db` | SQLite job store path |
| `INGEST_REAPER_STUCK_MINUTES` | `30` | Stuck-job TTL before the reaper fails them |
| `INGEST_WAIT_DEFAULT_TIMEOUT` | `25.0` | Server-side wait-mode ceiling (seconds) |
| `INGEST_WAIT_POLL_INTERVAL` | `0.5` | Wait-mode poll interval |
| `INGEST_PRODUCER_DROPS_ENABLED` | `true` | Accept raw S3 producer drops (objects landing without a pre-created job). See the trust note below. |

### Plugin-owned settings (NOT in core `Settings`)

Read by the plugin packages from the environment (same names a deployment
already sets as Lambda env vars):

| Env var | Read by | Purpose |
|---------|---------|---------|
| `INGEST_BLOB_S3_BUCKET` / `INGEST_BLOB_S3_PREFIX` | `stache-ai-aws` | Originals bucket / key prefix (prefix default `originals`) |
| `INGEST_QUEUE_SQS_URL` | `stache-ai-aws` | Ingestion queue URL |
| `INGEST_INTAKE_S3_PRESIGN_EXPIRY` | `stache-ai-aws` | Presigned PUT expiry (default 1500s). **Must be < `INGEST_REAPER_STUCK_MINUTES`×60** (default 1800s): a client that uploads after the reaper has already failed the `UPLOADING` job would be silently dropped. |
| `INGEST_JOBSTORE_DYNAMODB_TABLE` | `stache-ai-dynamodb` | Job records table |

On DynamoDB deployments the effective inline-text cap is the smaller of
`MAX_INGEST_TEXT_BYTES` (10MB default) and the jobstore's 350KB inline-payload
budget (headroom under DynamoDB's 400KB item limit). Oversized text is rejected
at submit with **413**, not a 500 on the backend write.

### Producer drops are trusted

Raw S3 producer drops (objects arriving in the originals bucket under the blob
prefix without a pre-created job) derive namespace and `requested_by` from
producer-asserted `x-amz-meta-stache-*` object metadata — this is **not**
authenticated identity. The bucket write policy is the only boundary on this
path: a producer with write access is fully trusted and can set any
`requested_by`/`namespace`. Set `INGEST_PRODUCER_DROPS_ENABLED=false` to reject
this path entirely in deployments that require verified callers.

Non-ASCII filenames are percent-encoded into `x-amz-meta-stache-filename` (S3
metadata must be ASCII / ISO-8859-1 so the browser can echo the signed header
back on the PUT); the producer path unquotes them on read. Producers may
therefore tag objects with either a plain or a percent-encoded filename.

---

## CLI / MCP

No changes in 0.2. `stache ingest` and the MCP tools continue to use the
existing endpoints, which now run through the ingestion backbone server-side
(sync tier: responses are unchanged and already terminal). A follow-up can
teach the CLI the presign + poll flow for large files on async deployments.

## Frontend

- New **Jobs** page (`/jobs`): the requester's upload jobs with status,
  auto-polling of active jobs.
- Capture page submits through the job API and surfaces job status.
- `api/client.js` gains `submitIngest`, `getJob`, `listJobs`,
  `pollJob` (exponential backoff), and `uploadViaPresign` (presign → direct
  PUT → poll; deliberately bypasses the authed axios instance for the
  storage PUT).

## Deployment (stache-serverless)

New resources: originals bucket, ingest SQS queue (+ DLQ redrive), ingest jobs
DynamoDB table, worker Lambda (SQS-triggered, partial-batch failures), reaper
Lambda (5-minute schedule). Handler paths:

```
IngestWorkerFunction:  stache_ai_aws.sqs_worker.lambda_handler
IngestReaperFunction:  stache_ai_aws.reaper.lambda_handler
```

## Breaking / Behavior Changes

1. **Lambda handler paths moved** (deployers): `stache_ai.ingestion.sqs_worker`
   and `stache_ai.ingestion.reaper.lambda_handler` no longer exist in core —
   update handlers to the `stache_ai_aws.*` paths (template.yaml already
   updated).
2. **AWS ingest settings left core `Settings`**: `settings.ingest_blob_s3_bucket`,
   `ingest_blob_s3_prefix`, `ingest_queue_sqs_url`,
   `ingest_jobstore_dynamodb_table`, `ingest_intake_s3_presign_expiry` are no
   longer attributes on the core config object. Env var names are unchanged,
   so deployments need no env changes; only code that read these off
   `stache_ai.config.settings` must switch to the plugin settings.
3. **`POST /api/upload`** returns 422 (was 500) for files with no extractable
   text; **empty text ingest now fails** with `EmptyExtractionError` instead of
   silently storing an empty document.
4. **S3 Vectors metadata**: empty arrays are dropped rather than failing the
   whole `PutVectors` call; hierarchical chunking omits empty `headings` /
   `doc_item_labels` keys accordingly (filter expressions on those keys should
   use `exists`-style semantics, not empty-array equality).
5. **Capture response** gains `job_id` and `status` fields (additive; existing
   fields preserved).

## Other Fixes

- Concept-index resolution failures (enterprise add-on installed but
  misconfigured) are now logged at ERROR instead of silently skipping concept
  extraction; a missing enterprise package remains silent.
- Batch dedup (`skipped`) results surface as job status `skipped` rather than
  a success with zero chunks.

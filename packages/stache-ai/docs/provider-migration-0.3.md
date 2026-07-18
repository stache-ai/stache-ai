# Provider Migration Guide: 0.3

This guide is for authors of **provider packages** (vector DBs, document
indexes, namespace stores, rerankers, ingestion seams) and **middleware/plugin**
authors extending stache-ai. It covers the new seams introduced in stache-ai
0.3.0 and the concrete signature changes you need to make to stay compatible.

None of this introduces multi-user policy into core. Every seam described here
is opaque at the core level — core threads values through and enforces
nothing on its own. Deployment-specific behavior (scoping, quotas, org
structure, whatever) lives entirely in packages that plug into these seams.

## 1. The `context=` kwarg contract

Every data method on `VectorDBProvider`, `DocumentIndexProvider`,
`NamespaceProvider`, and `RerankerProvider` now accepts an additional
`context` parameter:

```python
def search(
    self,
    query_vector: list[float],
    top_k: int = 5,
    filter: dict[str, Any] | None = None,
    namespace: str | None = None,
    context: "RequestContext | None" = None,
) -> list[dict[str, Any]]:
    ...
```

**Contract**:

- **Accept it.** If you subclass any of these ABCs, add `context=None` to every
  overridden method's signature. The base classes already declare it, so
  omitting it from your override is a signature mismatch, not an error you'll
  see immediately — it just means core's `context=context` keyword call will
  raise a `TypeError` at the call site.
- **Default is always `None`.** Never make it required.
- **Treat it as keyword-only.** Core always calls it as `context=context`. The
  base ABC signatures place it last with a plain default (not behind a `*` in
  every case), but you should not depend on its positional slot — put it after
  your own parameters and always invoke it by keyword in your own code.
- **You may ignore it.** Every first-party provider (S3 Vectors, DynamoDB,
  MongoDB, Qdrant, Pinecone, Redis, SQLite, Cohere/Ollama rerankers) accepts
  `context` and does nothing with it. That's a legitimate implementation.
- **What it is.** `context` is a `stache_ai.middleware.context.RequestContext`
  (or `None` when called outside a request — CLI, tests, workers that haven't
  been wired up). It carries `request_id`, `user_id`, `timestamp`, `namespace`,
  and an opaque `custom: dict` extension slot. Deployment-specific packages can
  read `context.custom` to make provider-level decisions (e.g. routing writes
  to a per-caller prefix); core and first-party providers never do.

If your provider wants to act on identity, read `context.custom["principal"]`
when present (the identity middleware stashes the full `Principal` there —
see §4) rather than inventing your own side channel.

## 2. `scan_by_metadata` and the `metadata_scan` capability

`VectorDBProvider` gained a new method:

```python
def scan_by_metadata(
    self,
    filter: dict[str, Any] | None = None,
    fields: list[str] | None = None,
    namespace: str | None = None,
    context: "RequestContext | None" = None,
) -> list[dict[str, Any]]:
    """Full-collection scan, unbounded, unlike list_by_filter."""
    raise NotImplementedError(...)
```

It exists to replace API routes that previously reached past the provider
abstraction into a specific provider's raw client (this happened with Qdrant's
`scroll` API for maintenance operations — orphaned-chunk cleanup, summary
migration). If your provider can efficiently walk its whole collection with an
optional exact-match filter, implement `scan_by_metadata` and advertise it:

```python
@property
def capabilities(self) -> set[str]:
    return {"metadata_scan", ...}
```

Callers are expected to capability-check before calling:

```python
if "metadata_scan" not in vectordb.capabilities:
    raise HTTPException(400, "Provider does not support metadata scan")
records = vectordb.scan_by_metadata(filter={"status": "orphaned"})
```

If you don't implement it, leave the capability out of your `capabilities`
set — the base class's `NotImplementedError` is the correct default.

## 3. `principal=` on ingestion seams, and overridable `make_key`

Three ingestion-backbone ABCs in `stache_ai.ingestion.base` gained an opaque,
**syntactically keyword-only** `principal` parameter (this one *is* behind a
`*` in the base signatures):

```python
class JobStore(ABC):
    @abstractmethod
    def create(self, job: Job, *, principal: Principal | None = None) -> None: ...

    @abstractmethod
    def list(self, *, requested_by: str | None = None,
             status: JobStatus | None = None, limit: int = 50,
             cursor: str | None = None,
             principal: Principal | None = None) -> tuple[list[Job], str | None]: ...

class IntakeProvider(ABC):
    @abstractmethod
    def begin(self, *, job_id: str, filename: str, namespace: str,
              content_type: str, size: int, requested_by: str,
              metadata: dict,
              principal: Principal | None = None) -> IntakeTicket: ...
```

Same rules as `context`: accept it, default `None`, ignore it unless you have
a reason not to.

`BlobStore.make_key` is no longer a fixed convention — it's now an
**overridable method with a default implementation**:

```python
class BlobStore(ABC):
    def make_key(self, job_id: str, filename: str, *,
                 principal: Principal | None = None) -> str:
        """Compose the storage key for a job's original blob."""
        return f"{job_id}/{filename}"
```

The default (`{job_id}/{filename}`) is unchanged from before. Override it in
your `BlobStore` subclass if your deployment needs a different key layout —
e.g. prefixing by something derived from `principal` for per-prefix IAM
policies or retention rules. `principal` is opaque; core does not interpret
it, so any prefixing scheme is entirely up to your override.

**If you override `make_key`, you MUST also override its inverse,
`parse_job_id`** — the async ingestion path (a blob object-created event) knows
only the storage key and recovers the job it belongs to by calling it:

```python
class BlobStore(ABC):
    def parse_job_id(self, key: str) -> str:   # inverse of make_key
        return key.split("/")[0]
```

The round-trip `parse_job_id(make_key(job_id, filename)) == job_id` must hold.
Two further constraints, because this seam is stable from 0.3.0 on:

- `make_key` must be **pure and deterministic** in `(job_id, filename, principal)`
  — the presign intake and the job record derive the key independently and must
  agree, so no `uuid`/timestamp/clock in the key.
- If your override **prefixes** keys, ensure the blob store's object-created
  event notification is configured to cover that prefix, or uploads never reach
  the worker. (Core strips the configured blob-store prefix before calling
  `parse_job_id`, so your override sees the post-strip key.)

## 4. New entry-point groups: `stache.principal_extractor` and `stache.authorizer`

Two new pluggable seams, both fail-closed when configured (see §5).

### `stache.principal_extractor`

Replaces (or extends) how the caller's identity is derived from a request.
The default, `ApiGatewayClaimsExtractor`, reads API Gateway authorizer claims
and falls back to an anonymous principal.

```python
from stache_ai.identity import PrincipalExtractor, Principal, AuthenticationError

class MyJwtExtractor(PrincipalExtractor):
    def __init__(self, config=None):
        self._config = config

    def extract(self, request) -> Principal:
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        if not token:
            raise AuthenticationError("missing bearer token")
        claims = verify_and_decode(token)  # your verification logic
        return Principal(user_id=claims["sub"], claims=claims)
```

Register it:

```toml
[project.entry-points."stache.principal_extractor"]
my_extractor = "my_package:MyJwtExtractor"
```

Activate it with config: `PRINCIPAL_EXTRACTOR=my_extractor`. Raising
`AuthenticationError` from `extract()` becomes a 401 at the API layer — core
never swallows it into an anonymous principal once a non-default extractor is
configured.

### `stache.authorizer`

Enforces (or declines to enforce) policy on an operation. The default,
`AllowAllAuthorizer`, allows everything — the existing single-user posture.

```python
from stache_ai.identity import AuthorizationProvider, Principal, ForbiddenError

class MyAuthorizer(AuthorizationProvider):
    def __init__(self, config=None):
        self._config = config

    def authorize(self, principal: Principal, operation: str,
                  resource: dict | None = None) -> None:
        # operation is a neutral verb string, e.g. "ingest", "delete_document",
        # "read_pending". resource carries opaque keys like "namespace"/"owner"
        # when cheaply available. Raise to deny; return None to allow.
        if not my_policy_check(principal, operation, resource):
            raise ForbiddenError(f"{principal.user_id} cannot {operation}")
```

Register it:

```toml
[project.entry-points."stache.authorizer"]
my_authorizer = "my_package:MyAuthorizer"
```

Activate it with config: `AUTHORIZATION_PROVIDER=my_authorizer`. Every API
route now calls `authorize()` before doing any work, so implementing this one
entry point gives you enforcement across the whole surface without touching
routes.

## 5. Fail-closed plugin/provider loading

Before 0.3, a plugin or provider entry point that failed to load logged a
warning and was silently skipped. That is no longer true for anything
explicitly configured:

- A **configured** `PRINCIPAL_EXTRACTOR`, `AUTHORIZATION_PROVIDER`, or any
  other named provider/plugin that is installed but raises during
  instantiation now **aborts application startup** with a `RuntimeError`,
  instead of falling back silently.
- Entry points backed by a package that simply **isn't installed**
  (`ModuleNotFoundError`/missing optional dependency) still skip normally —
  that's expected and unchanged.
- A named provider that is installed and broken but **not the one you
  configured** no longer aborts startup — it is recorded and skipped so an
  unrelated third-party plugin can't brick a working deployment. You only see
  the abort when the *configured* name is the broken one (and then with its
  real load error).
- **Middleware groups are stricter**: middleware (`stache.enrichment`,
  `stache.result_processor`, `stache.chunk_observer`, …) runs as a discovered
  *set* with no name selection, so *any* installed-but-broken middleware aborts
  startup — a silently-dropped result filter or isolation middleware would
  otherwise fail open. Don't ship a middleware entry point you can't load.

Practically: if you ship a `stache.principal_extractor` or `stache.authorizer`
plugin, an exception in your `__init__` or first use will now stop the app
from starting in any deployment that configured it, rather than quietly
degrading to anonymous/allow-all. Make sure your constructor fails loudly and
early rather than lazily on first request, so operators see the problem at
deploy time.

## 6. Metadata sanitization and reserved keys

`stache_ai.sanitize.strip_reserved_metadata` now runs on caller-supplied
metadata at API boundaries, before routes/guards write their own
internal-control fields on top. It drops:

- Any key starting with `_` (the internal-control convention used for dedup
  state, transport fields, and similar).
- `content_hash` explicitly (the dedup identity value itself).

If your enrichment middleware or provider relies on a caller being able to set
an underscore-prefixed metadata key directly through the ingest API, that
path is now closed — those keys are server-set only. Set them from your own
middleware/provider code (which runs after sanitization), not by asking
callers to pass them in.

## 7. DynamoDB key-delimiter escaping (compatibility note)

If you maintain or operate the `stache-ai-dynamodb` provider: composite keys
(`PK`, `GSI1PK`, `GSI2PK`, and the trash-entry key) now escape `#` and `%` in
caller-controlled components (namespace, filename, source_path) via a small
`_esc()` helper (`%` → `%25`, `#` → `%23`, escaped in that order so the
encoding is unambiguous).

This closes a key-forgery hole: previously, a namespace or filename containing
an embedded `#` could make the composite key of one document collide with (or
be crafted to match) another document's or trash entry's key.

**Compatibility**: identifiers that never contained `#` or `%` are byte-for-byte
unchanged by `_esc()` — no migration needed for the common case. Rows whose
namespace, filename, or source_path already contained a raw `#` or `%`
character will compute a **different** key under 0.2.0 than the one they were
originally stored under, and will no longer be found by the normal
get/list/delete paths. If your deployment has such rows, re-key or migrate
them before upgrading — don't assume they'll keep working.

## 8. Removed context fields

`RequestContext.tenant_id` and the corresponding `QueryContext.tenant_id`
property have been removed. They were unused placeholder fields — nothing in
core read or wrote them. If your middleware referenced `context.tenant_id`,
switch to `context.custom`, which is the supported extension point for
deployment-specific scoping:

```python
# Before
scope = context.tenant_id

# After
scope = context.custom.get("my_package.scope")
```

`RequestContext.custom` is populated by core with at most one first-party key
(`"principal"`, the full `Principal` object, when the identity middleware ran)
and is otherwise yours to use — namespace your keys as
`context.custom["YourMiddleware.key"]` per the existing middleware-plugin
guide convention.

## 9. Job visibility and queued-work identity (`JobStore`)

Two new concrete (non-abstract) methods on the `JobStore` ABC — you inherit
working defaults, and may override either:

```python
def visible_to(self, job, principal) -> bool:
    # Default: principal is not None and job.requested_by == principal.user_id
    ...

def principal_for(self, job) -> Principal:
    # Default: Principal(user_id=job.requested_by)
    ...
```

`visible_to` gates the single-job fetch: `GET /api/jobs/{job_id}` returns 404
for an invisible job, byte-identical to a missing one, so overrides must be
pure predicates with no side effects or logging that could differ by case.
`principal_for` is called by the ingestion worker before its authorization
re-check; if your store stamps identity attributes at `create(job,
principal=...)` time, rehydrate them here so a plugged authorizer sees the
same claims the original caller carried. The worker places this principal on
`context.custom["principal"]` for the pipeline call.

If your store duck-typed the old protocol instead of subclassing `JobStore`,
subclass it now (the worker calls both methods).

`NamespaceProvider` also gained concrete, context-aware `get_ancestors` /
`get_path` base methods (parent walk over `get`). If you overrode these
before, add the keyword-only `context=None` parameter and forward it to any
`get` calls you make.

## 10. `context=` on `LLMProvider` and `EmbeddingProvider`

The 0.3 `context=` pass (§1) deferred the LLM and embedding provider families;
they are now threaded too, closing the loop so *every* provider data call can
see the optional request context.

`EmbeddingProvider` gained a **keyword-only** `context` on each data method:

```python
class EmbeddingProvider(ABC):
    @abstractmethod
    def embed(self, text: str, *, context: "RequestContext | None" = None) -> list[float]: ...

    @abstractmethod
    def embed_batch(self, texts: list[str], *, context: "RequestContext | None" = None) -> list[list[float]]: ...

    def embed_query(self, text: str, *, context: "RequestContext | None" = None) -> list[float]:
        return self.embed(text, context=context)
```

`LLMProvider` gained the same keyword-only `context` on `generate`,
`generate_with_model`, `generate_structured`, and `generate_with_tools`. The
two methods that already take a positional `context` — the RAG chunk list —
instead gained a keyword-only **`request_context`** so the two never collide:

```python
class LLMProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str, *, context: "RequestContext | None" = None, **kwargs) -> str: ...

    @abstractmethod
    def generate_with_context(
        self, query: str, context: list[dict[str, Any]],
        *, request_context: "RequestContext | None" = None, **kwargs,
    ) -> str: ...

    def generate_with_model(
        self, prompt: str, model_id: str,
        *, context: "RequestContext | None" = None, **kwargs,
    ) -> str: ...

    def generate_with_context_and_model(
        self, query: str, context: list[dict[str, Any]], model_id: str,
        *, request_context: "RequestContext | None" = None, **kwargs,
    ) -> str: ...
```

**Contract** — identical in spirit to §1, with two specifics:

- **Keyword-only.** Unlike the four ABCs in §1 (where `context` is
  positional-or-keyword), these are behind a `*` because the methods already
  carry `**kwargs`; a bare `context=None` before `**kwargs` would be
  swallowable and ambiguous. Core always calls `context=`/`request_context=`.
- **`request_context`, not `context`, on the two RAG methods.** On
  `generate_with_context`/`generate_with_context_and_model`, `context` is the
  retrieved chunk list and is unchanged; the request context is
  `request_context`.
- **Accept, default `None`, ignore is fine.** All first-party providers accept
  it and do nothing with it — the per-package providers (Bedrock, Anthropic,
  OpenAI, Cohere, Ollama, Mixedbread) as well as the `fallback`/`none`
  providers shipped in core (`stache_ai.providers.llm`/
  `stache_ai.providers.embeddings`) — except that where one method delegates
  to another (`generate_with_context` → `generate`,
  `generate_with_context_and_model` → `generate_with_model`, or the embedding
  fallback provider's `embed`/`embed_batch` → its wrapped primary/secondary
  provider), they **forward** the request context so a wrapping provider that
  *does* act on it sees it at the leaf call. If your override makes a nested
  call, forward it the same way.

**Why keyword-only matters for the drift guard.** A signature-presence test
proves the parameter exists; it does NOT prove a method forwards it on a nested
call. The test suite therefore also asserts propagation by object identity
through the known nested sites (the base `generate_with_model` /
`generate_with_context_and_model` defaults and the auto-split embedding
wrapper), and separately enumerates every concrete first-party subclass
shipped in-tree (`FallbackEmbeddingProvider`, `NoneLLMProvider`,
`FallbackLLMProvider`) so a subclass override that drops the kwarg — not just
an ABC that never declared it — gets caught too. Per-provider-package
concretes (Bedrock, Anthropic, etc.) are covered by their own package test
suites. If you add a provider method that makes a nested data call, add an
identity-propagation assertion for it — do not rely on the signature check
alone.

The pipeline threads its request context through every embed/generate call
site (ingest, query synthesis, summary regeneration), and the auto-split
embedding wrapper (`AutoSplitEmbeddingWrapper`) forwards it into the wrapped
provider's `embed`/`embed_batch`.

## 11. `LimitExceededError` → 429 (with `Retry-After`)

A new neutral exception in `stache_ai.identity`, alongside `ForbiddenError`:

```python
from stache_ai.identity import LimitExceededError

# Raise from anywhere a configured limit rejects an operation — an IngestGuard,
# a QueryProcessor, a provider, or an authorizer:
raise LimitExceededError("try again shortly")
```

The API layer maps it to **`429 Too Many Requests`** with a `Retry-After: 60`
header, the same JSON `{"detail": ...}` shape as the 401/403 handlers. This
mirrors the existing `ForbiddenError` → 403 seam exactly:

- Core attaches **no meaning** to *which* limit was hit. There are no fields
  and no message contract — the `detail` string is passed through verbatim; OSS
  never composes it.
- Routes with a blanket `except Exception` re-raise it (`except
  LimitExceededError: raise`) ahead of the catch-all, so a rejection raised
  mid-request reaches the app's 429 handler instead of being rewritten into a
  500. A static AST sweep test enforces this re-raise (next to the
  `ForbiddenError` one) on every route module.

Use it when you want correct "try again later" HTTP semantics — `429` is what
SDKs and proxies honor for backoff, unlike `403`. Non-HTTP front ends (CLI,
MCP, worker) don't map it; the exception propagates and each maps as it sees
fit, exactly as with `ForbiddenError`. Because a `stache.routes` plugin only
contributes an `APIRouter` and never receives the `app`, this handler must live
in core — a proprietary package cannot register a global exception handler
itself.

## Summary of signature changes for provider authors

| ABC | Change |
|---|---|
| `VectorDBProvider` | All 11 data methods gained `context=None`; new `scan_by_metadata()`; new `"metadata_scan"` capability |
| `DocumentIndexProvider` | All 23 data methods gained `context=None` |
| `NamespaceProvider` | All 7 methods gained `context=None` |
| `RerankerProvider` | `rerank()` gained `context=None` |
| `EmbeddingProvider` | `embed`/`embed_batch`/`embed_query` gained keyword-only `context=None` (§10) |
| `LLMProvider` | `generate`/`generate_with_model`/`generate_structured`/`generate_with_tools` gained keyword-only `context=None`; `generate_with_context`/`generate_with_context_and_model` gained keyword-only `request_context=None` (§10) |
| `JobStore` | `create()`, `list()` gained keyword-only `principal=None` |
| `IntakeProvider` | `begin()` gained keyword-only `principal=None` |
| `BlobStore` | `make_key()` is now overridable (keyword-only `principal=None`); new paired inverse `parse_job_id()` — override both or neither (§3) |
| `IntakeTicket` | new optional `blob_key` field — the intake reports the key it presigned so the job record uses the identical one |

See also: `docs/middleware-plugin-guide.md` for the pre-existing middleware
entry points (`stache.enrichment`, `stache.query_processor`, etc.) — the
`context`/`custom` conventions described there are unchanged by this release.

# Resilience Module

## Overview

The resilience module provides shared utilities for handling failures and transient errors across HTTP-based providers. It prevents cascading failures by implementing circuit breaker patterns, automatic retries with exponential backoff, and connection pooling. These utilities are used by embedding providers (Mixedbread, Ollama), language model providers, and any external API integration.

The module ensures that temporary service disruptions don't cause application failures while preventing wasted resource usage against unavailable services.

## Components

### 1. Circuit Breaker

**Purpose**: Prevent cascading failures by detecting repeated failures and temporarily blocking requests to unhealthy services.

The circuit breaker implements a three-state finite state machine that monitors request success/failure patterns and actively rejects requests when a service is unavailable, reducing unnecessary network calls and resource consumption.

#### States

- **CLOSED**: Normal operation. Requests pass through to the service. Tracks failure count.
- **OPEN**: Service detected as unavailable. Circuit breaker rejects all requests immediately, returning `RuntimeError: "Circuit breaker OPEN - rejecting request"`. Waits for recovery timeout.
- **HALF_OPEN**: Recovery attempt in progress. Allows a limited number of test requests (default: 3) to check if the service has recovered. One failure transitions back to OPEN; successful tests transition to CLOSED.

#### State Transitions

```
CLOSED -- (failure_count >= threshold) --> OPEN
OPEN  -- (timeout elapsed) --> HALF_OPEN
HALF_OPEN -- (success_count >= half_open_max_calls) --> CLOSED
HALF_OPEN -- (any failure) --> OPEN
```

#### Configuration

- **`failure_threshold`** (default: 15): Number of consecutive failures required to transition from CLOSED to OPEN. Higher values tolerate more failures before protection kicks in.
- **`timeout`** (default: 60.0 seconds): Recovery window. Time to wait in OPEN state before attempting recovery in HALF_OPEN state.
- **`half_open_max_calls`** (default: 3): Number of test requests allowed in HALF_OPEN state. Must succeed consecutively to return to CLOSED.

#### Usage Example

```python
from stache_ai.providers.resilience.circuit_breaker import CircuitBreaker

# Create circuit breaker
cb = CircuitBreaker(
    threshold=15,
    timeout=60.0,
    half_open_max_calls=3
)

# Check if request should be attempted
if cb.can_attempt():
    try:
        # Make API request
        result = api.call_endpoint()
        cb.record_success()
        return result
    except Exception as e:
        cb.record_failure()
        raise
else:
    # Circuit is OPEN - service unavailable
    raise RuntimeError("Service temporarily unavailable")

# Get current state and statistics
state = cb.get_state()  # CircuitState.CLOSED, .OPEN, or .HALF_OPEN
stats = cb.get_stats()  # {"state": "closed", "failure_count": 5, ...}
```

#### Thread Safety

The `CircuitBreaker` class is thread-safe. All state transitions and checks use `threading.Lock` to prevent race conditions in multi-threaded environments.

---

### 2. HttpClient & HttpClientFactory

**Purpose**: Centralized HTTP client management with built-in resilience features (connection pooling, automatic retry, circuit breaker integration). Used by all REST API-based providers.

#### Features

- **Connection Pooling**: Reuses TCP connections via `httpx.Client` for efficiency
- **Automatic Retry**: Exponential backoff with jitter for transient failures
- **Circuit Breaker Integration**: Prevents requests to unavailable services
- **Async Support**: Both synchronous and asynchronous operations for streaming responses
- **Thread-Safe Factory**: Prevents duplicate client creation across threads
- **Request Tracing**: Unique request IDs in logs for tracking request lifecycles

#### HttpClientConfig

Configuration dataclass with all resilience settings for HTTP clients.

**Connection Settings:**
- `base_url` (required): Base URL for the API (e.g., `"https://api.mixedbread.com/v1"`)
- `headers` (required): HTTP headers to include in all requests (e.g., auth tokens)

**Timeout Settings (seconds):**
- `default_timeout` (default: 60.0): Overall request timeout
- `connect_timeout` (default: 10.0): TCP connection establishment timeout
- `write_timeout` (default: 10.0): Time to send request body
- `pool_timeout` (default: 5.0): Time to acquire connection from pool

**Connection Pool Limits:**
- `max_connections` (default: 50): Total connections in pool
- `max_keepalive_connections` (default: 20): Persistent connections to keep alive
- `keepalive_expiry` (default: 30.0): How long to keep idle connections before closing

**Retry Configuration:**
- `max_retries` (default: 3): Number of retry attempts after initial failure
- `retry_base_delay` (default: 1.0): Initial delay between retries (seconds)
- `retry_max_delay` (default: 10.0): Maximum delay cap for exponential backoff

**Circuit Breaker Configuration:**
- `circuit_breaker_threshold` (default: 15): Failures before opening circuit
- `circuit_breaker_timeout` (default: 60.0): Recovery window (seconds)
- `circuit_breaker_half_open_max_calls` (default: 3): Test requests in half-open state

All settings are validated in `__post_init__()` to ensure valid configurations.

#### Usage Example

```python
from stache_ai.providers.resilience.http_client import HttpClientFactory, HttpClientConfig

# Create configuration
config = HttpClientConfig(
    base_url="https://api.mixedbread.com/v1",
    headers={
        "Authorization": "Bearer your-api-key",
        "Content-Type": "application/json"
    },
    default_timeout=60.0,
    max_retries=3,
    retry_base_delay=1.0,
    circuit_breaker_threshold=10,
    circuit_breaker_timeout=60.0
)

# Get or create shared client for provider
client = HttpClientFactory.get_client("mixedbread", config)

# Make requests with automatic retry and circuit breaker
response = client.post(
    "/embeddings",
    json={"model": "mxbai-embed-large-v1", "input": ["text1", "text2"]}
)

# Check circuit breaker state
state = client.circuit_breaker.get_state()

# Get client statistics
stats = client.get_stats()
```

#### HTTP Methods

**Synchronous (blocking):**
- `post(endpoint, json, timeout=None)`: Sends POST request
- `get(endpoint, timeout=None)`: Sends GET request

**Asynchronous (non-blocking):**
- `apost(endpoint, json, timeout=None)`: Async POST request
- `aget(endpoint, timeout=None)`: Async GET request
- `stream_post(endpoint, json, timeout=None)`: Streaming POST (yields response for chunked reading)

#### Retry Behavior

When a request fails:

1. **Check circuit breaker** before attempting: `can_attempt()` returns False if OPEN
2. **Execute operation**: Make HTTP request
3. **On success**: Record success, return result
4. **On failure**:
   - If final attempt: Record failure, raise exception
   - Otherwise: Sleep with exponential backoff + jitter, then retry

**Exponential backoff formula**:
```
delay = min(retry_base_delay * (2 ** attempt), retry_max_delay)
jitter = random.uniform(-0.5, 0.5) * delay  # ±50% random variance
final_delay = max(0, delay + jitter)
```

For example with base_delay=1.0, max_delay=10.0:
- Attempt 1 failure: Sleep ~1.0-1.5s, then retry
- Attempt 2 failure: Sleep ~1.5-3.0s, then retry
- Attempt 3 failure: Sleep ~3.0-7.0s, then retry
- Attempt 4 failure: Sleep ~5.0-10.0s, then raise

#### Streaming Example

```python
import asyncio

async def stream_embeddings(client, texts):
    async with client.stream_post(
        "/embeddings",
        json={"model": "model", "input": texts, "stream": True}
    ) as response:
        async for line in response.aiter_lines():
            chunk = json.loads(line)
            yield chunk
```

#### Factory Pattern

The `HttpClientFactory` uses a registry pattern (not singleton) to manage client instances:

- **One client per provider**: Each provider (ollama, mixedbread, etc.) gets its own cached `HttpClient` instance
- **Shared connection pool**: All requests from a provider reuse the same `httpx.Client`, reducing connection overhead
- **Shared circuit breaker**: All requests from a provider share the same circuit breaker state, so if Ollama is down, all Ollama requests are rejected consistently
- **Thread-safe creation**: Double-checked locking prevents race conditions during client creation

**Why registry instead of singleton**:
- Allows different providers to have independent circuit breaker states
- Prevents circuit breaker state from one provider affecting another
- Enables provider-specific timeout and retry configurations

#### Thread Safety

The `HttpClientFactory` uses double-checked locking:

```python
# Fast path: already created
if provider_name in cls._clients:
    return cls._clients[provider_name]

# Slow path: need to create
with cls._lock:
    if provider_name in cls._clients:  # Check again after acquiring lock
        return cls._clients[provider_name]

    # Create and cache new client
    client = HttpClient(config)
    cls._clients[provider_name] = client
    return client
```

This pattern prevents race conditions where multiple threads might try to create the same client simultaneously.

---

### 3. @with_retry Decorator

**Purpose**: Add retry logic to SDK-based provider methods (boto3, anthropic client, etc.) where you don't use `HttpClient`.

The decorator wraps any function with exponential backoff retry logic without requiring circuit breaker integration (which is for HTTP clients only).

#### Features

- **Configurable retry attempts**: Set max number of retries
- **Exception filtering**: Catch and retry only specific exception types
- **Exponential backoff with jitter**: Avoids thundering herd problem
- **Structured logging**: Logs each retry with attempt count and delay

#### Usage Example

```python
from stache_ai.providers.resilience.decorators import with_retry
from botocore.exceptions import ClientError

class MyBedrockProvider(LLMProvider):
    def __init__(self, settings: Settings):
        self.client = boto3.client('bedrock-runtime')

    @with_retry(
        max_retries=3,
        base_delay=1.0,
        max_delay=30.0,
        exceptions=(ClientError, TimeoutError),
        operation_name="Bedrock invoke_model"
    )
    def generate_text(self, prompt: str) -> str:
        response = self.client.invoke_model(
            modelId='anthropic.claude-3-sonnet-20240229-v1:0',
            body=json.dumps({"prompt": prompt})
        )
        return response['body'].read().decode()
```

#### Parameters

- **`max_retries`** (default: 3): Number of retry attempts after initial failure
- **`base_delay`** (default: 0.5): Initial delay in seconds between retries
- **`max_delay`** (default: 10.0): Maximum delay cap for exponential backoff
- **`exceptions`** (default: `(Exception,)`): Tuple of exception types to catch and retry. Only these exceptions trigger retries; others are raised immediately.
- **`operation_name`** (default: "operation"): Human-readable name for logging

#### Configuration Examples

**For transient network errors only:**
```python
@with_retry(
    max_retries=3,
    exceptions=(TimeoutError, ConnectionError),
    operation_name="API call"
)
def call_api():
    ...
```

**For AWS SDK errors with longer delays:**
```python
@with_retry(
    max_retries=5,
    base_delay=2.0,
    max_delay=60.0,
    exceptions=(ClientError,),
    operation_name="DynamoDB query"
)
def query_table():
    ...
```

**For database operations:**
```python
@with_retry(
    max_retries=2,
    base_delay=0.1,
    exceptions=(DatabaseError, TimeoutError),
    operation_name="Database insert"
)
def insert_record(record):
    ...
```

---

## Architecture

### Provider Integration Patterns

The resilience module supports two integration patterns depending on provider type:

#### Pattern A: HTTP-based Providers (REST APIs)

Use `HttpClientFactory` for providers that make HTTP requests (Mixedbread, OpenAI, Cohere, custom APIs).

**Characteristics**:
- Makes direct HTTP requests
- Benefits from connection pooling
- Wants shared circuit breaker state across all requests

**Implementation**:
```python
class MixedbreadEmbeddingProvider(EmbeddingProvider):
    def __init__(self, settings: Settings):
        config = HttpClientConfig(
            base_url="https://api.mixedbread.com/v1",
            headers={"Authorization": f"Bearer {settings.mixedbread_api_key}"},
            default_timeout=settings.mixedbread_timeout,
            max_retries=settings.mixedbread_max_retries,
            retry_base_delay=settings.mixedbread_retry_base_delay,
            retry_max_delay=settings.mixedbread_retry_max_delay,
            circuit_breaker_threshold=settings.mixedbread_circuit_breaker_threshold,
            circuit_breaker_timeout=settings.mixedbread_circuit_breaker_timeout,
        )
        self._client = HttpClientFactory.get_client("mixedbread", config)

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        response = self._client.post(
            "/embeddings",
            json={"model": self.model, "input": texts}
        )
        data = response.json()
        return [item["embedding"] for item in data["data"]]
```

#### Pattern B: SDK-based Providers (boto3, anthropic, etc.)

Use `@with_retry` decorator for providers using AWS SDKs or language-specific client libraries.

**Characteristics**:
- Uses SDK client (boto3, anthropic, etc.)
- Doesn't need connection pooling (SDK handles it)
- Wants retry logic on transient SDK errors

**Implementation**:
```python
from botocore.exceptions import ClientError
from stache_ai.providers.resilience.decorators import with_retry

class BedrockLLMProvider(LLMProvider):
    def __init__(self, settings: Settings):
        self.client = boto3.client('bedrock-runtime', region_name='us-east-1')

    @with_retry(
        max_retries=3,
        base_delay=1.0,
        exceptions=(ClientError, TimeoutError),
        operation_name="Bedrock generate"
    )
    def generate(self, prompt: str) -> str:
        response = self.client.invoke_model(
            modelId='anthropic.claude-3-sonnet-20240229-v1:0',
            body=json.dumps({"prompt": prompt})
        )
        return response['body'].read().decode()
```

### Factory Pattern Design

**Why use a factory instead of singletons**:

1. **Provider isolation**: Each provider has independent circuit breaker state. If Ollama is down, Bedrock isn't affected.

2. **Configuration flexibility**: Each provider can have different timeout, retry, and circuit breaker settings.

3. **Testing simplicity**: Tests can create multiple independent clients without conflicts.

**Factory lifecycle**:

```
HTTP Request
    ↓
HttpClientFactory.get_client("mixedbread", config)
    ↓
Is client cached? → Yes → Return cached client
    ↓ No
Create new HttpClient(config)
    ↓
Cache and return
    ↓
HttpClient.with_retry(operation, "name")
    ↓
Check circuit_breaker.can_attempt()
    ↓
Execute operation with retries
    ↓
Record success/failure
    ↓
Return result or raise
```

### Thread Safety Model

**Components and synchronization**:

| Component | Thread Safety | Mechanism |
|-----------|---------------|-----------|
| CircuitBreaker | Yes | `threading.Lock` on state transitions |
| HttpClient | Yes | `httpx.Client` is thread-safe; circuit breaker uses lock |
| HttpClientFactory | Yes | Double-checked locking for client creation |
| @with_retry decorator | Yes | Stateless function wrapper; no shared state |

**Safe patterns**:
- Multiple threads making requests through same HttpClient: Safe
- Multiple threads creating clients simultaneously: Safe (factory prevents duplicates)
- Multiple threads accessing circuit breaker state: Safe (guarded by lock)

---

## Configuration Settings

### Ollama Provider

In `config.py`:

```python
# Embedding
ollama_embedding_timeout: float = 90.0  # Increased for large batches
ollama_llm_timeout: float = 120.0  # LLM generation timeout
ollama_health_check_timeout: float = 5.0  # Health check timeout

# Retry
ollama_max_retries: int = 3
ollama_retry_base_delay: float = 1.0
ollama_retry_max_delay: float = 10.0

# Circuit breaker (increased for batch workloads)
ollama_circuit_breaker_threshold: int = 15
ollama_circuit_breaker_timeout: float = 60.0
ollama_circuit_breaker_half_open_max_calls: int = 3
```

**Rationale**:
- Higher timeout for embeddings (large batches take longer)
- Higher circuit breaker threshold (local service can handle burst failures)
- Quick health check timeout (no point waiting long for unhealthy local service)

### Mixedbread Provider

In `config.py`:

```python
# Timeout and retry
mixedbread_timeout: float = 60.0
mixedbread_max_retries: int = 3
mixedbread_retry_base_delay: float = 1.0
mixedbread_retry_max_delay: float = 10.0

# Circuit breaker
mixedbread_circuit_breaker_threshold: int = 10
mixedbread_circuit_breaker_timeout: float = 60.0
mixedbread_circuit_breaker_half_open_max_calls: int = 3
```

**Rationale**:
- Standard timeout for cloud APIs
- Lower circuit breaker threshold (external APIs can fail more frequently)
- Standard retry strategy for rate limits and transient errors

### Best Practices for Configuration

**For external cloud APIs** (Mixedbread, OpenAI, etc.):
- `timeout`: 30-60 seconds (APIs have their own timeouts)
- `max_retries`: 3 (handle rate limits and transient errors)
- `circuit_breaker_threshold`: 10-15 (external services can be flaky)
- `circuit_breaker_timeout`: 60 seconds (reasonable recovery window)

**For local services** (Ollama running locally):
- `timeout`: 90-120 seconds (can process large batches)
- `max_retries`: 3 (local network is reliable)
- `circuit_breaker_threshold`: 15-20 (local failures are rare)
- `circuit_breaker_timeout`: 60 seconds (quick recovery expected)

**For database operations** (using @with_retry):
- `max_retries`: 2-3 (databases rarely need many retries)
- `base_delay`: 0.5-1.0 seconds (quick recovery)
- `exceptions`: Specific error types (OperationalError, TimeoutError)

---

## Testing

### Resetting Factory State

**Always reset the factory in test fixtures** to prevent test pollution (one test's circuit breaker state affecting another).

```python
import pytest
from stache_ai.providers.resilience.http_client import HttpClientFactory

@pytest.fixture(autouse=True)
def reset_http_client_factory():
    """Reset factory before each test."""
    HttpClientFactory.reset()
    yield
    HttpClientFactory.reset()
```

The `autouse=True` parameter ensures this fixture runs automatically for every test without explicit inclusion.

### Mocking HttpClient

Mock at the `httpx.Client` level, not the factory:

```python
from unittest.mock import patch, MagicMock
from stache_ai.providers.resilience.http_client import HttpClientFactory, HttpClientConfig

@patch('stache.providers.resilience.http_client.httpx.Client')
def test_provider_request_retry(mock_client_class):
    """Test that provider retries on transient failures."""
    # Setup mock
    mock_instance = MagicMock()
    mock_client_class.return_value = mock_instance

    # First call fails, second succeeds
    mock_response = MagicMock()
    mock_response.json.return_value = {"data": [{"embedding": [0.1, 0.2]}]}
    mock_instance.post.side_effect = [
        ConnectionError("Network error"),
        mock_response
    ]

    # Test code
    config = HttpClientConfig(
        base_url="https://api.test.com",
        headers={},
        max_retries=3
    )
    client = HttpClientFactory.get_client("test", config)

    # Should succeed after retry
    response = client.post(
        "/embeddings",
        json={"input": ["test"]}
    )
    assert response.json() == {"data": [{"embedding": [0.1, 0.2]}]}
```

### Testing Circuit Breaker

```python
def test_circuit_breaker_opens_on_threshold():
    """Test that circuit opens after threshold failures."""
    from stache_ai.providers.resilience.circuit_breaker import CircuitBreaker, CircuitState

    cb = CircuitBreaker(threshold=3, timeout=60, half_open_max_calls=1)

    # Circuit is initially closed
    assert cb.get_state() == CircuitState.CLOSED
    assert cb.can_attempt() is True

    # Record failures
    cb.record_failure()
    cb.record_failure()
    assert cb.get_state() == CircuitState.CLOSED
    assert cb.can_attempt() is True

    # Third failure opens circuit
    cb.record_failure()
    assert cb.get_state() == CircuitState.OPEN
    assert cb.can_attempt() is False  # Requests rejected


def test_circuit_breaker_half_open_recovery():
    """Test circuit breaker recovery sequence."""
    from stache_ai.providers.resilience.circuit_breaker import CircuitBreaker, CircuitState
    import time

    cb = CircuitBreaker(threshold=1, timeout=0.1, half_open_max_calls=1)

    # Open the circuit
    cb.record_failure()
    assert cb.get_state() == CircuitState.OPEN

    # Wait for recovery timeout
    time.sleep(0.2)

    # Circuit transitions to HALF_OPEN
    assert cb.get_state() == CircuitState.HALF_OPEN
    assert cb.can_attempt() is True

    # Successful attempt closes circuit
    cb.record_success()
    assert cb.get_state() == CircuitState.CLOSED
```

### Testing @with_retry Decorator

```python
from stache_ai.providers.resilience.decorators import with_retry
from unittest.mock import MagicMock, patch

def test_retry_decorator_success_on_retry():
    """Test that decorator retries on exception."""
    attempt_count = 0

    @with_retry(max_retries=2, base_delay=0.01, exceptions=(ValueError,))
    def flaky_operation():
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count < 2:
            raise ValueError("Temporary failure")
        return "success"

    result = flaky_operation()
    assert result == "success"
    assert attempt_count == 2


def test_retry_decorator_exhausts_retries():
    """Test that decorator raises after exhausting retries."""
    @with_retry(max_retries=2, base_delay=0.01, exceptions=(ValueError,))
    def always_fails():
        raise ValueError("Permanent failure")

    with pytest.raises(ValueError, match="Permanent failure"):
        always_fails()


def test_retry_decorator_ignores_other_exceptions():
    """Test that decorator doesn't retry unspecified exceptions."""
    call_count = 0

    @with_retry(max_retries=3, exceptions=(ValueError,))
    def raises_type_error():
        nonlocal call_count
        call_count += 1
        raise TypeError("Not retryable")

    with pytest.raises(TypeError):
        raises_type_error()

    # Should fail immediately, not retry
    assert call_count == 1
```

---

## Monitoring and Debugging

### Circuit Breaker Statistics

```python
# Get detailed statistics
stats = client.circuit_breaker.get_stats()
print(stats)
# Output:
# {
#     'state': 'closed',
#     'failure_count': 2,
#     'success_count': 0,
#     'last_failure': '2024-01-15T10:23:45.123456'
# }
```

### Client Statistics

```python
# Get HTTP client configuration and state
stats = client.get_stats()
print(stats)
# Output:
# {
#     'base_url': 'https://api.mixedbread.com/v1',
#     'default_timeout': 60.0,
#     'max_connections': 50,
#     'max_keepalive_connections': 20,
#     'max_retries': 3,
#     'retry_base_delay': 1.0,
#     'retry_max_delay': 10.0,
#     'circuit_breaker_state': 'closed',
#     'circuit_breaker_threshold': 10
# }
```

### Logging

All components use Python's `logging` module. Enable DEBUG logging to see detailed request tracking:

```python
import logging

# Enable debug logging for resilience module
logging.getLogger('stache.providers.resilience').setLevel(logging.DEBUG)

# Example log output:
# DEBUG: POST /embeddings (timeout=60.0s)
# DEBUG: [a1b2c3d4] API call succeeded on first attempt
# INFO: [a1b2c3d4] API call attempt 2/4 failed: 504 Server Error. Retrying in 1.23s...
# WARNING: Circuit breaker OPEN - rejecting request
```

Each request gets a unique 8-character request ID for tracing through logs.

---

## Common Patterns

### Health Check Pattern

```python
class MyProvider(EmbeddingProvider):
    def __init__(self, settings: Settings):
        config = HttpClientConfig(
            base_url=settings.api_url,
            headers={"Authorization": f"Bearer {settings.api_key}"},
            default_timeout=5.0,  # Short timeout for health checks
        )
        self._client = HttpClientFactory.get_client("my-provider", config)

    def health_check(self) -> bool:
        """Check if service is healthy."""
        try:
            response = self._client.get("/health", timeout=5.0)
            return response.status_code == 200
        except Exception:
            return False
```

### Batch Processing Pattern

```python
def embed_large_batch(self, texts: List[str], batch_size: int = 100) -> List[List[float]]:
    """Process texts in batches with circuit breaker protection."""
    embeddings = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]

        try:
            response = self._client.post(
                "/embeddings",
                json={"input": batch},
                timeout=90.0  # Longer timeout for large batches
            )
            batch_embeddings = response.json()["data"]
            embeddings.extend(batch_embeddings)
        except RuntimeError as e:
            if "Circuit breaker OPEN" in str(e):
                raise ServiceUnavailableError("Service temporarily unavailable")
            raise
        except Exception as e:
            logger.error(f"Batch embedding failed: {e}")
            raise

    return embeddings
```

### Graceful Degradation Pattern

```python
def generate_with_fallback(self, text: str) -> str:
    """Try primary provider, fall back to secondary on circuit breaker open."""
    try:
        return self.primary_provider.generate(text)
    except RuntimeError as e:
        if "Circuit breaker OPEN" in str(e):
            logger.warning("Primary provider unavailable, using fallback")
            return self.fallback_provider.generate(text)
        raise
```

---

## Troubleshooting

### Circuit Breaker Keeps Opening

**Symptoms**: Requests constantly rejected, circuit breaker state alternates between OPEN and HALF_OPEN

**Causes**:
- Service is genuinely unavailable
- Timeout is too short for the operation
- Network connectivity issue

**Solutions**:
1. Check service health: `curl https://api-endpoint/health`
2. Increase timeout: `HttpClientConfig(default_timeout=120.0)`
3. Increase circuit breaker threshold: `circuit_breaker_threshold=20`
4. Check network connectivity and firewall rules

### Too Many Retries Causing Slowness

**Symptoms**: Requests taking unexpectedly long to complete

**Causes**:
- `max_retries` too high
- `retry_max_delay` too high
- exponential backoff accumulating

**Solutions**:
1. Reduce `max_retries`: Start with 2 instead of 3
2. Reduce delays: `retry_base_delay=0.5, retry_max_delay=5.0`
3. Check if circuit breaker should open sooner: Lower `circuit_breaker_threshold`

### Retry Decorator Not Retrying

**Symptoms**: Exceptions raised immediately without retry attempts

**Causes**:
- Wrong exception type specified in `exceptions` parameter
- Exception type doesn't match what's actually raised

**Solutions**:
1. Check exception type: Print `type(exception).__name__`
2. Use broader exception: `exceptions=(Exception,)` to catch all
3. Verify inheritance: `isinstance(error, SpecifiedException)`

### Connection Pool Exhaustion

**Symptoms**: `PoolTimeout` errors, "Cannot find connection in pool"

**Causes**:
- `max_connections` too low
- Connections not being released (missing context manager)
- Slow/hanging requests consuming all connections

**Solutions**:
1. Increase pool size: `max_connections=100`
2. Use context managers: `with client.post(...) as response:`
3. Set shorter timeout: `default_timeout=30.0`
4. Check for connection leaks in application code

---

## Related Documentation

- **Config Settings**: `/mnt/devbuntu/dev/stache/backend/stache/config.py` - All resilience configuration
- **Provider Examples**: `/mnt/devbuntu/dev/stache/backend/stache/providers/embeddings/` - Integration examples
- **Tests**: `/mnt/devbuntu/dev/stache/backend/tests/` - Testing patterns and fixtures

"""Forwarding-drift guards for request-context threading on providers.

The 0.3 review's key lesson: a *signature-presence* test (does the method
declare a ``context`` parameter?) MISSES the far more common regression — a
method that accepts ``context`` but DROPS it on a nested/sibling data call.
Every context-threading fix in 0.3 was a dropped forward, not a missing param.

So this module has THREE layers, and the first alone is deliberately
documented as insufficient:

1. **Signature guards** — every data method on the provider ABCs carries a
   keyword-only request-context parameter (``context``, or ``request_context``
   on the two LLM methods whose ``context`` already means the RAG chunk list).
   Presence only; says nothing about whether it is forwarded.

2. **Identity-propagation guards** — for the methods that make nested/sibling
   data calls, a sentinel object is threaded in and its IDENTITY is asserted on
   the inner call. This is what actually catches a drop. Extend this list
   whenever a provider method grows a nested data call.

3. **Concrete first-party subclass guards** — layers 1 and 2 above only ever
   introspected the ABCs (and base-default implementations exercised through
   test-local spy subclasses). That is exactly how ``FallbackEmbeddingProvider``
   (``providers/embeddings/fallback.py``) and ``NoneLLMProvider``
   (``providers/llm/none.py``) slipped through pre-freeze: both are SHIPPED
   concrete subclasses that simply dropped ``context``/``request_context``
   from their own overrides, and no test ever looked at *their* signatures.
   Layer 3 enumerates the concrete in-tree first-party subclasses of
   ``LLMProvider``/``EmbeddingProvider`` (discovered via ``__subclasses__()``)
   and bind-tests every data method they override.

   Scope note: this module owns the CORE in-tree concretes only — i.e. the
   classes that ship inside ``stache-ai`` itself (currently: the embedding and
   LLM ``fallback``/``none`` providers). Per-provider-PACKAGE concretes
   (``stache-ai-bedrock``, ``stache-ai-anthropic``, ``stache-ai-openai``,
   ``stache-ai-cohere``, ``stache-ai-ollama``, ``stache-ai-mixedbread``, etc.)
   are covered by their own package test suites, not here.
"""

import importlib
import inspect

import pytest

from stache_ai.providers.base import (
    DocumentIndexProvider,
    EmbeddingProvider,
    LLMProvider,
    NamespaceProvider,
    VectorDBProvider,
)
from stache_ai.providers.reranker import RerankerProvider
from stache_ai.rag.embedding_resilience import AutoSplitEmbeddingWrapper

# Identity sentinel — the same pattern the 0.3 context-forwarding fixes used.
CTX = object()


# ---------------------------------------------------------------------------
# Layer 1: signature guards (necessary, NOT sufficient — see module docstring)
# ---------------------------------------------------------------------------

# LLM/Embedding gained a keyword-only request context. On the two methods whose
# ``context`` positional already denotes the RAG chunk list, the request
# context is named ``request_context`` instead.
LLM_DATA_METHODS = {
    "generate": "context",
    "generate_with_context": "request_context",
    "generate_with_model": "context",
    "generate_with_context_and_model": "request_context",
    "generate_structured": "context",
    "generate_with_tools": "context",
}
EMBEDDING_DATA_METHODS = {
    "embed": "context",
    "embed_batch": "context",
    "embed_query": "context",
}


@pytest.mark.parametrize("method,param", LLM_DATA_METHODS.items())
def test_llm_data_methods_carry_keyword_only_context(method, param):
    sig = inspect.signature(getattr(LLMProvider, method))
    assert param in sig.parameters, f"LLMProvider.{method} missing '{param}'"
    p = sig.parameters[param]
    assert p.kind is inspect.Parameter.KEYWORD_ONLY, (
        f"LLMProvider.{method} '{param}' must be keyword-only"
    )
    assert p.default is None, f"LLMProvider.{method} '{param}' must default to None"


@pytest.mark.parametrize("method,param", EMBEDDING_DATA_METHODS.items())
def test_embedding_data_methods_carry_keyword_only_context(method, param):
    sig = inspect.signature(getattr(EmbeddingProvider, method))
    assert param in sig.parameters, f"EmbeddingProvider.{method} missing '{param}'"
    p = sig.parameters[param]
    assert p.kind is inspect.Parameter.KEYWORD_ONLY, (
        f"EmbeddingProvider.{method} '{param}' must be keyword-only"
    )
    assert p.default is None


# The four ABCs threaded in 0.3 keep ``context`` (positional-or-keyword) on
# every data method. get_name is the only non-data function.
_ALREADY_THREADED = [
    VectorDBProvider,
    DocumentIndexProvider,
    NamespaceProvider,
    RerankerProvider,
]
_SIGNATURE_SKIP = {"get_name"}


@pytest.mark.parametrize("abc", _ALREADY_THREADED, ids=lambda a: a.__name__)
def test_threaded_abcs_data_methods_carry_context(abc):
    for name, fn in inspect.getmembers(abc, predicate=inspect.isfunction):
        if name.startswith("_") or name in _SIGNATURE_SKIP:
            continue
        params = inspect.signature(fn).parameters
        assert "context" in params, f"{abc.__name__}.{name} dropped its 'context' param"
        assert params["context"].default is None, (
            f"{abc.__name__}.{name} 'context' must default to None"
        )


def test_signature_presence_is_not_forwarding():
    """A provider can DECLARE context and still drop it — presence != forwarding.

    This documents WHY the identity-propagation guards below exist. A method
    that accepts ``context`` but never passes it to its nested call satisfies
    every signature guard above yet silently breaks per-caller threading.
    """

    class DroppingEmbedder(EmbeddingProvider):
        def __init__(self):
            self.seen = "unset"

        def embed(self, text, *, context=None):
            self.seen = context
            return [0.0]

        def embed_batch(self, texts, *, context=None):
            return [[0.0] for _ in texts]

        def get_dimensions(self):
            return 1

        # BUG: overrides the base default and DROPS context on the nested call.
        def embed_query(self, text, *, context=None):
            return self.embed(text)  # <-- context not forwarded

    e = DroppingEmbedder()
    e.embed_query("q", context=CTX)
    # Signature guard would pass; identity is silently lost. Proven here.
    assert e.seen is None
    assert e.seen is not CTX


# ---------------------------------------------------------------------------
# Layer 2: identity-propagation guards for the known nested/sibling call sites
# ---------------------------------------------------------------------------


class _SpyEmbedder(EmbeddingProvider):
    """Records the context each data method actually received."""

    def __init__(self):
        self.embed_ctx = "unset"
        self.embed_batch_ctx = "unset"

    def embed(self, text, *, context=None):
        self.embed_ctx = context
        return [0.1, 0.2]

    def embed_batch(self, texts, *, context=None):
        self.embed_batch_ctx = context
        return [[0.1, 0.2] for _ in texts]

    def get_dimensions(self):
        return 2


class _SpyLLM(LLMProvider):
    """Records the context/request_context each leaf method received."""

    def __init__(self):
        self.generate_ctx = "unset"
        self.generate_with_context_rc = "unset"

    def generate(self, prompt, *, context=None, **kwargs):
        self.generate_ctx = context
        return "ok"

    def generate_with_context(self, query, context, *, request_context=None, **kwargs):
        self.generate_with_context_rc = request_context
        return "ok"


def test_embedding_base_embed_query_forwards_context():
    spy = _SpyEmbedder()
    spy.embed_query("q", context=CTX)
    assert spy.embed_ctx is CTX


def test_llm_base_generate_with_model_forwards_context():
    """Base default generate_with_model() must forward context into generate()."""
    spy = _SpyLLM()
    spy.generate_with_model("p", "model-x", context=CTX)
    assert spy.generate_ctx is CTX


def test_llm_base_generate_with_context_and_model_forwards_request_context():
    """Base default must forward request_context into generate_with_context()."""
    spy = _SpyLLM()
    spy.generate_with_context_and_model("q", [{"content": "c"}], "model-x", request_context=CTX)
    assert spy.generate_with_context_rc is CTX


def test_autosplit_wrapper_forwards_context_to_embed_batch():
    """The AutoSplit embedding wrapper must forward context to embed_batch."""
    spy = _SpyEmbedder()
    wrapper = AutoSplitEmbeddingWrapper(provider=spy, enabled=True)
    wrapper.embed_batch_with_splits(["a", "b"], context=CTX)
    assert spy.embed_batch_ctx is CTX


def test_autosplit_wrapper_forwards_context_on_single_embed_fallback():
    """When a batch fails with a context-length error, the per-text fallback
    embed() calls must still carry the context by identity."""

    class _AlwaysContextLength:
        def is_context_length_error(self, err):
            return True

    class _BatchFailsEmbedder(_SpyEmbedder):
        def embed_batch(self, texts, *, context=None):
            self.embed_batch_ctx = context
            raise RuntimeError("input too long for context window")

    spy = _BatchFailsEmbedder()
    wrapper = AutoSplitEmbeddingWrapper(
        provider=spy,
        max_split_depth=0,  # do not actually split; just fall back to embed()
        error_classifier=_AlwaysContextLength(),
        enabled=True,
    )
    wrapper.embed_batch_with_splits(["a"], context=CTX)
    assert spy.embed_ctx is CTX


# ---------------------------------------------------------------------------
# Layer 3: concrete first-party (in-tree) subclass guards
# ---------------------------------------------------------------------------
#
# Layers 1-2 only ever looked at the ABCs and at test-local spy/stub classes.
# A SHIPPED concrete subclass overriding a data method and dropping the
# context kwarg satisfies every guard above and still breaks at runtime. This
# is exactly how FallbackEmbeddingProvider.embed/embed_batch and
# NoneLLMProvider.generate_with_context/generate_with_context_and_model
# regressed pre-freeze.

# Import the in-tree first-party provider modules so their concrete classes
# are registered on EmbeddingProvider.__subclasses__() / LLMProvider.__subclasses__().
importlib.import_module("stache_ai.providers.embeddings.fallback")
importlib.import_module("stache_ai.providers.llm.fallback")
importlib.import_module("stache_ai.providers.llm.none")

# Data method -> keyword-only request-context parameter name (mirrors the
# LLM_DATA_METHODS / EMBEDDING_DATA_METHODS maps above).
_LLM_METHOD_CTX_PARAM = {
    "generate": "context",
    "generate_with_context": "request_context",
    "generate_with_model": "context",
    "generate_with_context_and_model": "request_context",
    "generate_structured": "context",
    "generate_with_tools": "context",
}
_EMBEDDING_METHOD_CTX_PARAM = {
    "embed": "context",
    "embed_batch": "context",
    "embed_query": "context",
}

# Sample positional args, keyed by method name, used only to satisfy
# ``inspect.signature(...).bind`` — never actually called, so provider
# construction/credentials are irrelevant.
_SAMPLE_ARGS = {
    "generate": ("a prompt",),
    "generate_with_context": ("a query", []),
    "generate_with_model": ("a prompt", "model-x"),
    "generate_with_context_and_model": ("a query", []),
    "generate_structured": ("a prompt", {}),
    "generate_with_tools": ([], []),
    "embed": ("some text",),
    "embed_batch": (["some text"],),
    "embed_query": ("some text",),
}
# Extra keyword args that mirror how rag/pipeline.py actually calls the
# ``_and_model``/``_with_model`` variants (by ``model_id=``, not positional).
_SAMPLE_KWARGS = {
    "generate_with_context_and_model": {"model_id": "model-x"},
    "generate_with_model": {},
}


def _in_tree_concrete_subclasses(base_cls):
    """Concrete (non-abstract) subclasses of base_cls shipped inside stache-ai.

    Discovered via ``__subclasses__()`` (recursively, in case of multi-level
    inheritance) and filtered to modules under ``stache_ai.providers`` so
    test-local spy/stub/dropping classes defined in *this* file (or any other
    test module) are never mistaken for shipped providers.
    """
    seen = set()
    stack = list(base_cls.__subclasses__())
    found = []
    while stack:
        cls = stack.pop()
        if cls in seen:
            continue
        seen.add(cls)
        stack.extend(cls.__subclasses__())
        if inspect.isabstract(cls):
            continue
        if not cls.__module__.startswith("stache_ai.providers"):
            continue
        found.append(cls)
    return found


def _bind_test_case_ids(cls):
    return cls.__name__


@pytest.mark.parametrize(
    "cls", _in_tree_concrete_subclasses(EmbeddingProvider), ids=_bind_test_case_ids
)
def test_in_tree_embedding_concrete_overrides_accept_context(cls):
    """Every data method a shipped EmbeddingProvider subclass overrides must
    still accept the request-context kwarg used by the pipeline — either as
    an explicit keyword-only param, or via **kwargs. A method that redeclares
    the method WITHOUT either satisfies no other guard in this file.
    """
    for method, param in _EMBEDDING_METHOD_CTX_PARAM.items():
        if method not in cls.__dict__:
            continue  # not overridden here; covered by the ABC/base guards
        fn = cls.__dict__[method]
        sig = inspect.signature(fn)
        args = _SAMPLE_ARGS[method]
        kwargs = {param: CTX, **_SAMPLE_KWARGS.get(method, {})}
        try:
            sig.bind(object(), *args, **kwargs)
        except TypeError as e:
            pytest.fail(
                f"{cls.__name__}.{method} does not accept '{param}=' "
                f"(pipeline calls it with '{param}=...'): {e}"
            )


@pytest.mark.parametrize(
    "cls", _in_tree_concrete_subclasses(LLMProvider), ids=_bind_test_case_ids
)
def test_in_tree_llm_concrete_overrides_accept_context(cls):
    """Every data method a shipped LLMProvider subclass overrides must still
    accept the request-context kwarg used by the pipeline (``request_context``
    for the two context-taking methods, ``context`` elsewhere) — either as an
    explicit keyword-only param, or via **kwargs.
    """
    for method, param in _LLM_METHOD_CTX_PARAM.items():
        if method not in cls.__dict__:
            continue  # not overridden here; covered by the ABC/base guards
        fn = cls.__dict__[method]
        sig = inspect.signature(fn)
        args = _SAMPLE_ARGS[method]
        kwargs = {param: CTX, **_SAMPLE_KWARGS.get(method, {})}
        try:
            sig.bind(object(), *args, **kwargs)
        except TypeError as e:
            pytest.fail(
                f"{cls.__name__}.{method} does not accept '{param}=' "
                f"(pipeline calls it with '{param}=...'): {e}"
            )


def test_in_tree_concrete_subclasses_were_actually_discovered():
    """Guard the guard: if discovery ever comes back empty (e.g. an import
    path changes and the modules above stop being importable/registering),
    the parametrized tests above would silently collect zero cases and this
    whole layer would go dark. Fail loudly instead.
    """
    embedding_names = {c.__name__ for c in _in_tree_concrete_subclasses(EmbeddingProvider)}
    llm_names = {c.__name__ for c in _in_tree_concrete_subclasses(LLMProvider)}
    assert "FallbackEmbeddingProvider" in embedding_names
    assert "NoneLLMProvider" in llm_names
    assert "FallbackLLMProvider" in llm_names


# ---------------------------------------------------------------------------
# Layer 3b: identity-propagation for FallbackEmbeddingProvider
# ---------------------------------------------------------------------------
#
# Bind-testing (above) only proves the parameter is accepted, not that it is
# forwarded into the wrapped primary/secondary provider. FallbackEmbeddingProvider
# is the one in-tree concrete that wraps another provider on its data path, so
# it gets the same identity-propagation treatment as the ABC/base defaults above.


class _StubPrimaryEmbedder(EmbeddingProvider):
    """Records the context each data method actually received."""

    def __init__(self):
        self.embed_ctx = "unset"
        self.embed_batch_ctx = "unset"

    def embed(self, text, *, context=None):
        self.embed_ctx = context
        return [0.1, 0.2]

    def embed_batch(self, texts, *, context=None):
        self.embed_batch_ctx = context
        return [[0.1, 0.2] for _ in texts]

    def get_dimensions(self):
        return 2


def _make_fallback_embedding_provider(stub):
    """Build a FallbackEmbeddingProvider wired directly to a stub primary,
    bypassing __init__ (which needs real Settings + factory lookups that are
    irrelevant to what's being tested: does embed/embed_batch forward context
    to whichever provider `.primary` resolves to)."""
    from stache_ai.providers.embeddings.fallback import FallbackEmbeddingProvider

    fb = FallbackEmbeddingProvider.__new__(FallbackEmbeddingProvider)
    fb._primary = stub
    fb._secondary = stub
    fb._primary_name = "stub"
    fb._secondary_name = "stub"
    return fb


def test_fallback_embedding_provider_embed_forwards_context_to_primary():
    stub = _StubPrimaryEmbedder()
    fb = _make_fallback_embedding_provider(stub)
    fb.embed("hello", context=CTX)
    assert stub.embed_ctx is CTX


def test_fallback_embedding_provider_embed_batch_forwards_context_to_primary():
    stub = _StubPrimaryEmbedder()
    fb = _make_fallback_embedding_provider(stub)
    fb.embed_batch(["hello", "world"], context=CTX)
    assert stub.embed_batch_ctx is CTX

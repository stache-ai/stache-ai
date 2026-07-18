"""Tests for BedrockEmbeddingProvider (Titan, Cohere v3, Cohere v4)

Cohere Embed v4 (`cohere.embed-v4:0`) is a new code path added alongside the
existing v3 path - selection is purely config-driven via
`bedrock_embedding_model`. These tests cover the v4 request/response schema
(mocked, since we have no live AWS access here) and confirm the pre-existing
v3 and Titan paths are untouched.
"""

import json
import threading

import pytest
from unittest.mock import MagicMock, patch

from stache_ai.config import Settings
from stache_ai_bedrock.embedding import BedrockEmbeddingProvider


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_boto_client():
    """Create a mock boto3 bedrock-runtime client"""
    with patch("boto3.client") as mock_client:
        client_instance = MagicMock()
        mock_client.return_value = client_instance
        yield client_instance


@pytest.fixture
def settings_titan():
    return Settings(
        embedding_provider="bedrock",
        bedrock_embedding_model="amazon.titan-embed-text-v2:0",
        aws_region="us-east-1",
    )


@pytest.fixture
def settings_cohere_v3():
    return Settings(
        embedding_provider="bedrock",
        bedrock_embedding_model="cohere.embed-english-v3",
        aws_region="us-east-1",
    )


@pytest.fixture
def settings_cohere_v4():
    return Settings(
        embedding_provider="bedrock",
        bedrock_embedding_model="cohere.embed-v4:0",
        aws_region="us-east-1",
    )


def _response_with_body(payload: dict):
    body = MagicMock()
    body.read.return_value = json.dumps(payload)
    return {"body": body}


# ---------------------------------------------------------------------------
# Titan - unchanged, sanity check only
# ---------------------------------------------------------------------------

class TestTitanUnchanged:
    def test_embed_titan(self, settings_titan, mock_boto_client):
        mock_boto_client.invoke_model.return_value = _response_with_body(
            {"embedding": [0.1, 0.2, 0.3]}
        )

        provider = BedrockEmbeddingProvider(settings_titan)
        result = provider.embed("hello")

        assert result == [0.1, 0.2, 0.3]
        body = json.loads(mock_boto_client.invoke_model.call_args.kwargs["body"])
        assert "embedding_types" not in body
        assert "output_dimension" not in body

    def test_get_dimensions_titan(self, settings_titan, mock_boto_client):
        provider = BedrockEmbeddingProvider(settings_titan)
        assert provider.get_dimensions() == 1024


# ---------------------------------------------------------------------------
# Cohere v3 - unchanged, sanity check only
# ---------------------------------------------------------------------------

class TestCohereV3Unchanged:
    def test_embed_document(self, settings_cohere_v3, mock_boto_client):
        mock_boto_client.invoke_model.return_value = _response_with_body(
            {"embeddings": [[0.1, 0.2, 0.3]]}
        )

        provider = BedrockEmbeddingProvider(settings_cohere_v3)
        result = provider.embed("hello")

        assert result == [0.1, 0.2, 0.3]
        body = json.loads(mock_boto_client.invoke_model.call_args.kwargs["body"])
        assert body["input_type"] == "search_document"
        assert body["truncate"] == "END"
        # v3 body must NOT carry the v4-only fields
        assert "embedding_types" not in body
        assert "output_dimension" not in body

    def test_embed_query(self, settings_cohere_v3, mock_boto_client):
        mock_boto_client.invoke_model.return_value = _response_with_body(
            {"embeddings": [[0.4, 0.5, 0.6]]}
        )

        provider = BedrockEmbeddingProvider(settings_cohere_v3)
        result = provider.embed_query("query")

        assert result == [0.4, 0.5, 0.6]
        body = json.loads(mock_boto_client.invoke_model.call_args.kwargs["body"])
        assert body["input_type"] == "search_query"

    def test_embed_batch(self, settings_cohere_v3, mock_boto_client):
        mock_boto_client.invoke_model.return_value = _response_with_body(
            {"embeddings": [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]}
        )

        provider = BedrockEmbeddingProvider(settings_cohere_v3)
        result = provider.embed_batch(["a", "b", "c"])

        assert len(result) == 3
        assert mock_boto_client.invoke_model.call_count == 1

    def test_get_dimensions(self, settings_cohere_v3, mock_boto_client):
        provider = BedrockEmbeddingProvider(settings_cohere_v3)
        assert provider.get_dimensions() == 1024


# ---------------------------------------------------------------------------
# Cohere v4 - new path
# ---------------------------------------------------------------------------

class TestCohereV4:
    def test_get_dimensions_defaults_to_1024(self, settings_cohere_v4, mock_boto_client):
        provider = BedrockEmbeddingProvider(settings_cohere_v4)
        assert provider.get_dimensions() == 1024

    def test_embed_document(self, settings_cohere_v4, mock_boto_client):
        """v4-shaped response: embeddings keyed by type"""
        mock_boto_client.invoke_model.return_value = _response_with_body(
            {"embeddings": {"float": [[0.11, 0.22, 0.33]]}}
        )

        provider = BedrockEmbeddingProvider(settings_cohere_v4)
        result = provider.embed("hello")

        assert result == [0.11, 0.22, 0.33]

        body = json.loads(mock_boto_client.invoke_model.call_args.kwargs["body"])
        assert body["texts"] == ["hello"]
        assert body["input_type"] == "search_document"
        assert body["embedding_types"] == ["float"]
        assert body["output_dimension"] == 1024
        call_kwargs = mock_boto_client.invoke_model.call_args.kwargs
        assert call_kwargs["modelId"] == "cohere.embed-v4:0"

    def test_embed_query_uses_search_query_input_type(self, settings_cohere_v4, mock_boto_client):
        mock_boto_client.invoke_model.return_value = _response_with_body(
            {"embeddings": {"float": [[0.4, 0.5, 0.6]]}}
        )

        provider = BedrockEmbeddingProvider(settings_cohere_v4)
        result = provider.embed_query("search text")

        assert result == [0.4, 0.5, 0.6]
        body = json.loads(mock_boto_client.invoke_model.call_args.kwargs["body"])
        assert body["input_type"] == "search_query"

    def test_embed_response_parsed_defensively_as_bare_list(self, settings_cohere_v4, mock_boto_client):
        """Some deployments/schema variants may return a bare list instead of
        a dict keyed by embedding type - parsing must handle both."""
        mock_boto_client.invoke_model.return_value = _response_with_body(
            {"embeddings": [[0.7, 0.8, 0.9]]}
        )

        provider = BedrockEmbeddingProvider(settings_cohere_v4)
        result = provider.embed("hello")

        assert result == [0.7, 0.8, 0.9]

    def test_embed_batch_single_call_under_96(self, settings_cohere_v4, mock_boto_client):
        mock_boto_client.invoke_model.return_value = _response_with_body(
            {"embeddings": {"float": [[0.1, 0.1], [0.2, 0.2], [0.3, 0.3]]}}
        )

        provider = BedrockEmbeddingProvider(settings_cohere_v4)
        result = provider.embed_batch(["a", "b", "c"])

        assert result == [[0.1, 0.1], [0.2, 0.2], [0.3, 0.3]]
        assert mock_boto_client.invoke_model.call_count == 1

        body = json.loads(mock_boto_client.invoke_model.call_args.kwargs["body"])
        assert body["texts"] == ["a", "b", "c"]
        assert body["embedding_types"] == ["float"]
        assert body["output_dimension"] == 1024

    def test_embed_batch_splits_over_96_and_preserves_order(self, settings_cohere_v4, mock_boto_client):
        """>96 texts must be split into parallel batches, results flattened
        back into original input order."""
        lock = threading.Lock()
        call_count = [0]

        def mock_invoke(*args, **kwargs):
            body = json.loads(kwargs["body"])
            texts = body["texts"]
            with lock:
                call_count[0] += 1
            # Echo back a deterministic embedding per text so we can verify order
            embeddings = [[float(t.replace("text", ""))] for t in texts]
            return _response_with_body({"embeddings": {"float": embeddings}})

        mock_boto_client.invoke_model.side_effect = mock_invoke

        provider = BedrockEmbeddingProvider(settings_cohere_v4)
        texts = [f"text{i}" for i in range(150)]
        result = provider.embed_batch(texts)

        assert len(result) == 150
        assert call_count[0] == 2  # 96 + 54
        for i, embedding in enumerate(result):
            assert embedding == [float(i)]

    def test_dispatch_selects_v4_purely_from_model_id(self, mock_boto_client):
        """Provider must select the v4 vs v3 code path purely from the
        configured `bedrock_embedding_model` - no other flag involved."""
        v3_settings = Settings(
            embedding_provider="bedrock",
            bedrock_embedding_model="cohere.embed-english-v3",
            aws_region="us-east-1",
        )
        v4_settings = Settings(
            embedding_provider="bedrock",
            bedrock_embedding_model="cohere.embed-v4:0",
            aws_region="us-east-1",
        )

        v3_provider = BedrockEmbeddingProvider(v3_settings)
        v4_provider = BedrockEmbeddingProvider(v4_settings)

        assert v3_provider._is_cohere_v4() is False
        assert v4_provider._is_cohere_v4() is True

        # v3 request body
        mock_boto_client.invoke_model.return_value = _response_with_body(
            {"embeddings": [[0.1, 0.2]]}
        )
        v3_provider.embed("hello")
        v3_body = json.loads(mock_boto_client.invoke_model.call_args.kwargs["body"])
        assert "embedding_types" not in v3_body
        assert v3_body["truncate"] == "END"

        # v4 request body
        mock_boto_client.invoke_model.return_value = _response_with_body(
            {"embeddings": {"float": [[0.1, 0.2]]}}
        )
        v4_provider.embed("hello")
        v4_body = json.loads(mock_boto_client.invoke_model.call_args.kwargs["body"])
        assert v4_body["embedding_types"] == ["float"]
        assert v4_body["output_dimension"] == 1024
        assert "truncate" not in v4_body

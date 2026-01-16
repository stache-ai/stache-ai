"""Tests for BedrockLLMProvider.generate_structured method."""

import json
import pytest
from unittest.mock import MagicMock, patch
from botocore.exceptions import ClientError


class TestBedrockGenerateStructured:
    """Tests for structured output generation via Bedrock."""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings."""
        settings = MagicMock()
        settings.aws_region = "us-east-1"
        settings.bedrock_llm_model = "us.amazon.nova-lite-v1:0"
        return settings

    @pytest.fixture
    def sample_schema(self):
        """Sample JSON schema for testing."""
        return {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Document summary"
                },
                "doc_type": {
                    "type": "string",
                    "enum": ["article", "guide", "report"]
                }
            },
            "required": ["summary", "doc_type"]
        }

    @pytest.fixture
    def provider_with_mock_client(self, mock_settings):
        """Create provider with mocked boto3 client."""
        with patch("boto3.client") as mock_boto:
            from stache_ai_bedrock.llm import BedrockLLMProvider

            mock_client = MagicMock()
            mock_boto.return_value = mock_client

            provider = BedrockLLMProvider(mock_settings)
            provider.client = mock_client

            return provider, mock_client

    def test_capabilities_includes_structured_output(self, provider_with_mock_client):
        """Test that Bedrock provider declares structured_output capability."""
        provider, _ = provider_with_mock_client

        assert "structured_output" in provider.capabilities
        assert "tool_use" in provider.capabilities

    def test_nova_model_uses_converse_api(
        self, provider_with_mock_client, sample_schema
    ):
        """Test that Nova models use Converse API with toolConfig."""
        provider, mock_client = provider_with_mock_client
        provider.model_id = "us.amazon.nova-lite-v1:0"

        # Mock successful response
        mock_client.converse.return_value = {
            "output": {
                "message": {
                    "content": [
                        {
                            "toolUse": {
                                "toolUseId": "tool-123",
                                "name": "extract_data",
                                "input": {
                                    "summary": "Test summary",
                                    "doc_type": "article"
                                }
                            }
                        }
                    ]
                }
            }
        }

        result = provider.generate_structured(
            prompt="Analyze this document",
            schema=sample_schema
        )

        assert result == {"summary": "Test summary", "doc_type": "article"}
        mock_client.converse.assert_called_once()

        # Verify toolConfig in call
        call_kwargs = mock_client.converse.call_args[1]
        assert "toolConfig" in call_kwargs
        assert call_kwargs["toolConfig"]["tools"][0]["toolSpec"]["name"] == "extract_data"

    def test_claude_model_uses_invoke_model(
        self, provider_with_mock_client, sample_schema
    ):
        """Test that Claude models use InvokeModel with Anthropic format."""
        provider, mock_client = provider_with_mock_client
        provider.model_id = "us.anthropic.claude-3-haiku-20240307-v1:0"

        # Mock successful response
        response_body = json.dumps({
            "content": [
                {
                    "type": "tool_use",
                    "id": "tool-456",
                    "name": "extract_data",
                    "input": {
                        "summary": "Claude summary",
                        "doc_type": "guide"
                    }
                }
            ]
        })

        mock_response = MagicMock()
        mock_response.__getitem__ = lambda self, key: {
            "body": MagicMock(read=lambda: response_body.encode())
        }[key]
        mock_client.invoke_model.return_value = {"body": MagicMock(read=lambda: response_body.encode())}

        result = provider.generate_structured(
            prompt="Analyze this",
            schema=sample_schema
        )

        assert result == {"summary": "Claude summary", "doc_type": "guide"}
        mock_client.invoke_model.assert_called_once()

    def test_anthropic_keyword_triggers_invoke_model(
        self, provider_with_mock_client, sample_schema
    ):
        """Test that 'anthropic' in model ID triggers InvokeModel path."""
        provider, mock_client = provider_with_mock_client
        provider.model_id = "anthropic.claude-v2"

        response_body = json.dumps({
            "content": [
                {"type": "tool_use", "input": {"summary": "Test", "doc_type": "report"}}
            ]
        })
        mock_client.invoke_model.return_value = {
            "body": MagicMock(read=lambda: response_body.encode())
        }

        result = provider.generate_structured(prompt="Test", schema=sample_schema)

        assert result["doc_type"] == "report"
        mock_client.invoke_model.assert_called_once()

    def test_amazon_keyword_triggers_converse(
        self, provider_with_mock_client, sample_schema
    ):
        """Test that 'amazon' in model ID triggers Converse path."""
        provider, mock_client = provider_with_mock_client
        provider.model_id = "amazon.titan-text-express-v1"

        mock_client.converse.return_value = {
            "output": {
                "message": {
                    "content": [
                        {"toolUse": {"input": {"summary": "Titan", "doc_type": "article"}}}
                    ]
                }
            }
        }

        result = provider.generate_structured(prompt="Test", schema=sample_schema)

        assert result["summary"] == "Titan"
        mock_client.converse.assert_called_once()

    def test_unsupported_model_raises_not_implemented(
        self, provider_with_mock_client, sample_schema
    ):
        """Test that unsupported model family raises NotImplementedError."""
        provider, _ = provider_with_mock_client
        provider.model_id = "mistral.mistral-7b-instruct"

        with pytest.raises(NotImplementedError) as exc_info:
            provider.generate_structured(prompt="Test", schema=sample_schema)

        assert "Unsupported model family" in str(exc_info.value)

    def test_access_denied_raises_runtime_error(
        self, provider_with_mock_client, sample_schema
    ):
        """Test AccessDeniedException is wrapped in RuntimeError."""
        provider, mock_client = provider_with_mock_client
        provider.model_id = "us.amazon.nova-lite-v1:0"

        mock_client.converse.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "Access denied"}},
            "Converse"
        )

        with pytest.raises(RuntimeError) as exc_info:
            provider.generate_structured(prompt="Test", schema=sample_schema)

        assert "Access denied" in str(exc_info.value)

    def test_validation_exception_raises_value_error(
        self, provider_with_mock_client, sample_schema
    ):
        """Test ValidationException is wrapped in ValueError."""
        provider, mock_client = provider_with_mock_client
        provider.model_id = "us.amazon.nova-lite-v1:0"

        mock_client.converse.side_effect = ClientError(
            {"Error": {"Code": "ValidationException", "Message": "Invalid schema"}},
            "Converse"
        )

        with pytest.raises(ValueError) as exc_info:
            provider.generate_structured(prompt="Test", schema=sample_schema)

        assert "Invalid request" in str(exc_info.value)

    def test_no_tool_use_in_response_raises_value_error(
        self, provider_with_mock_client, sample_schema
    ):
        """Test missing toolUse in response raises ValueError."""
        provider, mock_client = provider_with_mock_client
        provider.model_id = "us.amazon.nova-lite-v1:0"

        # Response with no toolUse
        mock_client.converse.return_value = {
            "output": {
                "message": {
                    "content": [
                        {"text": "I cannot use tools"}
                    ]
                }
            }
        }

        with pytest.raises(ValueError) as exc_info:
            provider.generate_structured(prompt="Test", schema=sample_schema)

        assert "No tool use found" in str(exc_info.value)

    def test_model_id_override_via_kwargs(
        self, provider_with_mock_client, sample_schema
    ):
        """Test that model_id can be overridden via kwargs."""
        provider, mock_client = provider_with_mock_client
        provider.model_id = "us.amazon.nova-lite-v1:0"

        # Use Claude model via override
        response_body = json.dumps({
            "content": [
                {"type": "tool_use", "input": {"summary": "Override", "doc_type": "article"}}
            ]
        })
        mock_client.invoke_model.return_value = {
            "body": MagicMock(read=lambda: response_body.encode())
        }

        result = provider.generate_structured(
            prompt="Test",
            schema=sample_schema,
            model_id="us.anthropic.claude-3-haiku-20240307-v1:0"
        )

        assert result["summary"] == "Override"
        # Should use invoke_model (Claude path), not converse
        mock_client.invoke_model.assert_called_once()
        mock_client.converse.assert_not_called()

    def test_max_tokens_and_temperature_passed(
        self, provider_with_mock_client, sample_schema
    ):
        """Test that max_tokens and temperature are passed to API."""
        provider, mock_client = provider_with_mock_client
        provider.model_id = "us.amazon.nova-lite-v1:0"

        mock_client.converse.return_value = {
            "output": {
                "message": {
                    "content": [
                        {"toolUse": {"input": {"summary": "Test", "doc_type": "article"}}}
                    ]
                }
            }
        }

        provider.generate_structured(
            prompt="Test",
            schema=sample_schema,
            max_tokens=512,
            temperature=0.5
        )

        call_kwargs = mock_client.converse.call_args[1]
        assert call_kwargs["inferenceConfig"]["maxTokens"] == 512
        assert call_kwargs["inferenceConfig"]["temperature"] == 0.5

    def test_tool_choice_forces_tool_use(
        self, provider_with_mock_client, sample_schema
    ):
        """Test that toolChoice forces the model to use the tool."""
        provider, mock_client = provider_with_mock_client
        provider.model_id = "us.amazon.nova-lite-v1:0"

        mock_client.converse.return_value = {
            "output": {
                "message": {
                    "content": [
                        {"toolUse": {"input": {"summary": "Forced", "doc_type": "article"}}}
                    ]
                }
            }
        }

        provider.generate_structured(prompt="Test", schema=sample_schema)

        call_kwargs = mock_client.converse.call_args[1]
        tool_choice = call_kwargs["toolConfig"]["toolChoice"]
        assert tool_choice == {"tool": {"name": "extract_data"}}

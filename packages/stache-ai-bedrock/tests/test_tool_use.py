"""Tests for Bedrock tool use implementation."""
import pytest
from unittest.mock import MagicMock, patch
from botocore.exceptions import ClientError

from stache_ai.providers.tool_types import (
    Message, ToolCall, ToolResponse, ToolSpec, ToolUseResult
)


class TestConvertToolToBedrock:
    """Tests for _convert_tool_to_bedrock method."""

    @pytest.fixture
    def provider_with_mock_client(self):
        """Create provider with mocked boto3 client."""
        with patch("boto3.client") as mock_boto:
            from stache_ai_bedrock.llm import BedrockLLMProvider
            from stache_ai.config import Settings

            mock_client = MagicMock()
            mock_boto.return_value = mock_client

            settings = MagicMock(spec=Settings)
            settings.aws_region = "us-east-1"
            settings.bedrock_llm_model = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"

            provider = BedrockLLMProvider(settings)
            provider.client = mock_client

            return provider, mock_client

    def test_basic_conversion(self, provider_with_mock_client):
        """Test basic ToolSpec to Bedrock format conversion."""
        provider, _ = provider_with_mock_client

        spec = ToolSpec(
            name="search",
            description="Search knowledge base",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"}
                },
                "required": ["query"]
            }
        )

        result = provider._convert_tool_to_bedrock(spec)

        assert result == {
            "toolSpec": {
                "name": "search",
                "description": "Search knowledge base",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"}
                        },
                        "required": ["query"]
                    }
                }
            }
        }

    def test_complex_schema_conversion(self, provider_with_mock_client):
        """Test conversion with complex nested schema."""
        provider, _ = provider_with_mock_client

        spec = ToolSpec(
            name="create_task",
            description="Create a task with metadata",
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "priority": {"type": "string", "enum": ["low", "medium", "high"]},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "metadata": {
                        "type": "object",
                        "properties": {
                            "assigned_to": {"type": "string"}
                        }
                    }
                },
                "required": ["title", "priority"]
            }
        )

        result = provider._convert_tool_to_bedrock(spec)

        assert result["toolSpec"]["name"] == "create_task"
        assert result["toolSpec"]["description"] == "Create a task with metadata"
        assert "inputSchema" in result["toolSpec"]
        assert result["toolSpec"]["inputSchema"]["json"]["required"] == ["title", "priority"]


class TestConvertMessages:
    """Tests for _convert_messages method."""

    @pytest.fixture
    def provider_with_mock_client(self):
        """Create provider with mocked boto3 client."""
        with patch("boto3.client") as mock_boto:
            from stache_ai_bedrock.llm import BedrockLLMProvider
            from stache_ai.config import Settings

            mock_client = MagicMock()
            mock_boto.return_value = mock_client

            settings = MagicMock(spec=Settings)
            settings.aws_region = "us-east-1"
            settings.bedrock_llm_model = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"

            provider = BedrockLLMProvider(settings)
            provider.client = mock_client

            return provider, mock_client

    def test_text_message_user(self, provider_with_mock_client):
        """Test conversion of simple user text message."""
        provider, _ = provider_with_mock_client

        messages = [Message(role="user", content="Hello")]

        result = provider._convert_messages(messages)

        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["content"] == [{"text": "Hello"}]

    def test_text_message_assistant(self, provider_with_mock_client):
        """Test conversion of assistant text message."""
        provider, _ = provider_with_mock_client

        messages = [Message(role="assistant", content="Hi there!")]

        result = provider._convert_messages(messages)

        assert len(result) == 1
        assert result[0]["role"] == "assistant"
        assert result[0]["content"] == [{"text": "Hi there!"}]

    def test_message_with_tool_calls(self, provider_with_mock_client):
        """Test conversion of assistant message with tool calls."""
        provider, _ = provider_with_mock_client

        tool_calls = [
            ToolCall(id="call-123", name="search", input={"query": "test"}),
            ToolCall(id="call-456", name="update", input={"id": "doc-1", "status": "done"})
        ]
        messages = [Message(role="assistant", tool_calls=tool_calls)]

        result = provider._convert_messages(messages)

        assert len(result) == 1
        assert result[0]["role"] == "assistant"
        assert len(result[0]["content"]) == 2
        assert result[0]["content"][0] == {
            "toolUse": {
                "toolUseId": "call-123",
                "name": "search",
                "input": {"query": "test"}
            }
        }
        assert result[0]["content"][1] == {
            "toolUse": {
                "toolUseId": "call-456",
                "name": "update",
                "input": {"id": "doc-1", "status": "done"}
            }
        }

    def test_message_with_tool_responses(self, provider_with_mock_client):
        """Test conversion of user message with tool responses."""
        provider, _ = provider_with_mock_client

        tool_responses = [
            ToolResponse(id="call-123", content="Found 5 results"),
            ToolResponse(id="call-456", content="Update successful")
        ]
        messages = [Message(role="user", tool_responses=tool_responses)]

        result = provider._convert_messages(messages)

        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert len(result[0]["content"]) == 2
        assert result[0]["content"][0] == {
            "toolResult": {
                "toolUseId": "call-123",
                "content": [{"text": "Found 5 results"}],
                "status": "success"
            }
        }
        assert result[0]["content"][1] == {
            "toolResult": {
                "toolUseId": "call-456",
                "content": [{"text": "Update successful"}],
                "status": "success"
            }
        }

    def test_message_with_error_tool_response(self, provider_with_mock_client):
        """Test conversion of tool response with error status."""
        provider, _ = provider_with_mock_client

        tool_responses = [
            ToolResponse(id="call-123", content="Tool execution failed", is_error=True)
        ]
        messages = [Message(role="user", tool_responses=tool_responses)]

        result = provider._convert_messages(messages)

        assert result[0]["content"][0]["toolResult"]["status"] == "error"

    def test_message_with_text_and_tool_calls(self, provider_with_mock_client):
        """Test conversion of message with both text and tool calls."""
        provider, _ = provider_with_mock_client

        messages = [
            Message(
                role="assistant",
                content="Let me search for that",
                tool_calls=[ToolCall(id="call-123", name="search", input={"query": "test"})]
            )
        ]

        result = provider._convert_messages(messages)

        assert len(result[0]["content"]) == 2
        assert result[0]["content"][0] == {"text": "Let me search for that"}
        assert result[0]["content"][1]["toolUse"]["name"] == "search"

    def test_multiple_messages_conversation(self, provider_with_mock_client):
        """Test conversion of multi-turn conversation."""
        provider, _ = provider_with_mock_client

        messages = [
            Message(role="user", content="Search for documents"),
            Message(
                role="assistant",
                tool_calls=[ToolCall(id="call-1", name="search", input={"query": "docs"})]
            ),
            Message(
                role="user",
                tool_responses=[ToolResponse(id="call-1", content="Found 3 docs")]
            ),
            Message(role="assistant", content="I found 3 documents for you")
        ]

        result = provider._convert_messages(messages)

        assert len(result) == 4
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"
        assert result[2]["role"] == "user"
        assert result[3]["role"] == "assistant"

    def test_empty_content_raises_value_error(self, provider_with_mock_client):
        """Test that message with no content raises ValueError."""
        provider, _ = provider_with_mock_client

        messages = [Message(role="user")]  # No content, tool_calls, or tool_responses

        with pytest.raises(ValueError) as exc_info:
            provider._convert_messages(messages)

        assert "no content" in str(exc_info.value).lower()
        assert "user" in str(exc_info.value)

    def test_empty_content_assistant_raises_value_error(self, provider_with_mock_client):
        """Test that assistant message with no content raises ValueError."""
        provider, _ = provider_with_mock_client

        messages = [Message(role="assistant")]

        with pytest.raises(ValueError) as exc_info:
            provider._convert_messages(messages)

        assert "no content" in str(exc_info.value).lower()
        assert "assistant" in str(exc_info.value)


class TestParseToolResponse:
    """Tests for _parse_tool_response method."""

    @pytest.fixture
    def provider_with_mock_client(self):
        """Create provider with mocked boto3 client."""
        with patch("boto3.client") as mock_boto:
            from stache_ai_bedrock.llm import BedrockLLMProvider
            from stache_ai.config import Settings

            mock_client = MagicMock()
            mock_boto.return_value = mock_client

            settings = MagicMock(spec=Settings)
            settings.aws_region = "us-east-1"
            settings.bedrock_llm_model = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"

            provider = BedrockLLMProvider(settings)
            provider.client = mock_client

            return provider, mock_client

    def test_end_turn_with_text(self, provider_with_mock_client):
        """Test parsing response with end_turn stop reason."""
        provider, _ = provider_with_mock_client

        response = {
            "output": {
                "message": {
                    "content": [{"text": "Task completed successfully"}]
                }
            },
            "stopReason": "end_turn"
        }

        result = provider._parse_tool_response(response)

        assert isinstance(result, ToolUseResult)
        assert result.stop_reason == "end_turn"
        assert result.text == "Task completed successfully"
        assert len(result.tool_calls) == 0
        assert result.is_complete is True
        assert result.has_tool_calls is False

    def test_tool_use_with_single_tool(self, provider_with_mock_client):
        """Test parsing response with tool_use stop reason."""
        provider, _ = provider_with_mock_client

        response = {
            "output": {
                "message": {
                    "content": [
                        {
                            "toolUse": {
                                "toolUseId": "call-123",
                                "name": "search",
                                "input": {"query": "test documents"}
                            }
                        }
                    ]
                }
            },
            "stopReason": "tool_use"
        }

        result = provider._parse_tool_response(response)

        assert result.stop_reason == "tool_use"
        assert result.text is None
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].id == "call-123"
        assert result.tool_calls[0].name == "search"
        assert result.tool_calls[0].input == {"query": "test documents"}
        assert result.is_complete is False
        assert result.has_tool_calls is True

    def test_tool_use_with_multiple_tools(self, provider_with_mock_client):
        """Test parsing response with multiple tool calls."""
        provider, _ = provider_with_mock_client

        response = {
            "output": {
                "message": {
                    "content": [
                        {
                            "toolUse": {
                                "toolUseId": "call-1",
                                "name": "search",
                                "input": {"query": "docs"}
                            }
                        },
                        {
                            "toolUse": {
                                "toolUseId": "call-2",
                                "name": "update",
                                "input": {"id": "doc-1", "status": "done"}
                            }
                        }
                    ]
                }
            },
            "stopReason": "tool_use"
        }

        result = provider._parse_tool_response(response)

        assert len(result.tool_calls) == 2
        assert result.tool_calls[0].name == "search"
        assert result.tool_calls[1].name == "update"

    def test_text_and_tool_use_combined(self, provider_with_mock_client):
        """Test parsing response with both text and tool use."""
        provider, _ = provider_with_mock_client

        response = {
            "output": {
                "message": {
                    "content": [
                        {"text": "Let me search for that"},
                        {
                            "toolUse": {
                                "toolUseId": "call-1",
                                "name": "search",
                                "input": {"query": "test"}
                            }
                        }
                    ]
                }
            },
            "stopReason": "tool_use"
        }

        result = provider._parse_tool_response(response)

        assert result.text == "Let me search for that"
        assert len(result.tool_calls) == 1

    def test_multiple_text_blocks_concatenated(self, provider_with_mock_client):
        """Test that multiple text blocks are concatenated."""
        provider, _ = provider_with_mock_client

        response = {
            "output": {
                "message": {
                    "content": [
                        {"text": "Part one "},
                        {"text": "part two "},
                        {"text": "part three"}
                    ]
                }
            },
            "stopReason": "end_turn"
        }

        result = provider._parse_tool_response(response)

        assert result.text == "Part one part two part three"

    def test_max_tokens_stop_reason(self, provider_with_mock_client):
        """Test that max_tokens stop reason is normalized."""
        provider, _ = provider_with_mock_client

        response = {
            "output": {
                "message": {
                    "content": [{"text": "Truncated response"}]
                }
            },
            "stopReason": "max_tokens"
        }

        result = provider._parse_tool_response(response)

        assert result.stop_reason == "max_tokens"

    def test_stop_sequence_normalized_to_end_turn(self, provider_with_mock_client):
        """Test that stop_sequence is normalized to end_turn."""
        provider, _ = provider_with_mock_client

        response = {
            "output": {
                "message": {
                    "content": [{"text": "Response"}]
                }
            },
            "stopReason": "stop_sequence"
        }

        result = provider._parse_tool_response(response)

        assert result.stop_reason == "end_turn"

    def test_guardrail_intervened_normalized_to_end_turn(self, provider_with_mock_client):
        """Test that guardrail_intervened is normalized to end_turn."""
        provider, _ = provider_with_mock_client

        response = {
            "output": {
                "message": {
                    "content": [{"text": "Blocked"}]
                }
            },
            "stopReason": "guardrail_intervened"
        }

        result = provider._parse_tool_response(response)

        assert result.stop_reason == "end_turn"

    def test_content_filtered_normalized_to_end_turn(self, provider_with_mock_client):
        """Test that content_filtered is normalized to end_turn."""
        provider, _ = provider_with_mock_client

        response = {
            "output": {
                "message": {
                    "content": [{"text": "Filtered"}]
                }
            },
            "stopReason": "content_filtered"
        }

        result = provider._parse_tool_response(response)

        assert result.stop_reason == "end_turn"

    def test_unknown_stop_reason_defaults_to_end_turn(self, provider_with_mock_client):
        """Test that unknown stop reasons default to end_turn."""
        provider, _ = provider_with_mock_client

        response = {
            "output": {
                "message": {
                    "content": [{"text": "Response"}]
                }
            },
            "stopReason": "future_unknown_reason"
        }

        result = provider._parse_tool_response(response)

        assert result.stop_reason == "end_turn"

    def test_empty_content_returns_empty_result(self, provider_with_mock_client):
        """Test parsing response with empty content."""
        provider, _ = provider_with_mock_client

        response = {
            "output": {
                "message": {
                    "content": []
                }
            },
            "stopReason": "end_turn"
        }

        result = provider._parse_tool_response(response)

        assert result.text is None
        assert len(result.tool_calls) == 0


class TestGenerateWithToolsValidation:
    """Tests for generate_with_tools input validation."""

    @pytest.fixture
    def provider_with_mock_client(self):
        """Create provider with mocked boto3 client."""
        with patch("boto3.client") as mock_boto:
            from stache_ai_bedrock.llm import BedrockLLMProvider
            from stache_ai.config import Settings

            mock_client = MagicMock()
            mock_boto.return_value = mock_client

            settings = MagicMock(spec=Settings)
            settings.aws_region = "us-east-1"
            settings.bedrock_llm_model = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"

            provider = BedrockLLMProvider(settings)
            provider.client = mock_client

            return provider, mock_client

    def test_empty_messages_raises_value_error(self, provider_with_mock_client):
        """Test that empty messages list raises ValueError."""
        provider, _ = provider_with_mock_client

        spec = ToolSpec(
            name="test",
            description="Test tool",
            input_schema={"type": "object"}
        )

        with pytest.raises(ValueError) as exc_info:
            provider.generate_with_tools(messages=[], tools=[spec])

        assert "messages list cannot be empty" in str(exc_info.value)

    def test_empty_tools_raises_value_error(self, provider_with_mock_client):
        """Test that empty tools list raises ValueError."""
        provider, _ = provider_with_mock_client

        msg = Message(role="user", content="test")

        with pytest.raises(ValueError) as exc_info:
            provider.generate_with_tools(messages=[msg], tools=[])

        assert "tools list cannot be empty" in str(exc_info.value)


class TestGenerateWithToolsBasicFlow:
    """Tests for generate_with_tools basic functionality."""

    @pytest.fixture
    def provider_with_mock_client(self):
        """Create provider with mocked boto3 client."""
        with patch("boto3.client") as mock_boto:
            from stache_ai_bedrock.llm import BedrockLLMProvider
            from stache_ai.config import Settings

            mock_client = MagicMock()
            mock_boto.return_value = mock_client

            settings = MagicMock(spec=Settings)
            settings.aws_region = "us-east-1"
            settings.bedrock_llm_model = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"

            provider = BedrockLLMProvider(settings)
            provider.client = mock_client

            return provider, mock_client

    def test_basic_tool_use_flow(self, provider_with_mock_client):
        """Test basic flow of generate_with_tools."""
        provider, mock_client = provider_with_mock_client

        # Mock successful response
        mock_client.converse.return_value = {
            "output": {
                "message": {
                    "content": [
                        {
                            "toolUse": {
                                "toolUseId": "call-123",
                                "name": "search",
                                "input": {"query": "test"}
                            }
                        }
                    ]
                }
            },
            "stopReason": "tool_use"
        }

        messages = [Message(role="user", content="Search for test")]
        tools = [
            ToolSpec(
                name="search",
                description="Search documents",
                input_schema={"type": "object", "properties": {"query": {"type": "string"}}}
            )
        ]

        result = provider.generate_with_tools(messages=messages, tools=tools)

        assert result.stop_reason == "tool_use"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "search"

        # Verify converse was called with correct structure
        mock_client.converse.assert_called_once()
        call_kwargs = mock_client.converse.call_args[1]
        assert "messages" in call_kwargs
        assert "toolConfig" in call_kwargs
        assert "inferenceConfig" in call_kwargs

    def test_system_prompt_included(self, provider_with_mock_client):
        """Test that system prompt is included in request."""
        provider, mock_client = provider_with_mock_client

        mock_client.converse.return_value = {
            "output": {"message": {"content": [{"text": "Done"}]}},
            "stopReason": "end_turn"
        }

        messages = [Message(role="user", content="Test")]
        tools = [ToolSpec(name="test", description="Test", input_schema={})]

        provider.generate_with_tools(
            messages=messages,
            tools=tools,
            system_prompt="You are a helpful assistant"
        )

        call_kwargs = mock_client.converse.call_args[1]
        assert "system" in call_kwargs
        assert call_kwargs["system"] == [{"text": "You are a helpful assistant"}]

    def test_no_system_prompt_omitted(self, provider_with_mock_client):
        """Test that system prompt is omitted when None."""
        provider, mock_client = provider_with_mock_client

        mock_client.converse.return_value = {
            "output": {"message": {"content": [{"text": "Done"}]}},
            "stopReason": "end_turn"
        }

        messages = [Message(role="user", content="Test")]
        tools = [ToolSpec(name="test", description="Test", input_schema={})]

        provider.generate_with_tools(messages=messages, tools=tools)

        call_kwargs = mock_client.converse.call_args[1]
        assert "system" not in call_kwargs

    def test_max_tokens_and_temperature_passed(self, provider_with_mock_client):
        """Test that max_tokens and temperature are passed correctly."""
        provider, mock_client = provider_with_mock_client

        mock_client.converse.return_value = {
            "output": {"message": {"content": [{"text": "Done"}]}},
            "stopReason": "end_turn"
        }

        messages = [Message(role="user", content="Test")]
        tools = [ToolSpec(name="test", description="Test", input_schema={})]

        provider.generate_with_tools(
            messages=messages,
            tools=tools,
            max_tokens=2048,
            temperature=0.5
        )

        call_kwargs = mock_client.converse.call_args[1]
        assert call_kwargs["inferenceConfig"]["maxTokens"] == 2048
        assert call_kwargs["inferenceConfig"]["temperature"] == 0.5

    def test_model_id_override_via_kwargs(self, provider_with_mock_client):
        """Test that model_id can be overridden via kwargs."""
        provider, mock_client = provider_with_mock_client

        mock_client.converse.return_value = {
            "output": {"message": {"content": [{"text": "Done"}]}},
            "stopReason": "end_turn"
        }

        messages = [Message(role="user", content="Test")]
        tools = [ToolSpec(name="test", description="Test", input_schema={})]

        provider.generate_with_tools(
            messages=messages,
            tools=tools,
            model_id="us.anthropic.claude-3-haiku-20240307-v1:0"
        )

        call_kwargs = mock_client.converse.call_args[1]
        assert call_kwargs["modelId"] == "us.anthropic.claude-3-haiku-20240307-v1:0"


class TestGenerateWithToolsErrorHandling:
    """Tests for generate_with_tools error handling."""

    @pytest.fixture
    def provider_with_mock_client(self):
        """Create provider with mocked boto3 client."""
        with patch("boto3.client") as mock_boto:
            from stache_ai_bedrock.llm import BedrockLLMProvider
            from stache_ai.config import Settings

            mock_client = MagicMock()
            mock_boto.return_value = mock_client

            settings = MagicMock(spec=Settings)
            settings.aws_region = "us-east-1"
            settings.bedrock_llm_model = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"

            provider = BedrockLLMProvider(settings)
            provider.client = mock_client

            return provider, mock_client

    def test_access_denied_raises_runtime_error(self, provider_with_mock_client):
        """Test AccessDeniedException is wrapped in RuntimeError."""
        provider, mock_client = provider_with_mock_client

        mock_client.converse.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "Access denied"}},
            "Converse"
        )

        messages = [Message(role="user", content="Test")]
        tools = [ToolSpec(name="test", description="Test", input_schema={})]

        with pytest.raises(RuntimeError) as exc_info:
            provider.generate_with_tools(messages=messages, tools=tools)

        assert "Access denied" in str(exc_info.value)
        assert "IAM permissions" in str(exc_info.value)

    def test_throttling_exception_raises_runtime_error(self, provider_with_mock_client):
        """Test ThrottlingException is wrapped in RuntimeError."""
        provider, mock_client = provider_with_mock_client

        mock_client.converse.side_effect = ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
            "Converse"
        )

        messages = [Message(role="user", content="Test")]
        tools = [ToolSpec(name="test", description="Test", input_schema={})]

        with pytest.raises(RuntimeError) as exc_info:
            provider.generate_with_tools(messages=messages, tools=tools)

        assert "throttled" in str(exc_info.value).lower()
        assert "backoff" in str(exc_info.value).lower()

    def test_validation_exception_raises_value_error(self, provider_with_mock_client):
        """Test ValidationException is wrapped in ValueError."""
        provider, mock_client = provider_with_mock_client

        mock_client.converse.side_effect = ClientError(
            {"Error": {"Code": "ValidationException", "Message": "Invalid schema"}},
            "Converse"
        )

        messages = [Message(role="user", content="Test")]
        tools = [ToolSpec(name="test", description="Test", input_schema={})]

        with pytest.raises(ValueError) as exc_info:
            provider.generate_with_tools(messages=messages, tools=tools)

        assert "Invalid request" in str(exc_info.value)

    def test_unknown_error_raises_runtime_error(self, provider_with_mock_client):
        """Test unknown errors are wrapped in RuntimeError."""
        provider, mock_client = provider_with_mock_client

        mock_client.converse.side_effect = ClientError(
            {"Error": {"Code": "UnknownException", "Message": "Unknown error"}},
            "Converse"
        )

        messages = [Message(role="user", content="Test")]
        tools = [ToolSpec(name="test", description="Test", input_schema={})]

        with pytest.raises(RuntimeError) as exc_info:
            provider.generate_with_tools(messages=messages, tools=tools)

        assert "Bedrock API error" in str(exc_info.value)

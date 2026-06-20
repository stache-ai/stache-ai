"""Tests for tool calling types."""
import pytest
from stache_ai.providers.tool_types import (
    Message,
    ToolCall,
    ToolResponse,
    ToolSpec,
    ToolUseResult,
)


class TestToolSpec:
    """Tests for ToolSpec creation and fields."""

    def test_creation(self):
        """Test basic ToolSpec creation."""
        spec = ToolSpec(
            name="test_tool",
            description="A test tool",
            input_schema={"type": "object", "properties": {}},
        )
        assert spec.name == "test_tool"
        assert spec.description == "A test tool"
        assert spec.input_schema == {"type": "object", "properties": {}}

    def test_creation_with_complex_schema(self):
        """Test ToolSpec with complex JSON schema."""
        schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        }
        spec = ToolSpec(
            name="search",
            description="Search the knowledge base",
            input_schema=schema,
        )
        assert spec.name == "search"
        assert spec.input_schema == schema
        assert spec.input_schema["properties"]["query"]["type"] == "string"

    def test_fields_immutable_by_default(self):
        """Test that ToolSpec is a dataclass with frozen=False by default."""
        spec = ToolSpec(
            name="tool1", description="desc", input_schema={"type": "object"}
        )
        # Should be able to modify (not frozen)
        spec.name = "tool2"
        assert spec.name == "tool2"

    def test_empty_input_schema(self):
        """Test ToolSpec with empty input schema."""
        spec = ToolSpec(name="no_args", description="Tool with no args", input_schema={})
        assert spec.input_schema == {}


class TestToolCall:
    """Tests for ToolCall creation and fields."""

    def test_creation(self):
        """Test basic ToolCall creation."""
        call = ToolCall(id="123", name="test", input={"key": "value"})
        assert call.id == "123"
        assert call.name == "test"
        assert call.input == {"key": "value"}

    def test_creation_with_complex_input(self):
        """Test ToolCall with complex nested input."""
        input_data = {
            "query": "test search",
            "filters": {"namespace": "docs", "type": "pdf"},
            "limit": 10,
        }
        call = ToolCall(id="call_1", name="search", input=input_data)
        assert call.input == input_data
        assert call.input["filters"]["namespace"] == "docs"

    def test_creation_with_empty_input(self):
        """Test ToolCall with empty input dict."""
        call = ToolCall(id="456", name="no_args_tool", input={})
        assert call.input == {}
        assert call.id == "456"

    def test_creation_with_empty_string_id(self):
        """Test ToolCall with empty string ID (edge case)."""
        call = ToolCall(id="", name="tool", input={})
        assert call.id == ""

    def test_multiple_calls_with_different_ids(self):
        """Test creating multiple ToolCalls with different IDs."""
        call1 = ToolCall(id="1", name="tool_a", input={"x": 1})
        call2 = ToolCall(id="2", name="tool_b", input={"y": 2})
        assert call1.id != call2.id
        assert call1.name != call2.name


class TestToolResponse:
    """Tests for ToolResponse creation (success and error cases)."""

    def test_success_response(self):
        """Test successful tool response."""
        resp = ToolResponse(id="123", content="result")
        assert resp.id == "123"
        assert resp.content == "result"
        assert resp.is_error is False

    def test_error_response(self):
        """Test error tool response."""
        resp = ToolResponse(id="123", content="error message", is_error=True)
        assert resp.id == "123"
        assert resp.content == "error message"
        assert resp.is_error is True

    def test_default_is_error_false(self):
        """Test that is_error defaults to False."""
        resp = ToolResponse(id="456", content="output")
        assert resp.is_error is False

    def test_error_with_empty_message(self):
        """Test error response with empty content."""
        resp = ToolResponse(id="789", content="", is_error=True)
        assert resp.is_error is True
        assert resp.content == ""

    def test_response_with_multiline_content(self):
        """Test response with multiline content."""
        content = "Line 1\nLine 2\nLine 3"
        resp = ToolResponse(id="123", content=content)
        assert resp.content == content
        assert "\n" in resp.content

    def test_response_with_json_content(self):
        """Test response with JSON stringified content."""
        content = '{"status": "ok", "data": [1, 2, 3]}'
        resp = ToolResponse(id="123", content=content)
        assert resp.content == content
        assert "status" in resp.content


class TestToolUseResult:
    """Tests for ToolUseResult properties (has_tool_calls, is_complete)."""

    def test_end_turn_complete(self):
        """Test end_turn result is complete."""
        result = ToolUseResult(stop_reason="end_turn", text="Done")
        assert result.is_complete is True
        assert result.has_tool_calls is False
        assert result.text == "Done"

    def test_tool_use_not_complete(self):
        """Test tool_use result is not complete."""
        call = ToolCall(id="1", name="test", input={})
        result = ToolUseResult(stop_reason="tool_use", tool_calls=[call])
        assert result.is_complete is False
        assert result.has_tool_calls is True

    def test_max_tokens_not_complete(self):
        """Test max_tokens result is not complete."""
        result = ToolUseResult(stop_reason="max_tokens", text="partial")
        assert result.is_complete is False
        assert result.has_tool_calls is False

    def test_tool_use_with_multiple_calls(self):
        """Test tool_use with multiple tool calls."""
        calls = [
            ToolCall(id="1", name="tool_a", input={"x": 1}),
            ToolCall(id="2", name="tool_b", input={"y": 2}),
        ]
        result = ToolUseResult(stop_reason="tool_use", tool_calls=calls)
        assert result.has_tool_calls is True
        assert len(result.tool_calls) == 2

    def test_end_turn_with_empty_tool_calls(self):
        """Test end_turn with empty tool_calls list."""
        result = ToolUseResult(stop_reason="end_turn", text="Result", tool_calls=[])
        assert result.is_complete is True
        assert result.has_tool_calls is False

    def test_tool_use_with_no_text(self):
        """Test tool_use without text field."""
        call = ToolCall(id="1", name="search", input={"q": "test"})
        result = ToolUseResult(stop_reason="tool_use", tool_calls=[call])
        assert result.text is None
        assert result.has_tool_calls is True

    def test_max_tokens_with_tool_calls(self):
        """Test max_tokens with partial tool calls (edge case)."""
        call = ToolCall(id="1", name="tool", input={})
        result = ToolUseResult(
            stop_reason="max_tokens", text="partial", tool_calls=[call]
        )
        assert result.is_complete is False
        assert result.has_tool_calls is True


class TestMessage:
    """Tests for Message creation with various combinations."""

    def test_user_message_text_only(self):
        """Test user message with text content."""
        msg = Message(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"
        assert msg.tool_calls is None
        assert msg.tool_responses is None

    def test_assistant_message_text_only(self):
        """Test assistant message with text content."""
        msg = Message(role="assistant", content="Response")
        assert msg.role == "assistant"
        assert msg.content == "Response"

    def test_assistant_with_tool_calls(self):
        """Test assistant message with tool calls."""
        call = ToolCall(id="1", name="search", input={"query": "test"})
        msg = Message(role="assistant", tool_calls=[call])
        assert msg.role == "assistant"
        assert msg.tool_calls is not None
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0].name == "search"

    def test_assistant_with_multiple_tool_calls(self):
        """Test assistant message with multiple tool calls."""
        calls = [
            ToolCall(id="1", name="search", input={"q": "a"}),
            ToolCall(id="2", name="lookup", input={"id": "123"}),
        ]
        msg = Message(role="assistant", tool_calls=calls)
        assert len(msg.tool_calls) == 2
        assert msg.content is None

    def test_user_with_tool_responses(self):
        """Test user message with tool responses."""
        resp = ToolResponse(id="1", content="result")
        msg = Message(role="user", tool_responses=[resp])
        assert msg.role == "user"
        assert msg.tool_responses is not None
        assert len(msg.tool_responses) == 1

    def test_user_with_multiple_tool_responses(self):
        """Test user message with multiple tool responses."""
        responses = [
            ToolResponse(id="1", content="result1"),
            ToolResponse(id="2", content="result2", is_error=True),
        ]
        msg = Message(role="user", tool_responses=responses)
        assert len(msg.tool_responses) == 2
        assert msg.tool_responses[1].is_error is True

    def test_assistant_with_text_and_tool_calls(self):
        """Test assistant message with both text and tool calls."""
        call = ToolCall(id="1", name="search", input={})
        msg = Message(role="assistant", content="Let me search", tool_calls=[call])
        assert msg.content == "Let me search"
        assert msg.tool_calls is not None
        assert len(msg.tool_calls) == 1

    def test_user_with_text_and_tool_responses(self):
        """Test user message with both text and tool responses."""
        resp = ToolResponse(id="1", content="result")
        msg = Message(role="user", content="Here are results", tool_responses=[resp])
        assert msg.content == "Here are results"
        assert msg.tool_responses is not None

    def test_message_defaults(self):
        """Test message with minimal fields (all defaults)."""
        msg = Message(role="user")
        assert msg.role == "user"
        assert msg.content is None
        assert msg.tool_calls is None
        assert msg.tool_responses is None

    def test_assistant_with_empty_tool_calls_list(self):
        """Test assistant message with empty tool calls list."""
        msg = Message(role="assistant", tool_calls=[])
        assert msg.tool_calls == []

    def test_user_with_empty_tool_responses_list(self):
        """Test user message with empty tool responses list."""
        msg = Message(role="user", tool_responses=[])
        assert msg.tool_responses == []

    def test_conversation_sequence(self):
        """Test a sequence of messages simulating conversation."""
        # User asks question
        msg1 = Message(role="user", content="Search for AI papers")
        assert msg1.role == "user"

        # Assistant calls tool
        call = ToolCall(id="search_1", name="search", input={"query": "AI papers"})
        msg2 = Message(role="assistant", tool_calls=[call])
        assert msg2.role == "assistant"

        # User provides tool result
        resp = ToolResponse(id="search_1", content="Found 5 papers")
        msg3 = Message(role="user", tool_responses=[resp])
        assert msg3.role == "user"

        # Assistant provides final answer
        msg4 = Message(role="assistant", content="I found 5 AI papers for you")
        assert msg4.content == "I found 5 AI papers for you"

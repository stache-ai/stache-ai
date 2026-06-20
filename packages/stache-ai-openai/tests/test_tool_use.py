"""Tests for OpenAI tool use response parsing."""
import json
from unittest.mock import MagicMock, patch

import pytest

from stache_ai.providers.tool_types import ToolCall, ToolUseResult


@pytest.fixture
def provider():
    """Create provider with mocked OpenAI client."""
    with patch("stache_ai_openai.llm.OpenAI") as mock_openai:
        from stache_ai.config import Settings
        from stache_ai_openai.llm import OpenAILLMProvider

        settings = MagicMock(spec=Settings)
        settings.openai_api_key = "test-key"
        settings.openai_base_url = None
        settings.openai_llm_model = "gpt-4o"

        provider = OpenAILLMProvider(settings)
        provider.client = MagicMock()
        return provider


def _mock_response(finish_reason, content=None, tool_calls=None):
    response = MagicMock()
    choice = MagicMock()
    choice.finish_reason = finish_reason
    choice.message.content = content
    choice.message.tool_calls = tool_calls
    response.choices = [choice]
    return response


class TestParseResponse:
    """Tests for _parse_response."""

    def test_text_response_has_empty_tool_calls_list(self, provider):
        """No tool calls must yield tool_calls=[] (not None)."""
        result = provider._parse_response(_mock_response("stop", content="4"))

        assert isinstance(result, ToolUseResult)
        assert result.stop_reason == "end_turn"
        assert result.text == "4"
        assert result.tool_calls == []
        assert result.has_tool_calls is False

    def test_none_content_becomes_empty_string(self, provider):
        result = provider._parse_response(_mock_response("stop", content=None))

        assert result.text == ""
        assert result.tool_calls == []

    def test_max_tokens_stop_reason(self, provider):
        result = provider._parse_response(_mock_response("length", content="partial"))

        assert result.stop_reason == "max_tokens"

    def test_tool_calls_parsed(self, provider):
        tc = MagicMock()
        tc.id = "call_123"
        tc.function.name = "search"
        tc.function.arguments = json.dumps({"query": "paris"})

        result = provider._parse_response(
            _mock_response("tool_calls", content=None, tool_calls=[tc])
        )

        assert result.stop_reason == "tool_use"
        assert result.has_tool_calls is True
        assert result.tool_calls == [
            ToolCall(id="call_123", name="search", input={"query": "paris"})
        ]

    def test_invalid_tool_arguments_become_empty_dict(self, provider):
        tc = MagicMock()
        tc.id = "call_456"
        tc.function.name = "search"
        tc.function.arguments = "{not valid json"

        result = provider._parse_response(
            _mock_response("tool_calls", content=None, tool_calls=[tc])
        )

        assert result.tool_calls[0].input == {}

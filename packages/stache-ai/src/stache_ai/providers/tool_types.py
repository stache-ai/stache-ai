"""Tool calling abstraction types for LLM providers."""
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class ToolSpec:
    """Specification for a tool that LLM can call.

    Provider-agnostic representation. Providers handle conversion to their native formats.
    """
    name: str
    description: str
    input_schema: dict[str, Any]  # JSON Schema for parameters


@dataclass
class ToolCall:
    """A tool call requested by the LLM.

    Returned from generate_with_tools() when LLM wants to use a tool.
    """
    id: str  # Unique ID for matching response
    name: str  # Tool name
    input: dict[str, Any]  # Tool arguments


@dataclass
class ToolResponse:
    """Response to a tool call, fed back to LLM.

    Used to provide tool results back to the conversation.
    """
    id: str  # Must match ToolCall.id
    content: str  # Tool output (stringified)
    is_error: bool = False  # Whether tool failed


@dataclass
class ToolUseResult:
    """Result from generate_with_tools().

    Contains either final text response or pending tool calls.
    """
    # Normalized stop reasons (providers map their native reasons to these)
    stop_reason: Literal["end_turn", "tool_use", "max_tokens"]
    text: str | None = None  # Final response text (if stop_reason="end_turn")
    tool_calls: list[ToolCall] = field(default_factory=list)

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0

    @property
    def is_complete(self) -> bool:
        return self.stop_reason == "end_turn"


@dataclass
class Message:
    """Conversation message for multi-turn tool use.

    Supports text content and tool use/results.
    """
    role: Literal["user", "assistant"]
    content: str | None = None
    tool_calls: list[ToolCall] | None = None  # For assistant messages
    tool_responses: list[ToolResponse] | None = None  # For user messages

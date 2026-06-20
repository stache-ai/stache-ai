"""OpenAI-compatible LLM provider with tool calling support."""

import json
import logging
from typing import Any

from openai import OpenAI

from stache_ai.config import Settings
from stache_ai.providers.base import LLMProvider, ModelInfo
from stache_ai.providers.tool_types import (
    Message,
    ToolCall,
    ToolResponse,
    ToolSpec,
    ToolUseResult,
)

logger = logging.getLogger(__name__)

# Curated list of GPT models available via OpenAI API
OPENAI_GPT_MODELS = [
    # Fast & cheap
    ModelInfo("gpt-4o-mini", "GPT-4o Mini", "openai", "fast"),
    ModelInfo("gpt-3.5-turbo", "GPT-3.5 Turbo", "openai", "fast"),
    # Balanced
    ModelInfo("gpt-4o", "GPT-4o", "openai", "balanced"),
    ModelInfo("gpt-4-turbo", "GPT-4 Turbo", "openai", "balanced"),
    # Premium
    ModelInfo("gpt-4", "GPT-4", "openai", "premium"),
    ModelInfo("o1", "o1", "openai", "premium"),
    ModelInfo("o1-mini", "o1-mini", "openai", "balanced"),
]

# Map OpenAI finish_reason to normalized stop_reason
STOP_REASON_MAP = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "length": "max_tokens",
    "content_filter": "end_turn",
}


class OpenAILLMProvider(LLMProvider):
    """OpenAI-compatible LLM provider.

    Works with OpenAI API and compatible services (Ollama, Together, Groq, etc.)
    via base_url configuration.

    Configuration:
        OPENAI_API_KEY: API key (required for OpenAI, ignored by Ollama)
        OPENAI_BASE_URL: API endpoint (default: OpenAI, set to http://localhost:11434/v1 for Ollama)
        OPENAI_LLM_MODEL: Model name (e.g., gpt-4o, llama3.2)
    """

    def __init__(self, settings: Settings):
        self.settings = settings

        # Support base_url for Ollama and other compatible services
        client_kwargs: dict[str, Any] = {}

        # API key - required for OpenAI, but Ollama ignores it
        api_key = settings.openai_api_key
        if not api_key and settings.openai_base_url:
            # For Ollama and similar, use a placeholder
            api_key = "ollama"
        client_kwargs["api_key"] = api_key

        # Base URL for Ollama/compatible services
        if settings.openai_base_url:
            client_kwargs["base_url"] = settings.openai_base_url

        self.client = OpenAI(**client_kwargs)

        # Model selection
        self.model = settings.openai_llm_model or settings.get_llm_model()

    @property
    def capabilities(self) -> set[str]:
        """Declare supported capabilities."""
        return {"tool_use", "structured_output"}

    def generate(self, prompt: str, **kwargs) -> str:
        """Generate text from prompt."""
        max_tokens = kwargs.get("max_tokens", 1024)
        temperature = kwargs.get("temperature", 0)

        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )

        return response.choices[0].message.content or ""

    def generate_stream(self, prompt: str, **kwargs):
        """Generate text with streaming. Yields chunks as they arrive."""
        max_tokens = kwargs.get("max_tokens", 1024)
        temperature = kwargs.get("temperature", 0)

        stream = self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
        )

        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    def generate_with_context(
        self,
        query: str,
        context: list[dict[str, Any]],
        **kwargs,
    ) -> str:
        """Generate answer with RAG context."""
        prompt = self._build_rag_prompt(query, context)
        return self.generate(prompt, **kwargs)

    def generate_with_tools(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
        system_prompt: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs,
    ) -> ToolUseResult:
        """Generate response with tool calling support.

        Args:
            messages: Conversation history
            tools: Available tools
            system_prompt: Optional system prompt
            max_tokens: Max tokens to generate
            temperature: Sampling temperature
            **kwargs: Additional provider-specific options

        Returns:
            ToolUseResult with stop_reason, text, and/or tool_calls
        """
        # Input validation
        if not messages:
            raise ValueError("messages cannot be empty")
        if not tools:
            raise ValueError("tools cannot be empty")

        # Convert messages to OpenAI format
        openai_messages = self._convert_messages(messages, system_prompt)

        # Convert tools to OpenAI format
        openai_tools = self._convert_tools(tools)

        # Make API call
        try:
            response = self.client.chat.completions.create(
                model=kwargs.get("model_id", self.model),
                messages=openai_messages,
                tools=openai_tools,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            raise

        # Parse response
        return self._parse_response(response)

    def _convert_messages(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
    ) -> list[dict[str, Any]]:
        """Convert Message objects to OpenAI message format."""
        openai_messages: list[dict[str, Any]] = []

        # Add system prompt if provided
        if system_prompt:
            openai_messages.append({"role": "system", "content": system_prompt})

        for msg in messages:
            if msg.role == "user":
                # User message - may contain tool responses
                if msg.tool_responses:
                    # Add tool results
                    for tr in msg.tool_responses:
                        openai_messages.append({
                            "role": "tool",
                            "tool_call_id": tr.id,
                            "content": tr.content,
                        })
                elif msg.content:
                    openai_messages.append({"role": "user", "content": msg.content})

            elif msg.role == "assistant":
                # Assistant message - may contain tool calls
                assistant_msg: dict[str, Any] = {"role": "assistant"}

                if msg.content:
                    assistant_msg["content"] = msg.content

                if msg.tool_calls:
                    assistant_msg["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.input),
                            },
                        }
                        for tc in msg.tool_calls
                    ]

                openai_messages.append(assistant_msg)

        return openai_messages

    def _convert_tools(self, tools: list[ToolSpec]) -> list[dict[str, Any]]:
        """Convert ToolSpec objects to OpenAI tool format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                },
            }
            for tool in tools
        ]

    def _parse_response(self, response) -> ToolUseResult:
        """Parse OpenAI response into ToolUseResult."""
        choice = response.choices[0]
        message = choice.message
        finish_reason = choice.finish_reason

        # Map finish_reason to normalized stop_reason
        stop_reason = STOP_REASON_MAP.get(finish_reason, "end_turn")

        # Check for tool calls
        if message.tool_calls:
            tool_calls = []
            for tc in message.tool_calls:
                # Parse arguments from JSON string
                try:
                    arguments = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse tool arguments: {tc.function.arguments}")
                    arguments = {}

                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        input=arguments,
                    )
                )

            return ToolUseResult(
                stop_reason="tool_use",
                text=message.content,
                tool_calls=tool_calls,
            )

        # No tool calls - return text response
        return ToolUseResult(
            stop_reason=stop_reason,
            text=message.content or "",
            tool_calls=[],
        )

    def _build_rag_prompt(self, query: str, context: list[dict[str, Any]]) -> str:
        """Build the RAG prompt from query and context."""
        context_str = "\n\n".join(
            [f"[Source {i+1}]\n{chunk['content']}" for i, chunk in enumerate(context)]
        )

        return f"""You are a helpful AI assistant with access to the user's knowledge base.

Answer the question directly using the information below. Do not mention "context", "provided information", or reference where the information came from - just answer naturally as if you know this information. If you don't have enough information to answer, simply say you don't have that information.

Information:
{context_str}

Question: {query}

Answer:"""

    def get_available_models(self) -> list[ModelInfo]:
        """Get list of GPT models available via OpenAI API."""
        return OPENAI_GPT_MODELS

    def get_default_model(self) -> str:
        """Get the configured default model."""
        return self.model

    def generate_with_model(
        self,
        prompt: str,
        model_id: str,
        **kwargs,
    ) -> str:
        """Generate text using a specific model."""
        max_tokens = kwargs.get("max_tokens", 1024)
        temperature = kwargs.get("temperature", 0)

        response = self.client.chat.completions.create(
            model=model_id,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )

        return response.choices[0].message.content or ""

    def generate_with_context_and_model(
        self,
        query: str,
        context: list[dict[str, Any]],
        model_id: str,
        **kwargs,
    ) -> str:
        """Generate answer with context using a specific model."""
        prompt = self._build_rag_prompt(query, context)
        return self.generate_with_model(prompt, model_id, **kwargs)

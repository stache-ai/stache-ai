"""Ollama LLM provider"""

from typing import List, Dict, Any
import json
import re
import logging
from stache_ai.providers.base import LLMProvider, ModelInfo
from stache_ai.config import Settings
from .client import OllamaClient

logger = logging.getLogger(__name__)


class OllamaLLMProvider(LLMProvider):
    """Ollama local LLM provider"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.model = settings.ollama_model
        self.client = OllamaClient(settings)
        self._cached_models: List[ModelInfo] | None = None

    @property
    def capabilities(self) -> set[str]:
        """Ollama supports structured output via JSON mode."""
        return {"structured_output", "generate"}

    def generate(self, prompt: str, **kwargs) -> str:
        """Generate text from prompt"""
        temperature = kwargs.get('temperature', 0)

        request_payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature
            }
        }

        response = self.client.post(
            "/api/generate",
            json=request_payload,
            timeout=self.client.llm_timeout
        )
        response.raise_for_status()
        return response.json()["response"]

    def generate_with_context(
        self,
        query: str,
        context: List[Dict[str, Any]],
        **kwargs
    ) -> str:
        """Generate answer with context"""
        prompt = self._build_rag_prompt(query, context)
        return self.generate(prompt, **kwargs)

    def _build_rag_prompt(self, query: str, context: List[Dict[str, Any]]) -> str:
        """Build the RAG prompt from query and context"""
        context_str = "\n\n".join([
            f"[Source {i+1}]\n{chunk['content']}"
            for i, chunk in enumerate(context)
        ])

        return f"""You are a helpful AI assistant with access to the user's knowledge base.

Answer the question directly using the information below. Do not mention "context", "provided information", or reference where the information came from - just answer naturally as if you know this information. If you don't have enough information to answer, simply say you don't have that information.

Information:
{context_str}

Question: {query}

Answer:"""

    def get_available_models(self) -> List[ModelInfo]:
        """Get list of models available from local Ollama server"""
        if self._cached_models is not None:
            return self._cached_models

        try:
            response = self.client.get(
                "/api/tags",
                timeout=self.client.default_timeout
            )
            response.raise_for_status()
            data = response.json()

            models = []
            for model in data.get("models", []):
                name = model.get("name", "")
                # Infer tier from model name patterns
                tier = "balanced"
                if any(x in name.lower() for x in ["small", "mini", "tiny", "1b", "3b"]):
                    tier = "fast"
                elif any(x in name.lower() for x in ["70b", "72b", "large", "opus"]):
                    tier = "premium"

                models.append(ModelInfo(
                    id=name,
                    name=name,
                    provider="ollama",
                    tier=tier
                ))

            self._cached_models = models
            return models

        except Exception as e:
            logger.warning(f"Failed to fetch Ollama models: {e}")
            # Return empty list - will use default model only
            return []

    def get_default_model(self) -> str:
        """Get the configured default model"""
        return self.model

    def get_name(self) -> str:
        """Get provider name"""
        return f"ollama/{self.model}"

    def generate_with_model(
        self,
        prompt: str,
        model_id: str,
        **kwargs
    ) -> str:
        """Generate text using a specific Ollama model"""
        temperature = kwargs.get('temperature', 0)

        request_payload = {
            "model": model_id,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature
            }
        }

        response = self.client.post(
            "/api/generate",
            json=request_payload,
            timeout=self.client.llm_timeout
        )
        response.raise_for_status()
        return response.json()["response"]

    def generate_with_context_and_model(
        self,
        query: str,
        context: List[Dict[str, Any]],
        model_id: str,
        **kwargs
    ) -> str:
        """Generate answer with context using a specific model"""
        prompt = self._build_rag_prompt(query, context)
        return self.generate_with_model(prompt, model_id, **kwargs)

    def generate_structured(
        self,
        prompt: str,
        schema: dict[str, Any],
        max_tokens: int = 2048,
        temperature: float = 0.0,
        **kwargs
    ) -> dict[str, Any]:
        """Generate JSON output matching schema.

        Uses Ollama's JSON mode with schema in system prompt for guidance.
        Falls back to JSON extraction from response if model doesn't follow format.

        Raises:
            RuntimeError: On timeout or HTTP errors from Ollama
            ValueError: If JSON cannot be extracted from response
        """
        import httpx

        schema_prompt = self._build_schema_prompt(schema)

        request_payload = {
            "model": self.model,
            "prompt": prompt,
            "system": schema_prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            }
        }

        try:
            response = self.client.post(
                "/api/generate",
                json=request_payload,
                timeout=self.client.llm_timeout
            )
            response.raise_for_status()
        except httpx.TimeoutException as e:
            raise RuntimeError(
                f"Ollama request timed out after {self.client.llm_timeout}s"
            ) from e
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"Ollama returned {e.response.status_code}: {e.response.text[:200]}"
            ) from e

        response_data = response.json()
        if "error" in response_data:
            raise RuntimeError(f"Ollama returned error: {response_data['error']}")
        response_text = response_data.get("response", "")
        if not response_text:
            raise ValueError("Ollama returned empty response")
        return self._parse_json_response(response_text, schema)

    def _build_schema_prompt(self, schema: dict[str, Any]) -> str:
        """Build system prompt with JSON schema guidance."""
        properties = schema.get("properties", {})
        required = schema.get("required", [])

        field_descriptions = []
        for field, spec in properties.items():
            field_type = spec.get("type", "string")
            is_required = "(required)" if field in required else "(optional)"

            if field_type == "array" and "items" in spec:
                item_type = spec["items"].get("type", "string")
                if "properties" in spec["items"]:
                    obj_fields = ", ".join(spec["items"]["properties"].keys())
                    field_descriptions.append(
                        f'- "{field}": array of objects with fields [{obj_fields}] {is_required}'
                    )
                else:
                    field_descriptions.append(
                        f'- "{field}": array of {item_type} {is_required}'
                    )
            elif field_type == "string" and "enum" in spec:
                enum_values = ", ".join(f'"{v}"' for v in spec["enum"])
                field_descriptions.append(
                    f'- "{field}": one of [{enum_values}] {is_required}'
                )
            else:
                field_descriptions.append(
                    f'- "{field}": {field_type} {is_required}'
                )

        return f"""You are a JSON generator. Output ONLY valid JSON matching this schema:

{chr(10).join(field_descriptions)}

Do not include any text before or after the JSON object."""

    def _parse_json_response(
        self,
        response_text: str,
        schema: dict[str, Any]
    ) -> dict[str, Any]:
        """Parse JSON from response, with fallback extraction."""
        # Direct parse
        try:
            result = json.loads(response_text.strip())
            if isinstance(result, dict):
                return self._apply_defaults(result, schema)
        except json.JSONDecodeError:
            pass

        # Fallback 1: find first { to last } - handles most nested structures
        start = response_text.find('{')
        end = response_text.rfind('}')
        if start != -1 and end > start:
            try:
                result = json.loads(response_text[start:end + 1])
                if isinstance(result, dict):
                    return self._apply_defaults(result, schema)
            except json.JSONDecodeError:
                pass

        # Fallback 2: extract from markdown code blocks
        patterns = [
            r'```json\s*(.*?)\s*```',
            r'```\s*(.*?)\s*```',
        ]

        for pattern in patterns:
            match = re.search(pattern, response_text, re.DOTALL)
            if match:
                try:
                    result = json.loads(match.group(1).strip())
                    if isinstance(result, dict):
                        return self._apply_defaults(result, schema)
                except json.JSONDecodeError:
                    continue

        raise ValueError(f"Could not extract JSON from: {response_text[:500]}")

    def _apply_defaults(
        self,
        result: dict[str, Any],
        schema: dict[str, Any]
    ) -> dict[str, Any]:
        """Apply schema defaults for missing optional fields."""
        properties = schema.get("properties", {})
        for field, spec in properties.items():
            if field not in result:
                if "default" in spec:
                    result[field] = spec["default"]
                elif spec.get("type") == "array":
                    result[field] = []
                elif spec.get("type") == "boolean":
                    result[field] = False
        return result

"""Ollama LLM provider"""

from typing import List, Dict, Any
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

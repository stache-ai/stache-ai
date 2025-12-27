"""OpenAI GPT LLM provider"""

from typing import List, Dict, Any
from stache_ai.providers.base import LLMProvider, ModelInfo
from stache_ai.config import Settings
from openai import OpenAI

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


class OpenAILLMProvider(LLMProvider):
    """OpenAI GPT LLM provider"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model = settings.get_llm_model()

    def generate(self, prompt: str, **kwargs) -> str:
        """Generate text from prompt"""
        max_tokens = kwargs.get('max_tokens', 1024)
        temperature = kwargs.get('temperature', 0)

        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        return response.choices[0].message.content

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
        """Get list of GPT models available via OpenAI API"""
        return OPENAI_GPT_MODELS

    def get_default_model(self) -> str:
        """Get the configured default model"""
        return self.model

    def generate_with_model(
        self,
        prompt: str,
        model_id: str,
        **kwargs
    ) -> str:
        """Generate text using a specific model"""
        max_tokens = kwargs.get('max_tokens', 1024)
        temperature = kwargs.get('temperature', 0)

        response = self.client.chat.completions.create(
            model=model_id,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        return response.choices[0].message.content

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

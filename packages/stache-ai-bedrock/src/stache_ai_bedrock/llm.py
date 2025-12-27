"""AWS Bedrock LLM provider - Native AWS LLM access via IAM

Uses the Converse API which supports inference profiles for newer Claude models.
Inference profiles (e.g., us.anthropic.claude-sonnet-4-5-20250929-v1:0) are required
for on-demand access to Claude 3.5+ and 4.x models.
"""

import logging
from typing import List, Dict, Any

import boto3
from botocore.exceptions import ClientError

from stache_ai.providers.base import LLMProvider, ModelInfo
from stache_ai.config import Settings

logger = logging.getLogger(__name__)

# Curated list of Claude models available via Bedrock inference profiles
# Sorted by capability tier
BEDROCK_CLAUDE_MODELS = [
    # Fast & cheap
    ModelInfo("us.anthropic.claude-3-haiku-20240307-v1:0", "Claude 3 Haiku", "anthropic", "fast"),
    ModelInfo("us.anthropic.claude-3-5-haiku-20241022-v1:0", "Claude 3.5 Haiku", "anthropic", "fast"),
    ModelInfo("us.anthropic.claude-haiku-4-5-20251001-v1:0", "Claude Haiku 4.5", "anthropic", "fast"),
    # Balanced
    ModelInfo("us.anthropic.claude-3-5-sonnet-20241022-v2:0", "Claude 3.5 Sonnet v2", "anthropic", "balanced"),
    ModelInfo("us.anthropic.claude-3-7-sonnet-20250219-v1:0", "Claude 3.7 Sonnet", "anthropic", "balanced"),
    ModelInfo("us.anthropic.claude-sonnet-4-20250514-v1:0", "Claude Sonnet 4", "anthropic", "balanced"),
    ModelInfo("us.anthropic.claude-sonnet-4-5-20250929-v1:0", "Claude Sonnet 4.5", "anthropic", "balanced"),
    # Premium
    ModelInfo("us.anthropic.claude-3-opus-20240229-v1:0", "Claude 3 Opus", "anthropic", "premium"),
    ModelInfo("us.anthropic.claude-opus-4-20250514-v1:0", "Claude Opus 4", "anthropic", "premium"),
    ModelInfo("us.anthropic.claude-opus-4-1-20250805-v1:0", "Claude Opus 4.1", "anthropic", "premium"),
    ModelInfo("us.anthropic.claude-opus-4-5-20251101-v1:0", "Claude Opus 4.5", "anthropic", "premium"),
]

# Non-Anthropic Bedrock models
BEDROCK_OTHER_MODELS = [
    # Amazon Titan & Nova - Fast
    ModelInfo("amazon.titan-text-express-v1", "Titan Text Express", "amazon", "fast"),
    ModelInfo("us.amazon.nova-micro-v1:0", "Amazon Nova Micro", "amazon", "fast"),
    ModelInfo("us.amazon.nova-lite-v1:0", "Amazon Nova Lite", "amazon", "fast"),
    # Amazon - Balanced
    ModelInfo("amazon.titan-text-premier-v1:0", "Titan Text Premier", "amazon", "balanced"),
    ModelInfo("us.amazon.nova-pro-v1:0", "Amazon Nova Pro", "amazon", "balanced"),
    # Meta Llama - Fast
    ModelInfo("meta.llama3-8b-instruct-v1:0", "Llama 3 8B Instruct", "meta", "fast"),
    # Meta Llama - Balanced
    ModelInfo("meta.llama3-70b-instruct-v1:0", "Llama 3 70B Instruct", "meta", "balanced"),
    ModelInfo("us.meta.llama3-2-90b-instruct-v1:0", "Llama 3.2 90B Instruct", "meta", "balanced"),
    # Meta Llama - Premium
    ModelInfo("meta.llama3-1-405b-instruct-v1:0", "Llama 3.1 405B Instruct", "meta", "premium"),
    # Mistral - Fast
    ModelInfo("mistral.mistral-7b-instruct-v0:2", "Mistral 7B Instruct", "mistral", "fast"),
    # Mistral - Balanced
    ModelInfo("mistral.mixtral-8x7b-instruct-v0:1", "Mixtral 8x7B Instruct", "mistral", "balanced"),
    # Mistral - Premium
    ModelInfo("mistral.mistral-large-2402-v1:0", "Mistral Large", "mistral", "premium"),
    # Cohere - Balanced
    ModelInfo("cohere.command-r-v1:0", "Cohere Command R", "cohere", "balanced"),
    # Cohere - Premium
    ModelInfo("cohere.command-r-plus-v1:0", "Cohere Command R+", "cohere", "premium"),
    # AI21 - Balanced
    ModelInfo("ai21.jamba-1-5-mini-v1:0", "AI21 Jamba 1.5 Mini", "ai21", "balanced"),
    # AI21 - Premium
    ModelInfo("ai21.jamba-1-5-large-v1:0", "AI21 Jamba 1.5 Large", "ai21", "premium"),
]

# Combined list of all Bedrock models
BEDROCK_ALL_MODELS = BEDROCK_CLAUDE_MODELS + BEDROCK_OTHER_MODELS


class BedrockLLMProvider(LLMProvider):
    """AWS Bedrock LLM provider for Lambda-native deployments

    Uses the Converse API which:
    - Supports inference profiles (required for Claude 3.5+, 4.x models)
    - Provides a unified interface across model families
    - Handles model-specific formatting automatically

    Required IAM permissions:
    - bedrock:InvokeModel

    Note: Newer Claude models require inference profile IDs (e.g., us.anthropic.claude-*)
    not direct model IDs (e.g., anthropic.claude-*). Use list-inference-profiles to find
    the correct ID for your model.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = boto3.client(
            'bedrock-runtime',
            region_name=settings.aws_region
        )
        self.model_id = settings.bedrock_llm_model
        logger.info(f"Bedrock LLM provider initialized: {self.model_id}")

    def generate(self, prompt: str, **kwargs) -> str:
        """Generate text from prompt using Bedrock Converse API"""
        max_tokens = kwargs.get('max_tokens', 1024)
        temperature = kwargs.get('temperature', 0)

        return self._converse(prompt, max_tokens, temperature)

    def _converse(self, prompt: str, max_tokens: int, temperature: float) -> str:
        """Generate using Bedrock Converse API (supports all model families)"""
        try:
            response = self.client.converse(
                modelId=self.model_id,
                messages=[
                    {
                        "role": "user",
                        "content": [{"text": prompt}]
                    }
                ],
                inferenceConfig={
                    "maxTokens": max_tokens,
                    "temperature": temperature
                }
            )

            # Extract text from response
            output_message = response.get('output', {}).get('message', {})
            content_blocks = output_message.get('content', [])

            # Concatenate all text blocks
            text_parts = []
            for block in content_blocks:
                if 'text' in block:
                    text_parts.append(block['text'])

            return ''.join(text_parts)

        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_msg = e.response['Error'].get('Message', str(e))

            if error_code == 'AccessDeniedException':
                raise RuntimeError(
                    f"Access denied to Bedrock model '{self.model_id}'. "
                    "Ensure the model is enabled in your AWS account and IAM permissions are configured."
                ) from e
            elif error_code == 'ThrottlingException':
                raise RuntimeError(
                    f"Bedrock request throttled for model '{self.model_id}'. "
                    "Consider implementing retry logic or reducing request rate."
                ) from e
            elif error_code == 'ModelNotReadyException':
                raise RuntimeError(
                    f"Bedrock model '{self.model_id}' is not ready. Please try again later."
                ) from e
            elif error_code == 'ValidationException':
                # Check if it's the inference profile error
                if 'inference profile' in error_msg.lower():
                    raise ValueError(
                        f"Model '{self.model_id}' requires an inference profile. "
                        "Use 'aws bedrock list-inference-profiles' to find the correct ID. "
                        f"Example: us.anthropic.claude-sonnet-4-5-20250929-v1:0"
                    ) from e
                raise ValueError(
                    f"Invalid request to Bedrock model '{self.model_id}': {error_msg}"
                ) from e
            else:
                logger.error(f"Bedrock error ({error_code}): {e}")
                raise

    def generate_with_context(
        self,
        query: str,
        context: List[Dict[str, Any]],
        **kwargs
    ) -> str:
        """Generate answer with context (RAG)"""
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
        """Get list of all models available via Bedrock"""
        return BEDROCK_ALL_MODELS

    def get_default_model(self) -> str:
        """Get the configured default model"""
        return self.model_id

    def generate_with_model(
        self,
        prompt: str,
        model_id: str,
        **kwargs
    ) -> str:
        """Generate text using a specific Bedrock model"""
        max_tokens = kwargs.get('max_tokens', 1024)
        temperature = kwargs.get('temperature', 0)

        return self._converse_with_model(prompt, model_id, max_tokens, temperature)

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

    def _converse_with_model(
        self,
        prompt: str,
        model_id: str,
        max_tokens: int,
        temperature: float
    ) -> str:
        """Generate using Bedrock Converse API with specified model"""
        try:
            response = self.client.converse(
                modelId=model_id,
                messages=[
                    {
                        "role": "user",
                        "content": [{"text": prompt}]
                    }
                ],
                inferenceConfig={
                    "maxTokens": max_tokens,
                    "temperature": temperature
                }
            )

            # Extract text from response
            output_message = response.get('output', {}).get('message', {})
            content_blocks = output_message.get('content', [])

            text_parts = []
            for block in content_blocks:
                if 'text' in block:
                    text_parts.append(block['text'])

            return ''.join(text_parts)

        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_msg = e.response['Error'].get('Message', str(e))

            if error_code == 'AccessDeniedException':
                raise RuntimeError(
                    f"Access denied to Bedrock model '{model_id}'. "
                    "Ensure the model is enabled in your AWS account and IAM permissions are configured."
                ) from e
            elif error_code == 'ValidationException':
                if 'inference profile' in error_msg.lower():
                    raise ValueError(
                        f"Model '{model_id}' requires an inference profile. "
                        "Use 'aws bedrock list-inference-profiles' to find the correct ID."
                    ) from e
                raise ValueError(
                    f"Invalid request to Bedrock model '{model_id}': {error_msg}"
                ) from e
            else:
                logger.error(f"Bedrock error ({error_code}): {e}")
                raise

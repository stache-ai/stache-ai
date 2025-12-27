"""AWS Bedrock Embedding provider - Native AWS embeddings via IAM"""

import json
import logging
from typing import List
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3

from stache_ai.providers.base import EmbeddingProvider
from stache_ai.config import Settings

logger = logging.getLogger(__name__)


class BedrockEmbeddingProvider(EmbeddingProvider):
    """AWS Bedrock Embedding provider for Lambda-native deployments

    Required IAM permissions:
    - bedrock:InvokeModel

    Note: The embedding model must be enabled in your AWS account.
    """

    # Model dimension mapping
    DIMENSIONS = {
        'amazon.titan-embed-text-v1': 1536,
        'amazon.titan-embed-text-v2:0': 1024,
        'amazon.titan-embed-image-v1': 1024,
        'cohere.embed-english-v3': 1024,
        'cohere.embed-multilingual-v3': 1024,
    }

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = boto3.client(
            'bedrock-runtime',
            region_name=settings.aws_region
        )
        self.model_id = settings.bedrock_embedding_model
        self._dimensions = self._get_model_dimensions()
        logger.info(f"Bedrock Embedding provider initialized: {self.model_id} ({self._dimensions} dims)")

    def _get_model_dimensions(self) -> int:
        """Get embedding dimensions for the configured model"""
        # Check exact match first
        if self.model_id in self.DIMENSIONS:
            return self.DIMENSIONS[self.model_id]

        # Check partial match
        for model_prefix, dims in self.DIMENSIONS.items():
            if model_prefix in self.model_id:
                return dims

        # Default
        logger.warning(f"Unknown model dimensions for {self.model_id}, defaulting to 1024")
        return 1024

    def embed(self, text: str, input_type: str = "search_document") -> List[float]:
        """Generate embedding for a single text

        Args:
            text: Text to embed
            input_type: For Cohere models - "search_document" for indexing,
                       "search_query" for queries. Ignored for Titan models.
        """
        if 'titan' in self.model_id.lower():
            return self._embed_titan(text)
        elif 'cohere' in self.model_id.lower():
            return self._embed_cohere(text, input_type)
        else:
            # Default to Titan format
            return self._embed_titan(text)

    def embed_query(self, text: str) -> List[float]:
        """Generate embedding for a search query (optimized for retrieval)"""
        return self.embed(text, input_type="search_query")

    def _embed_titan(self, text: str) -> List[float]:
        """Generate embedding using Amazon Titan"""
        body = {
            "inputText": text
        }

        # Titan v2 supports dimensions parameter
        if 'v2' in self.model_id:
            body["dimensions"] = self._dimensions
            body["normalize"] = True

        response = self.client.invoke_model(
            modelId=self.model_id,
            body=json.dumps(body),
            contentType='application/json',
            accept='application/json'
        )

        response_body = json.loads(response['body'].read())
        return response_body['embedding']

    def _embed_cohere(self, text: str, input_type: str = "search_document") -> List[float]:
        """Generate embedding using Cohere on Bedrock

        Args:
            text: Text to embed
            input_type: "search_document" for documents being indexed,
                       "search_query" for search queries
        """
        body = {
            "texts": [text],
            "input_type": input_type,
            "truncate": "END"
        }

        response = self.client.invoke_model(
            modelId=self.model_id,
            body=json.dumps(body),
            contentType='application/json',
            accept='application/json'
        )

        response_body = json.loads(response['body'].read())
        return response_body['embeddings'][0]

    def embed_batch(self, texts: List[str], input_type: str = "search_document") -> List[List[float]]:
        """Generate embeddings for multiple texts

        Args:
            texts: List of texts to embed
            input_type: For Cohere models - "search_document" for indexing,
                       "search_query" for queries. Ignored for Titan models.
        """
        if not texts:
            return []

        # Cohere supports batch natively
        if 'cohere' in self.model_id.lower():
            return self._embed_batch_cohere(texts, input_type)

        # Titan requires individual calls - parallelize for throughput
        return self._embed_batch_titan_parallel(texts, input_type)

    def _embed_batch_titan_parallel(
        self,
        texts: List[str],
        input_type: str = "search_document",
        max_workers: int = 10
    ) -> List[List[float]]:
        """Parallel batch embedding for Titan models

        Uses ThreadPoolExecutor to parallelize individual Titan calls.
        Bedrock supports concurrent requests within account limits.

        Args:
            texts: List of texts to embed
            input_type: Embedding type (ignored for Titan, kept for API consistency)
            max_workers: Max concurrent threads (default 10, respects Bedrock limits)

        Returns:
            List of embeddings in the same order as input texts
        """
        if len(texts) <= 2:
            # Sequential for small batches (overhead not worth it)
            return [self.embed(text, input_type) for text in texts]

        # Use indexed results to preserve order
        results = [None] * len(texts)

        def embed_with_index(idx: int, text: str) -> tuple:
            return idx, self.embed(text, input_type)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(embed_with_index, i, text): i
                for i, text in enumerate(texts)
            }

            for future in as_completed(futures):
                idx, embedding = future.result()
                results[idx] = embedding

        return results

    def _embed_batch_cohere(self, texts: List[str], input_type: str = "search_document") -> List[List[float]]:
        """Batch embedding using Cohere on Bedrock

        Args:
            texts: List of texts to embed
            input_type: "search_document" for documents, "search_query" for queries
        """
        # Cohere has a batch limit, process in chunks
        batch_size = 96
        all_embeddings = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]

            body = {
                "texts": batch,
                "input_type": input_type,
                "truncate": "END"
            }

            response = self.client.invoke_model(
                modelId=self.model_id,
                body=json.dumps(body),
                contentType='application/json',
                accept='application/json'
            )

            response_body = json.loads(response['body'].read())
            all_embeddings.extend(response_body['embeddings'])

        return all_embeddings

    def get_dimensions(self) -> int:
        """Get the dimension size of embeddings"""
        return self._dimensions

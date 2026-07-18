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
    #
    # Cohere Embed v4 (`cohere.embed-v4:0`) supports Matryoshka output_dimension
    # of 256/512/1024/1536 (Bedrock default is 1536 if unspecified). We default
    # v4 to 1024 here so it matches the 1024 dimension the S3 Vectors index is
    # created with. If a deployment ever
    # needs a different v4 dimension, it is entirely config-driven (whatever
    # `_dimensions` resolves to is sent as `output_dimension`) - just don't
    # change this default without also updating the vector index dimension.
    DIMENSIONS = {
        'amazon.titan-embed-text-v1': 1536,
        'amazon.titan-embed-text-v2:0': 1024,
        'amazon.titan-embed-image-v1': 1024,
        'cohere.embed-english-v3': 1024,
        'cohere.embed-multilingual-v3': 1024,
        'cohere.embed-v4:0': 1024,
        'cohere.embed-v4': 1024,
    }

    # Cohere Embed v4 request/response schema, per AWS Bedrock docs
    # (docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-embed-v4.html,
    # verified 2026-07). NOTE: not yet confirmed against a live `invoke-model`
    # call in this account - the deployer should run one CLI invoke test
    # against the real model id before relying on this in production, since
    # Bedrock model schemas have been known to shift between preview/GA.
    COHERE_V4_BATCH_SIZE = 96

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

    def _is_cohere_v4(self) -> bool:
        """Whether the configured model is Cohere Embed v4 (vs v3)

        Detected purely from the configured model id (e.g. `cohere.embed-v4:0`).
        v3 model ids (`cohere.embed-english-v3`, `cohere.embed-multilingual-v3`)
        don't contain "v4", so this is unambiguous. Selection is entirely
        config-driven via `bedrock_embedding_model` - v3 and v4 code paths
        coexist and neither is deprecated.
        """
        return 'v4' in self.model_id.lower()

    def embed(self, text: str, input_type: str = "search_document", *, context=None) -> List[float]:
        """Generate embedding for a single text

        Args:
            text: Text to embed
            input_type: For Cohere models - "search_document" for indexing,
                       "search_query" for queries. Ignored for Titan models.
            context: optional request context (caller identity); keyword-only,
                accepted and ignored.
        """
        if 'titan' in self.model_id.lower():
            return self._embed_titan(text)
        elif 'cohere' in self.model_id.lower():
            if self._is_cohere_v4():
                return self._embed_cohere_v4(text, input_type)
            return self._embed_cohere(text, input_type)
        else:
            # Default to Titan format
            return self._embed_titan(text)

    def embed_query(self, text: str, *, context=None) -> List[float]:
        """Generate embedding for a search query (optimized for retrieval)"""
        return self.embed(text, input_type="search_query", context=context)

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

    def _embed_cohere_v4(self, text: str, input_type: str = "search_document") -> List[float]:
        """Generate embedding using Cohere Embed v4 on Bedrock

        v4's request/response schema differs from v3: it takes
        `embedding_types` + `output_dimension` (Matryoshka, config-driven via
        `self._dimensions`), and its response keys embeddings by type
        (e.g. `{"embeddings": {"float": [[...]]}}`) when multiple
        embedding_types are requested, or a bare list when only one type is
        requested. See `_parse_cohere_v4_embeddings` for the defensive parse.

        Args:
            text: Text to embed
            input_type: "search_document" for documents being indexed,
                       "search_query" for search queries (v4 also supports
                       "classification" and "clustering", not used here)
        """
        body = {
            "texts": [text],
            "input_type": input_type,
            "embedding_types": ["float"],
            "output_dimension": self._dimensions,
        }

        response = self.client.invoke_model(
            modelId=self.model_id,
            body=json.dumps(body),
            contentType='application/json',
            accept='application/json'
        )

        response_body = json.loads(response['body'].read())
        return self._parse_cohere_v4_embeddings(response_body)[0]

    @staticmethod
    def _parse_cohere_v4_embeddings(response_body: dict) -> List[List[float]]:
        """Extract float vectors (in input order) from a Cohere v4 response

        Handles both documented shapes defensively:
        - multiple embedding_types requested: {"embeddings": {"float": [[...]], ...}}
        - single embedding_type requested: {"embeddings": [[...]]}
        """
        embeddings = response_body['embeddings']
        if isinstance(embeddings, dict):
            if 'float' in embeddings:
                return embeddings['float']
            # Graceful fallback if "float" isn't present but another type is
            return next(iter(embeddings.values()))
        return embeddings

    def embed_batch(self, texts: List[str], input_type: str = "search_document", *, context=None) -> List[List[float]]:
        """Generate embeddings for multiple texts

        Args:
            texts: List of texts to embed
            input_type: For Cohere models - "search_document" for indexing,
                       "search_query" for queries. Ignored for Titan models.
            context: optional request context (caller identity); keyword-only,
                accepted and ignored.
        """
        if not texts:
            return []

        # Cohere supports batch natively
        if 'cohere' in self.model_id.lower():
            if self._is_cohere_v4():
                return self._embed_batch_cohere_v4(texts, input_type)
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

    def _embed_batch_cohere(
        self,
        texts: List[str],
        input_type: str = "search_document",
        max_workers: int = 10
    ) -> List[List[float]]:
        """Parallel batch embedding using Cohere on Bedrock

        Cohere supports up to 96 texts per API call. For larger sets,
        batches are sent in parallel using ThreadPoolExecutor.

        Args:
            texts: List of texts to embed
            input_type: "search_document" for documents, "search_query" for queries
            max_workers: Max concurrent batch requests (default 10)
        """
        batch_size = 96

        # Single batch - no parallelism needed
        if len(texts) <= batch_size:
            return self._invoke_cohere_batch(texts, input_type)

        # Split into batches and process in parallel
        batches = [
            (i, texts[start:start + batch_size])
            for i, start in enumerate(range(0, len(texts), batch_size))
        ]

        results = [None] * len(batches)

        def embed_batch_with_index(idx: int, batch: List[str]) -> tuple:
            return idx, self._invoke_cohere_batch(batch, input_type)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(embed_batch_with_index, idx, batch): idx
                for idx, batch in batches
            }

            for future in as_completed(futures):
                idx, embeddings = future.result()
                results[idx] = embeddings

        # Flatten ordered batch results
        all_embeddings = []
        for batch_result in results:
            all_embeddings.extend(batch_result)
        return all_embeddings

    def _invoke_cohere_batch(self, texts: List[str], input_type: str) -> List[List[float]]:
        """Invoke Cohere embedding API for a single batch (up to 96 texts)"""
        body = {
            "texts": texts,
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
        return response_body['embeddings']

    def _embed_batch_cohere_v4(
        self,
        texts: List[str],
        input_type: str = "search_document",
        max_workers: int = 10
    ) -> List[List[float]]:
        """Parallel batch embedding using Cohere Embed v4 on Bedrock

        Same batching pattern as v3: up to COHERE_V4_BATCH_SIZE (96) texts
        per call (per AWS docs, unchanged from v3), larger sets are split
        into batches and sent in parallel, preserving input order.

        Args:
            texts: List of texts to embed
            input_type: "search_document" for documents, "search_query" for queries
            max_workers: Max concurrent batch requests (default 10)
        """
        batch_size = self.COHERE_V4_BATCH_SIZE

        # Single batch - no parallelism needed
        if len(texts) <= batch_size:
            return self._invoke_cohere_v4_batch(texts, input_type)

        # Split into batches and process in parallel
        batches = [
            (i, texts[start:start + batch_size])
            for i, start in enumerate(range(0, len(texts), batch_size))
        ]

        results = [None] * len(batches)

        def embed_batch_with_index(idx: int, batch: List[str]) -> tuple:
            return idx, self._invoke_cohere_v4_batch(batch, input_type)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(embed_batch_with_index, idx, batch): idx
                for idx, batch in batches
            }

            for future in as_completed(futures):
                idx, embeddings = future.result()
                results[idx] = embeddings

        # Flatten ordered batch results
        all_embeddings = []
        for batch_result in results:
            all_embeddings.extend(batch_result)
        return all_embeddings

    def _invoke_cohere_v4_batch(self, texts: List[str], input_type: str) -> List[List[float]]:
        """Invoke Cohere Embed v4 API for a single batch (up to COHERE_V4_BATCH_SIZE texts)"""
        body = {
            "texts": texts,
            "input_type": input_type,
            "embedding_types": ["float"],
            "output_dimension": self._dimensions,
        }

        response = self.client.invoke_model(
            modelId=self.model_id,
            body=json.dumps(body),
            contentType='application/json',
            accept='application/json'
        )

        response_body = json.loads(response['body'].read())
        return self._parse_cohere_v4_embeddings(response_body)

    def get_dimensions(self) -> int:
        """Get the dimension size of embeddings"""
        return self._dimensions

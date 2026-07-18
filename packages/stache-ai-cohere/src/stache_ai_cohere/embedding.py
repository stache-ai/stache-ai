"""Cohere embedding provider"""

import json
import logging
import tempfile
from typing import Dict, List, Optional

import cohere
from stache_ai.config import Settings
from stache_ai.providers.base import EmbeddingProvider

logger = logging.getLogger(__name__)


class CohereEmbeddingProvider(EmbeddingProvider):
    """Cohere embedding provider"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = cohere.Client(api_key=settings.cohere_api_key)
        self.model = settings.get_embedding_model()
        self._dimensions = 1024  # Cohere embed-english-v3.0 is 1024

    def embed(self, text: str, *, context=None) -> List[float]:
        """Generate embedding for single text (for documents).

        ``context`` (keyword-only request context) is accepted and ignored.
        """
        response = self.client.embed(
            texts=[text],
            model=self.model,
            input_type="search_document"
        )
        return response.embeddings[0]

    def embed_query(self, text: str, *, context=None) -> List[float]:
        """Generate embedding for search query.

        ``context`` (keyword-only request context) is accepted and ignored.
        """
        response = self.client.embed(
            texts=[text],
            model=self.model,
            input_type="search_query"
        )
        return response.embeddings[0]

    def embed_batch(self, texts: List[str], *, context=None) -> List[List[float]]:
        """Generate embeddings for multiple texts (for documents).

        ``context`` (keyword-only request context) is accepted and ignored.
        """
        response = self.client.embed(
            texts=texts,
            model=self.model,
            input_type="search_document"
        )
        return response.embeddings

    def get_dimensions(self) -> int:
        """Get embedding dimensions"""
        return self._dimensions

    # --- Embed Jobs API ---

    def create_embed_job(
        self,
        texts: List[str],
        model: Optional[str] = None,
        input_type: str = "search_document",
    ) -> str:
        """Create a Cohere embed job for batch embedding.

        Uploads texts as a dataset, waits for validation, then launches
        an async embed job.

        Args:
            texts: List of text strings to embed.
            model: Embedding model ID. Defaults to the provider's configured model.
            input_type: One of "search_document", "search_query", "classification",
                "clustering". Defaults to "search_document".

        Returns:
            The embed job ID string.

        Raises:
            ValueError: If texts is empty.
            Exception: If dataset validation fails.
        """
        if not texts:
            raise ValueError("texts must be a non-empty list")

        # Write texts to a temporary JSONL file for dataset upload
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            for text in texts:
                json.dump({"text": text}, f)
                f.write("\n")
            tmp_path = f.name

        # Upload dataset
        logger.info("Uploading dataset with %d texts", len(texts))
        with open(tmp_path, "rb") as data_file:
            dataset_response = self.client.datasets.create(
                name="stache-embed-input",
                type="embed-input",
                data=data_file,
            )

        # Wait for dataset validation
        logger.info("Waiting for dataset validation (id=%s)", dataset_response.id)
        self.client.wait(dataset_response)

        # Launch embed job
        job_model = model or self.model
        logger.info(
            "Creating embed job (dataset=%s, model=%s)", dataset_response.id, job_model
        )
        job_response = self.client.embed_jobs.create(
            dataset_id=dataset_response.id,
            model=job_model,
            input_type=input_type,
            embedding_types=["float"],
        )

        logger.info("Embed job created: %s", job_response.job_id)
        return job_response.job_id

    def get_embed_job_status(self, job_id: str) -> Dict[str, str]:
        """Get the status of an embed job.

        Args:
            job_id: The embed job ID.

        Returns:
            Dict with "status" (one of "processing", "complete", "failed",
            "cancelled", "cancelling") and "job_id".
        """
        job = self.client.embed_jobs.get(id=job_id)
        return {"status": job.status, "job_id": job.job_id}

    def download_embed_job(self, job_id: str) -> List[List[float]]:
        """Download embeddings from a completed embed job.

        Args:
            job_id: The embed job ID. Must be in "complete" status.

        Returns:
            List of embedding vectors in the same order as the input texts.

        Raises:
            RuntimeError: If the job is not complete or has no output dataset.
        """
        job = self.client.embed_jobs.get(id=job_id)

        if job.status != "complete":
            raise RuntimeError(
                f"Embed job {job_id} is not complete (status={job.status})"
            )

        if not job.output_dataset_id:
            raise RuntimeError(f"Embed job {job_id} has no output dataset")

        # Fetch output dataset and iterate records via the SDK utility
        output_response = self.client.datasets.get(id=job.output_dataset_id)
        dataset = output_response.dataset

        embeddings: List[List[float]] = []
        for record in cohere.utils.dataset_generator(dataset):
            # Output records contain embeddings keyed by type; we requested "float"
            record_embeddings = record.get("embeddings")
            if record_embeddings and isinstance(record_embeddings, dict):
                floats = record_embeddings.get("float")
                if floats is not None:
                    embeddings.append(floats)
                    continue
            # Fallback: embedding may be at top level (older SDK versions)
            embedding = record.get("embedding")
            if embedding is not None:
                embeddings.append(embedding)
            else:
                raise RuntimeError(
                    f"Could not extract embedding from record: {list(record.keys())}"
                )

        return embeddings

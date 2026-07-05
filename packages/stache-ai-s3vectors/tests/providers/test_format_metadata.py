"""Regression: S3 Vectors rejects empty arrays in metadata.

Job e1ba9c2a failed with:
    PutVectors ... "Empty arrays are not allowed in metadata"
because hierarchical chunking attached `headings: []` to chunks with no
structure. `_format_metadata` must drop empty-list values so a single bad
field doesn't fail the whole PutVectors batch.
"""
import pytest
from unittest.mock import MagicMock, patch

from stache_ai.config import Settings


@pytest.fixture
def provider():
    settings = Settings(
        vectordb_provider="s3vectors",
        s3vectors_bucket="test-bucket",
        s3vectors_index="test-index",
        aws_region="us-east-1",
        embedding_dimension=1024,
    )
    with patch("boto3.client") as mock_client:
        client = MagicMock()
        client.get_vector_bucket.return_value = {}
        client.get_index.return_value = {}
        mock_client.return_value = client
        from stache_ai_s3vectors.provider import S3VectorsProvider
        yield S3VectorsProvider(settings)


def test_empty_list_is_dropped(provider):
    out = provider._format_metadata(
        {"headings": [], "doc_item_labels": [], "strategy": "hierarchical"}
    )
    assert "headings" not in out
    assert "doc_item_labels" not in out
    assert out["strategy"] == "hierarchical"


def test_non_empty_list_passes_through(provider):
    out = provider._format_metadata({"headings": ["Intro", "Background"]})
    assert out["headings"] == ["Intro", "Background"]


def test_none_dropped_primitives_kept(provider):
    out = provider._format_metadata({"a": None, "b": "x", "c": 3, "d": True})
    assert "a" not in out
    assert out == {"b": "x", "c": 3, "d": True}

"""Tests for S3 Vectors status filtering functionality"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from botocore.exceptions import ClientError

from stache_ai_s3vectors.provider import S3VectorsProvider


@pytest.fixture
def mock_settings():
    """Create mock settings object"""
    settings = Mock()
    settings.s3vectors_bucket = "test-bucket"
    settings.s3vectors_index = "test-index"
    settings.aws_region = "us-east-1"
    settings.embedding_dimension = 1024
    return settings


@pytest.fixture
def mock_s3vectors_provider(mock_settings):
    """Create S3 Vectors provider with mocked boto3"""
    with patch('stache_ai_s3vectors.provider.boto3') as mock_boto3:
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        # Mock get_vector_bucket response
        mock_client.get_vector_bucket.return_value = {'vectorBucketName': 'test-bucket'}

        # Mock get_index response
        mock_client.get_index.return_value = {
            'indexName': 'test-index',
            'dimension': 1024,
            'distanceMetric': 'COSINE'
        }

        provider = S3VectorsProvider(mock_settings)
        provider.client = mock_client

        return provider, mock_client


class TestInsertWithStatusField:
    """Test that insert sets status=active on vectors"""

    def test_insert_sets_status_active(self, mock_s3vectors_provider):
        """Test that insert automatically sets status=active"""
        provider, mock_client = mock_s3vectors_provider
        mock_client.put_vectors.return_value = {}

        vectors = [[0.1, 0.2], [0.3, 0.4]]
        texts = ["text1", "text2"]
        metadatas = [{"field1": "value1"}, {"field2": "value2"}]

        ids = provider.insert(vectors, texts, metadatas, namespace="docs")

        assert len(ids) == 2
        mock_client.put_vectors.assert_called_once()

        # Verify status was set
        call_args = mock_client.put_vectors.call_args[1]
        vectors_list = call_args['vectors']
        assert len(vectors_list) == 2
        for vector in vectors_list:
            metadata = vector['metadata']
            assert metadata['status'] == 'active'

    def test_insert_respects_existing_status(self, mock_s3vectors_provider):
        """Test that insert preserves explicitly set status"""
        provider, mock_client = mock_s3vectors_provider
        mock_client.put_vectors.return_value = {}

        vectors = [[0.1, 0.2]]
        texts = ["text1"]
        metadatas = [{"status": "archived"}]

        ids = provider.insert(vectors, texts, metadatas, namespace="docs")

        call_args = mock_client.put_vectors.call_args[1]
        vectors_list = call_args['vectors']
        assert vectors_list[0]['metadata']['status'] == 'archived'

    def test_insert_handles_empty_metadata(self, mock_s3vectors_provider):
        """Test insert with empty metadata list"""
        provider, mock_client = mock_s3vectors_provider
        mock_client.put_vectors.return_value = {}

        vectors = [[0.1, 0.2], [0.3, 0.4]]
        texts = ["text1", "text2"]

        ids = provider.insert(vectors, texts, namespace="docs")

        call_args = mock_client.put_vectors.call_args[1]
        vectors_list = call_args['vectors']
        assert len(vectors_list) == 2
        # All should have status=active even though no metadata provided
        for vector in vectors_list:
            assert vector['metadata']['status'] == 'active'

    def test_insert_batch_processing(self, mock_s3vectors_provider):
        """Test that large inserts are batched and all set status"""
        provider, mock_client = mock_s3vectors_provider
        mock_client.put_vectors.return_value = {}

        # Create 750 vectors (will need 2 batches of 500)
        vectors = [[float(i) / 1000] for i in range(750)]
        texts = [f"text{i}" for i in range(750)]
        metadatas = [{} for _ in range(750)]

        ids = provider.insert(vectors, texts, metadatas, namespace="docs")

        assert len(ids) == 750

        # Should call put_vectors twice (batch size 500)
        assert mock_client.put_vectors.call_count == 2

        # Check first batch
        first_call = mock_client.put_vectors.call_args_list[0][1]
        assert len(first_call['vectors']) == 500
        for vector in first_call['vectors']:
            assert vector['metadata']['status'] == 'active'

        # Check second batch
        second_call = mock_client.put_vectors.call_args_list[1][1]
        assert len(second_call['vectors']) == 250
        for vector in second_call['vectors']:
            assert vector['metadata']['status'] == 'active'


class TestSearchStatusFiltering:
    """Test that search automatically filters out soft-deleted vectors"""

    def test_search_includes_active_vectors(self, mock_s3vectors_provider):
        """Test that search returns active vectors"""
        provider, mock_client = mock_s3vectors_provider

        mock_client.query_vectors.return_value = {
            'vectors': [
                {
                    'key': 'id1',
                    'distance': 0.1,
                    'metadata': {
                        'text': 'active vector',
                        'namespace': 'docs',
                        'status': 'active'
                    }
                }
            ]
        }

        results = provider.search(
            query_vector=[0.1, 0.2],
            top_k=5,
            namespace="docs"
        )

        assert len(results) == 1
        assert results[0]['id'] == 'id1'
        assert results[0]['text'] == 'active vector'

    def test_search_excludes_deleting_vectors(self, mock_s3vectors_provider):
        """Test that search applies status filter to exclude deleting vectors"""
        provider, mock_client = mock_s3vectors_provider

        # Mock query returns only active vectors (S3 Vectors filters server-side)
        mock_client.query_vectors.return_value = {
            'vectors': [
                {
                    'key': 'id1',
                    'distance': 0.1,
                    'metadata': {
                        'text': 'active vector',
                        'namespace': 'docs',
                        'status': 'active'
                    }
                }
            ]
        }

        results = provider.search(
            query_vector=[0.1, 0.2],
            top_k=5,
            namespace="docs"
        )

        # Verify status filter was applied to the query
        call_args = mock_client.query_vectors.call_args[1]
        assert 'filter' in call_args
        filter_dict = call_args['filter']
        # Should have status filter that excludes deleting
        assert '$or' in filter_dict or '$and' in filter_dict

        assert len(results) == 1
        assert results[0]['id'] == 'id1'

    def test_search_includes_legacy_vectors_without_status(self, mock_s3vectors_provider):
        """Test that search includes vectors without status field (legacy support)"""
        provider, mock_client = mock_s3vectors_provider

        mock_client.query_vectors.return_value = {
            'vectors': [
                {
                    'key': 'id1',
                    'distance': 0.1,
                    'metadata': {
                        'text': 'legacy vector',
                        'namespace': 'docs'
                        # No status field
                    }
                }
            ]
        }

        results = provider.search(
            query_vector=[0.1, 0.2],
            top_k=5,
            namespace="docs"
        )

        assert len(results) == 1
        assert results[0]['id'] == 'id1'

    def test_search_applies_status_filter_with_other_filters(self, mock_s3vectors_provider):
        """Test that status filter combines correctly with user filters"""
        provider, mock_client = mock_s3vectors_provider

        mock_client.query_vectors.return_value = {
            'vectors': [
                {
                    'key': 'id1',
                    'distance': 0.1,
                    'metadata': {
                        'text': 'active vector',
                        'namespace': 'docs',
                        'status': 'active',
                        'category': 'important'
                    }
                }
            ]
        }

        results = provider.search(
            query_vector=[0.1, 0.2],
            top_k=5,
            namespace="docs",
            filter={'category': 'important'}
        )

        assert len(results) == 1

        # Verify filter was passed correctly
        call_args = mock_client.query_vectors.call_args[1]
        assert 'filter' in call_args
        filter_dict = call_args['filter']

        # Should have status filter combined with custom filter
        assert '$and' in filter_dict or '$or' in filter_dict

    def test_search_without_custom_filter(self, mock_s3vectors_provider):
        """Test search with only status filtering (no user filter)"""
        provider, mock_client = mock_s3vectors_provider

        mock_client.query_vectors.return_value = {
            'vectors': []
        }

        provider.search(
            query_vector=[0.1, 0.2],
            top_k=5,
            namespace="docs",
            filter=None
        )

        call_args = mock_client.query_vectors.call_args[1]
        assert 'filter' in call_args
        filter_dict = call_args['filter']

        # Should have status filter with $or conditions
        # Structure can be: {'$or': [...]}, {'$and': [{'$or': [...]}]}, etc.
        def has_status_filter(f):
            if '$or' in f:
                return any('status' in c for c in f['$or'])
            if '$and' in f:
                return any(has_status_filter(c) if isinstance(c, dict) else False for c in f['$and'])
            return False

        assert has_status_filter(filter_dict)


class TestUpdateStatus:
    """Test batch status updates for soft delete"""

    def test_update_status_single_vector(self, mock_s3vectors_provider):
        """Test updating status for a single vector"""
        provider, mock_client = mock_s3vectors_provider

        # Mock get_vectors to return existing vector
        mock_client.get_vectors.return_value = {
            'vectors': [
                {
                    'key': 'id1',
                    'data': {'float32': [0.1, 0.2]},
                    'metadata': {
                        'text': 'vector text',
                        'namespace': 'docs',
                        'status': 'active'
                    }
                }
            ]
        }

        mock_client.put_vectors.return_value = {}

        updated = provider.update_status(['id1'], 'docs', 'deleting')

        assert updated == 1
        mock_client.put_vectors.assert_called_once()

        # Verify status was updated
        call_args = mock_client.put_vectors.call_args[1]
        vector = call_args['vectors'][0]
        assert vector['metadata']['status'] == 'deleting'

    def test_update_status_multiple_vectors(self, mock_s3vectors_provider):
        """Test updating status for multiple vectors (batched)"""
        provider, mock_client = mock_s3vectors_provider

        # Mock get_vectors returns all requested vectors in batch
        mock_client.get_vectors.return_value = {
            'vectors': [
                {
                    'key': 'id1',
                    'data': {'float32': [0.1, 0.2]},
                    'metadata': {'text': 'text_id1', 'namespace': 'docs', 'status': 'active'}
                },
                {
                    'key': 'id2',
                    'data': {'float32': [0.2, 0.3]},
                    'metadata': {'text': 'text_id2', 'namespace': 'docs', 'status': 'active'}
                },
                {
                    'key': 'id3',
                    'data': {'float32': [0.3, 0.4]},
                    'metadata': {'text': 'text_id3', 'namespace': 'docs', 'status': 'active'}
                }
            ]
        }
        mock_client.put_vectors.return_value = {}

        updated = provider.update_status(['id1', 'id2', 'id3'], 'docs', 'deleting')

        assert updated == 3
        # Batched update: should be 1 GET + 1 PUT call (all in one batch)
        mock_client.get_vectors.assert_called_once()
        mock_client.put_vectors.assert_called_once()

        # Verify all vectors updated to deleting status
        call_args = mock_client.put_vectors.call_args[1]
        updated_vectors = call_args['vectors']
        assert len(updated_vectors) == 3
        for vector in updated_vectors:
            assert vector['metadata']['status'] == 'deleting'

    def test_update_status_large_batch(self, mock_s3vectors_provider):
        """Test updating status for >500 vectors (multiple batches)"""
        provider, mock_client = mock_s3vectors_provider

        # Create 750 vector IDs (will need 2 batches: 500 + 250)
        vector_ids = [f'id{i}' for i in range(750)]

        # Mock get_vectors to return vectors for each batch
        def get_vectors_side_effect(**kwargs):
            requested_keys = kwargs['keys']
            return {
                'vectors': [
                    {
                        'key': key,
                        'data': {'float32': [0.1, 0.2]},
                        'metadata': {'text': f'text_{key}', 'namespace': 'docs', 'status': 'active'}
                    }
                    for key in requested_keys
                ]
            }

        mock_client.get_vectors.side_effect = get_vectors_side_effect
        mock_client.put_vectors.return_value = {}

        updated = provider.update_status(vector_ids, 'docs', 'deleting')

        assert updated == 750
        # Should make 2 GET calls (500 + 250) and 2 PUT calls (500 + 250)
        assert mock_client.get_vectors.call_count == 2
        assert mock_client.put_vectors.call_count == 2

        # Verify first batch had 500 vectors
        first_get_call = mock_client.get_vectors.call_args_list[0][1]
        assert len(first_get_call['keys']) == 500

        # Verify second batch had 250 vectors
        second_get_call = mock_client.get_vectors.call_args_list[1][1]
        assert len(second_get_call['keys']) == 250

        # Verify status updated in both batches
        first_put_call = mock_client.put_vectors.call_args_list[0][1]
        assert len(first_put_call['vectors']) == 500
        assert all(v['metadata']['status'] == 'deleting' for v in first_put_call['vectors'])

        second_put_call = mock_client.put_vectors.call_args_list[1][1]
        assert len(second_put_call['vectors']) == 250
        assert all(v['metadata']['status'] == 'deleting' for v in second_put_call['vectors'])

    def test_update_status_vector_not_found(self, mock_s3vectors_provider):
        """Test update when vector is not found"""
        provider, mock_client = mock_s3vectors_provider

        mock_client.get_vectors.return_value = {'vectors': []}

        updated = provider.update_status(['nonexistent'], 'docs', 'deleting')

        assert updated == 0

    def test_update_status_preserves_metadata(self, mock_s3vectors_provider):
        """Test that update_status preserves other metadata fields"""
        provider, mock_client = mock_s3vectors_provider

        existing_metadata = {
            'text': 'important content',
            'namespace': 'docs',
            'category': 'urgent',
            'priority': 'high',
            'status': 'active'
        }

        mock_client.get_vectors.return_value = {
            'vectors': [
                {
                    'key': 'id1',
                    'data': {'float32': [0.1, 0.2]},
                    'metadata': existing_metadata
                }
            ]
        }

        mock_client.put_vectors.return_value = {}

        provider.update_status(['id1'], 'docs', 'deleting')

        call_args = mock_client.put_vectors.call_args[1]
        updated_metadata = call_args['vectors'][0]['metadata']

        # Status should change but other fields preserved
        assert updated_metadata['status'] == 'deleting'
        assert updated_metadata['category'] == 'urgent'
        assert updated_metadata['priority'] == 'high'
        assert updated_metadata['text'] == 'important content'

    def test_update_status_handles_errors_gracefully(self, mock_s3vectors_provider):
        """Test that update_status handles batch errors gracefully"""
        provider, mock_client = mock_s3vectors_provider

        # Create 750 IDs to test error handling across batches
        # First batch succeeds, second batch fails
        vector_ids = [f'id{i}' for i in range(750)]

        def get_vectors_side_effect(**kwargs):
            requested_keys = kwargs['keys']
            # First batch (500 vectors) succeeds
            if len(requested_keys) == 500:
                return {
                    'vectors': [
                        {'key': key, 'data': {'float32': [0.1]}, 'metadata': {'status': 'active'}}
                        for key in requested_keys
                    ]
                }
            # Second batch (250 vectors) fails
            else:
                raise Exception("Network error")

        mock_client.get_vectors.side_effect = get_vectors_side_effect
        mock_client.put_vectors.return_value = {}

        updated = provider.update_status(vector_ids, 'docs', 'deleting')

        # Should have updated first batch (500) successfully, second batch (250) failed
        assert updated == 500


class TestStatusFilterIntegration:
    """Integration tests for status filtering with other operations"""

    def test_search_after_update_status(self, mock_s3vectors_provider):
        """Test search applies status filter after update"""
        provider, mock_client = mock_s3vectors_provider

        # Scenario: insert vectors, mark some as deleting, then search

        # Setup for insert
        mock_client.put_vectors.return_value = {}
        vectors = [[0.1, 0.2], [0.3, 0.4]]
        texts = ["text1", "text2"]
        ids = provider.insert(vectors, texts, namespace="docs")

        # Setup for status update
        mock_client.get_vectors.return_value = {
            'vectors': [
                {
                    'key': ids[0],
                    'data': {'float32': [0.1, 0.2]},
                    'metadata': {'text': 'text1', 'namespace': 'docs', 'status': 'active'}
                }
            ]
        }
        provider.update_status([ids[0]], 'docs', 'deleting')

        # Setup for search - S3 Vectors filters server-side, returns only active
        mock_client.query_vectors.return_value = {
            'vectors': [
                {
                    'key': ids[1],
                    'distance': 0.05,
                    'metadata': {'text': 'text2', 'namespace': 'docs', 'status': 'active'}
                }
            ]
        }

        results = provider.search([0.1, 0.2], top_k=5, namespace="docs")

        # Verify status filter was applied
        call_args = mock_client.query_vectors.call_args[1]
        assert 'filter' in call_args

        # Should only return the active vector
        assert len(results) == 1
        assert results[0]['text'] == 'text2'

    def test_mixed_status_search_results(self, mock_s3vectors_provider):
        """Test search with mix of active, deleting, and legacy vectors"""
        provider, mock_client = mock_s3vectors_provider

        # S3 Vectors filters server-side with status filter
        # Only active and legacy (no status) are returned
        mock_client.query_vectors.return_value = {
            'vectors': [
                {
                    'key': 'id1',
                    'distance': 0.05,
                    'metadata': {'text': 'active1', 'namespace': 'docs', 'status': 'active'}
                },
                {
                    'key': 'id3',
                    'distance': 0.15,
                    'metadata': {'text': 'legacy', 'namespace': 'docs'}  # No status
                },
                {
                    'key': 'id4',
                    'distance': 0.2,
                    'metadata': {'text': 'active2', 'namespace': 'docs', 'status': 'active'}
                }
            ]
        }

        results = provider.search([0.1, 0.2], top_k=10, namespace="docs")

        # Verify status filter was applied
        call_args = mock_client.query_vectors.call_args[1]
        assert 'filter' in call_args

        # Should include: active1, legacy, active2 (deleting and purged filtered by server)
        result_ids = {r['id'] for r in results}
        assert 'id1' in result_ids  # active
        assert 'id3' in result_ids  # legacy (included)
        assert 'id4' in result_ids  # active


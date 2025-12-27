"""AWS S3 Vectors provider for serverless vector storage"""

import json
import logging
import time
from typing import List, Dict, Any, Optional, Union
import uuid

import boto3
from botocore.exceptions import ClientError

from stache_ai.providers.base import VectorDBProvider
from stache_ai.config import Settings

logger = logging.getLogger(__name__)


class S3VectorsProvider(VectorDBProvider):
    """AWS S3 Vectors database provider for Lambda-native deployments

    Required IAM permissions:
    - s3vectors:GetVectorBucket
    - s3vectors:GetIndex
    - s3vectors:PutVectors
    - s3vectors:QueryVectors
    - s3vectors:GetVectors (if using metadata filtering or returnMetadata)
    - s3vectors:DeleteVectors
    - s3vectors:ListVectors (for delete_by_metadata operation)
    """

    def __init__(self, settings: Settings, index_name: Optional[str] = None):
        self.settings = settings
        self.client = boto3.client(
            's3vectors',
            region_name=settings.aws_region
        )
        self.bucket_name = settings.s3vectors_bucket
        self.index_name = index_name or settings.s3vectors_index
        self.dimensions = settings.embedding_dimension

        # Validate infrastructure exists (should be pre-provisioned via Terraform/CDK)
        self._validate_infrastructure()

    def _validate_infrastructure(self):
        """Validate that vector bucket and index exist (must be pre-provisioned)"""
        if not self.bucket_name:
            raise ValueError("S3VECTORS_BUCKET environment variable is required")

        try:
            self.client.get_vector_bucket(vectorBucketName=self.bucket_name)
            logger.info(f"S3 Vectors bucket validated: {self.bucket_name}")
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'ResourceNotFoundException':
                raise ValueError(
                    f"S3 Vectors bucket '{self.bucket_name}' not found. "
                    "Please create it using Terraform/CDK before running the application."
                ) from e
            raise

        try:
            self.client.get_index(
                vectorBucketName=self.bucket_name,
                indexName=self.index_name
            )
            logger.info(f"S3 Vectors index validated: {self.index_name}")
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'ResourceNotFoundException':
                raise ValueError(
                    f"S3 Vectors index '{self.index_name}' not found in bucket '{self.bucket_name}'. "
                    "Please create it using Terraform/CDK before running the application."
                ) from e
            raise

    def _with_retry(self, operation, *args, **kwargs):
        """Execute an S3 Vectors operation with exponential backoff on throttling

        Args:
            operation: Boto3 client method to call
            *args, **kwargs: Arguments to pass to the operation

        Returns:
            Operation result

        Raises:
            ClientError: If the operation fails after retries
        """
        max_retries = 5
        base_delay = 0.5  # Start with 500ms

        for attempt in range(max_retries):
            try:
                return operation(*args, **kwargs)
            except ClientError as e:
                error_code = e.response['Error']['Code']

                # Only retry on throttling errors
                if error_code in ('ThrottlingException', 'TooManyRequestsException'):
                    if attempt < max_retries - 1:
                        # Exponential backoff with jitter
                        delay = base_delay * (2 ** attempt)
                        jitter = delay * 0.1  # 10% jitter
                        sleep_time = delay + (jitter * (0.5 - time.time() % 1))

                        logger.warning(
                            f"S3 Vectors throttled, retrying in {sleep_time:.2f}s "
                            f"(attempt {attempt + 1}/{max_retries})"
                        )
                        time.sleep(sleep_time)
                        continue

                # Re-raise on non-throttling errors or final retry
                raise

    def _validate_metadata(self, text: str, metadata: Dict[str, Any]) -> None:
        """Validate metadata against S3 Vectors limits

        S3 Vectors limitations:
        - Filterable metadata: 2 KB max (excludes 'text' which is non-filterable)
        - Total metadata: 40 KB max
        - Metadata keys: 50 max

        Note: The 'text' field is configured as non-filterable at index creation,
        so it doesn't count toward the 2KB filterable limit.

        Args:
            text: Document text to be stored in metadata (non-filterable)
            metadata: User metadata dictionary (filterable)

        Raises:
            ValueError: If metadata exceeds S3 Vectors limits
        """
        # Count total keys (including 'text' and 'namespace')
        total_keys = len(metadata) + 2
        if total_keys > 50:
            raise ValueError(
                f"Metadata has {total_keys} keys (including 'text' and 'namespace'), "
                f"maximum is 50 per S3 Vectors specification"
            )

        # Build metadata structure to estimate size (simple key-value format)
        # Inline formatting to avoid method ordering issues
        formatted_meta = {}
        for k, v in metadata.items():
            if v is None:
                continue
            elif isinstance(v, (str, int, float, bool)):
                formatted_meta[k] = v
            elif isinstance(v, list):
                formatted_meta[k] = v
            elif isinstance(v, dict):
                formatted_meta[k] = json.dumps(v)
            else:
                formatted_meta[k] = str(v)

        # Check filterable metadata size (excludes 'text' which is non-filterable)
        filterable_dict = {
            'namespace': 'default',  # worst case estimate
            **formatted_meta
        }
        filterable_json = json.dumps(filterable_dict)
        filterable_bytes = len(filterable_json.encode('utf-8'))

        if filterable_bytes > 2048:  # 2 KB
            raise ValueError(
                f"Filterable metadata size is {filterable_bytes} bytes, "
                f"exceeds S3 Vectors limit of 2KB. Reduce metadata fields."
            )

        # Check total metadata limit (40 KB) - includes text
        total_dict = {'text': text, **filterable_dict}
        total_json = json.dumps(total_dict)
        total_bytes = len(total_json.encode('utf-8'))

        if total_bytes > 40960:  # 40 KB
            raise ValueError(
                f"Total metadata size is {total_bytes} bytes, "
                f"exceeds S3 Vectors limit of 40 KB"
            )

    def insert(
        self,
        vectors: List[List[float]],
        texts: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        ids: Optional[List[str]] = None,
        namespace: Optional[str] = None
    ) -> List[str]:
        """Insert vectors into S3 Vectors"""
        if not ids:
            ids = [str(uuid.uuid4()) for _ in vectors]

        if not metadatas:
            metadatas = [{} for _ in vectors]

        # Build vector records
        vector_records = []
        for id_, vector, text, metadata in zip(ids, vectors, texts, metadatas):
            # Validate metadata against S3 Vectors limits
            self._validate_metadata(text, metadata)

            record = {
                'key': id_,
                'data': {
                    'float32': vector
                },
                'metadata': {
                    'text': text,
                    'namespace': namespace or 'default',
                    **self._format_metadata(metadata)
                }
            }
            vector_records.append(record)

        # Insert in batches (S3 Vectors supports up to 500 vectors per PutVectors call)
        batch_size = 500
        for i in range(0, len(vector_records), batch_size):
            batch = vector_records[i:i + batch_size]
            self._with_retry(
                self.client.put_vectors,
                vectorBucketName=self.bucket_name,
                indexName=self.index_name,
                vectors=batch
            )

        logger.info(f"Inserted {len(ids)} vectors into S3 Vectors")
        return ids

    def search(
        self,
        query_vector: List[float],
        top_k: int = 5,
        filter: Optional[Dict[str, Any]] = None,
        namespace: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Search for similar vectors in S3 Vectors

        Supports namespace wildcards:
        - "books/*" matches "books/fiction", "books/nonfiction", etc.
        - "books" matches exactly "books" and sub-namespaces by default
        """
        # S3 Vectors has a hard limit of 100 for topK
        if top_k > 100:
            logger.warning(f"top_k={top_k} exceeds S3 Vectors limit of 100, clamping to 100")
            top_k = 100

        # Build filter dict (MongoDB-style syntax)
        query_filter = {}
        namespace_prefix = None
        requires_post_filtering = False

        if namespace:
            if namespace.startswith("exact:"):
                # Exact namespace match - use native filter
                query_filter['namespace'] = namespace[6:]
            elif namespace.endswith("/*"):
                # Wildcard prefix match - requires post-filtering
                # S3 Vectors doesn't support prefix/startswith operators
                namespace_prefix = namespace[:-2]
                requires_post_filtering = True
            else:
                # Default behavior: exact match for this namespace
                query_filter['namespace'] = namespace

        # Add custom filters (merge with namespace filter)
        if filter:
            query_filter.update(filter)

        # Only increase limit if we need post-filtering for wildcard prefixes
        search_limit = top_k * 3 if requires_post_filtering else top_k

        # Execute query
        query_params = {
            'vectorBucketName': self.bucket_name,
            'indexName': self.index_name,
            'queryVector': {'float32': query_vector},
            'topK': search_limit,
            'returnMetadata': True,
            'returnDistance': True
        }

        if query_filter:
            query_params['filter'] = query_filter

        response = self._with_retry(self.client.query_vectors, **query_params)

        results = []
        for match in response.get('vectors', []):
            metadata = match.get('metadata', {})
            ns = self._extract_string_value(metadata.get('namespace'))

            # Post-filter for namespace prefix (only for wildcard patterns)
            if requires_post_filtering and namespace_prefix:
                if not (ns == namespace_prefix or ns.startswith(namespace_prefix + "/")):
                    continue

            # Skip document summaries
            doc_type = self._extract_string_value(metadata.get('_type'))
            if doc_type == 'document_summary':
                continue

            # S3 Vectors returns 'distance' (lower is better for cosine)
            # Convert to similarity score (higher is better) for consistency
            distance = match.get('distance', 0.0)
            # For cosine distance: similarity = 1 - distance
            score = 1.0 - distance if distance is not None else 0.0

            # Build result
            text_content = self._extract_string_value(metadata.get('text'))
            result = {
                'id': match.get('key'),
                'score': score,
                'text': text_content,
                'content': text_content,  # Alias for LLM providers expecting 'content'
                'namespace': ns,
                'metadata': {
                    k: self._extract_value(v)
                    for k, v in metadata.items()
                    if k not in ('text', 'namespace', '_type')
                }
            }
            results.append(result)

            if len(results) >= top_k:
                break

        return results

    def _extract_string_value(self, value: Any) -> str:
        """Extract string value from S3 Vectors metadata"""
        if value is None:
            return ''
        return str(value)

    def _extract_value(self, value: Any) -> Union[str, float, bool, list, None]:
        """Extract value from S3 Vectors metadata

        Args:
            value: S3 Vectors metadata value (simple type)

        Returns:
            The value as-is (string, number, boolean, list, or None)
        """
        return value

    def _format_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Format metadata dict for S3 Vectors API

        S3 Vectors accepts simple key-value pairs with:
        - strings
        - numbers
        - booleans
        - arrays (of strings)

        Args:
            metadata: Raw metadata dictionary

        Returns:
            Formatted metadata dictionary for S3 Vectors
        """
        formatted = {}
        for k, v in metadata.items():
            if v is None:
                # Skip None values - S3 Vectors doesn't support null
                continue
            elif isinstance(v, (str, int, float, bool)):
                # Primitives pass through directly
                formatted[k] = v
            elif isinstance(v, list):
                # S3 Vectors supports arrays - convert items to strings if needed
                if all(isinstance(item, (str, int, float, bool)) for item in v):
                    formatted[k] = v
                else:
                    # Convert complex items to strings
                    formatted[k] = [str(item) if not isinstance(item, (str, int, float, bool)) else item for item in v]
            elif isinstance(v, dict):
                # Flatten nested dicts by JSON-encoding them
                formatted[k] = json.dumps(v)
            else:
                # Fallback: convert to string
                formatted[k] = str(v)
        return formatted

    def delete(self, ids: List[str], namespace: Optional[str] = None) -> bool:
        """Delete vectors by IDs"""
        if not ids:
            return True

        try:
            # S3 Vectors supports up to 500 vectors per DeleteVectors call
            batch_size = 500
            for i in range(0, len(ids), batch_size):
                batch = ids[i:i + batch_size]
                self._with_retry(
                    self.client.delete_vectors,
                    vectorBucketName=self.bucket_name,
                    indexName=self.index_name,
                    keys=batch
                )
            logger.info(f"Deleted {len(ids)} vectors from S3 Vectors")
            return True
        except ClientError as e:
            logger.error(f"Failed to delete vectors: {e}")
            return False

    def search_summaries(
        self,
        query_vector: List[float],
        top_k: int = 10,
        namespace: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Search document summaries for document discovery

        Unlike search() which excludes summaries, this ONLY searches
        document summaries (_type=document_summary).
        """
        # S3 Vectors has a hard limit of 100 for topK
        if top_k > 100:
            top_k = 100

        # Build filter for document summaries
        query_filter = {"_type": "document_summary"}

        namespace_prefix = None
        requires_post_filtering = False

        if namespace:
            if namespace.endswith("/*"):
                namespace_prefix = namespace[:-2]
                requires_post_filtering = True
            else:
                query_filter['namespace'] = namespace

        search_limit = top_k * 3 if requires_post_filtering else top_k

        query_params = {
            'vectorBucketName': self.bucket_name,
            'indexName': self.index_name,
            'queryVector': {'float32': query_vector},
            'topK': search_limit,
            'returnMetadata': True,
            'returnDistance': True,
            'filter': query_filter
        }

        response = self._with_retry(self.client.query_vectors, **query_params)

        results = []
        for match in response.get('vectors', []):
            metadata = match.get('metadata', {})
            ns = self._extract_string_value(metadata.get('namespace'))

            # Post-filter for namespace wildcard
            if requires_post_filtering and namespace_prefix:
                if not (ns == namespace_prefix or ns.startswith(namespace_prefix + "/")):
                    continue

            distance = match.get('distance', 0.0)
            score = 1.0 - distance if distance is not None else 0.0

            text_content = self._extract_string_value(metadata.get('text'))
            result = {
                'id': match.get('key'),
                'score': score,
                'text': text_content,
                'content': text_content,  # Alias for LLM providers expecting 'content'
                'namespace': ns,
                'metadata': {
                    k: self._extract_value(v)
                    for k, v in metadata.items()
                    if k != 'text'
                }
            }
            results.append(result)

            if len(results) >= top_k:
                break

        return results

    def delete_by_metadata(
        self,
        field: str,
        value: str,
        namespace: Optional[str] = None
    ) -> Dict[str, Any]:
        """Delete vectors by metadata field value

        Note: S3 Vectors list_vectors API does NOT support metadata filtering,
        so we must list all vectors and filter client-side. For large datasets,
        this may be slow.
        """
        # Build filter dict for client-side matching
        query_filter = {field: value}

        if namespace:
            query_filter['namespace'] = namespace

        # Paginate through all vectors and filter client-side
        ids_to_delete = []
        paginator = self.client.get_paginator('list_vectors')

        for page in paginator.paginate(
            vectorBucketName=self.bucket_name,
            indexName=self.index_name,
            returnMetadata=True  # Need metadata to filter client-side
        ):
            for vector in page.get('vectors', []):
                metadata = vector.get('metadata', {})
                if self._matches_filter(metadata, query_filter):
                    ids_to_delete.append(vector.get('key'))

        if not ids_to_delete:
            return {'deleted': 0, 'ids': []}

        # Delete in batches (S3 Vectors supports up to 500 vectors per DeleteVectors call)
        batch_size = 500
        for i in range(0, len(ids_to_delete), batch_size):
            batch = ids_to_delete[i:i + batch_size]
            self._with_retry(
                self.client.delete_vectors,
                vectorBucketName=self.bucket_name,
                indexName=self.index_name,
                keys=batch
            )

        logger.info(f"Deleted {len(ids_to_delete)} vectors by {field}={value}")
        return {'deleted': len(ids_to_delete), 'ids': ids_to_delete}

    def get_collection_info(self) -> Dict[str, Any]:
        """Get information about the S3 Vectors index"""
        try:
            index_info = self.client.get_index(
                vectorBucketName=self.bucket_name,
                indexName=self.index_name
            )
            return {
                'name': self.index_name,
                'bucket': self.bucket_name,
                'dimension': index_info.get('dimension'),
                'distanceMetric': index_info.get('distanceMetric'),
                'status': index_info.get('status')
            }
        except ClientError as e:
            logger.error(f"Failed to get index info: {e}")
            return {
                'name': self.index_name,
                'bucket': self.bucket_name,
                'error': str(e)
            }

    def count_by_filter(self, filter: Dict[str, Any]) -> int:
        """Count vectors matching a filter using list_vectors with client-side filtering

        Note: S3 Vectors list_vectors API does NOT support metadata filtering,
        so we must list all vectors and filter client-side. For large datasets,
        this may be slow.

        Args:
            filter: Dictionary of field:value pairs to match (e.g., {"namespace": "mba"})

        Returns:
            Count of matching vectors
        """
        try:
            count = 0
            paginator = self.client.get_paginator('list_vectors')

            for page in paginator.paginate(
                vectorBucketName=self.bucket_name,
                indexName=self.index_name,
                returnMetadata=True  # Need metadata to filter
            ):
                for vector in page.get('vectors', []):
                    metadata = vector.get('metadata', {})
                    # Client-side filter matching
                    if self._matches_filter(metadata, filter):
                        count += 1

            return count
        except ClientError as e:
            logger.error(f"Failed to count vectors with filter {filter}: {e}")
            return 0

    def _matches_filter(self, metadata: Dict[str, Any], filter: Dict[str, Any]) -> bool:
        """Check if metadata matches all filter conditions

        Args:
            metadata: Vector metadata dictionary
            filter: Filter conditions (all must match)

        Returns:
            True if all filter conditions match
        """
        for key, expected_value in filter.items():
            actual_value = metadata.get(key)
            # Extract string value if needed (S3 Vectors sometimes wraps values)
            actual_str = self._extract_string_value(actual_value)
            expected_str = str(expected_value) if expected_value is not None else ''

            if actual_str != expected_str:
                return False
        return True

    def list_by_filter(
        self,
        filter: Dict[str, Any],
        fields: Optional[List[str]] = None,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """List vectors matching a filter with their metadata

        Note: S3 Vectors list_vectors API does NOT support metadata filtering,
        so we must list all vectors and filter client-side.

        Args:
            filter: Dictionary of field:value pairs to match
            fields: Optional list of metadata fields to return (None = all)
            limit: Maximum number of vectors to return

        Returns:
            List of dictionaries with vector metadata
        """
        try:
            results = []
            paginator = self.client.get_paginator('list_vectors')

            for page in paginator.paginate(
                vectorBucketName=self.bucket_name,
                indexName=self.index_name,
                returnMetadata=True
            ):
                for vector in page.get('vectors', []):
                    metadata = vector.get('metadata', {})

                    # Client-side filter matching
                    if not self._matches_filter(metadata, filter):
                        continue

                    # Extract values from metadata
                    extracted = {k: self._extract_value(v) for k, v in metadata.items()}

                    # Filter to requested fields if specified
                    if fields:
                        extracted = {k: v for k, v in extracted.items() if k in fields}

                    results.append({
                        'key': vector.get('key'),
                        **extracted
                    })

                    if len(results) >= limit:
                        return results

            return results
        except ClientError as e:
            logger.error(f"Failed to list vectors with filter {filter}: {e}")
            return []

    def get_by_ids(
        self,
        ids: List[str],
        fields: Optional[List[str]] = None,
        namespace: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Retrieve vectors by IDs with their metadata

        Args:
            ids: List of vector IDs to retrieve
            fields: Optional list of metadata fields to return (None = all)
            namespace: Optional namespace filter (validation only)

        Returns:
            List of dictionaries with vector metadata and text
        """
        if not ids:
            return []

        # S3 Vectors GetVectors supports up to 100 keys per call
        results = []
        batch_size = 100

        for i in range(0, len(ids), batch_size):
            batch = ids[i:i + batch_size]
            response = self._with_retry(
                self.client.get_vectors,
                vectorBucketName=self.bucket_name,
                indexName=self.index_name,
                keys=batch,
                returnMetadata=True
            )

            for vector in response.get('vectors', []):
                metadata = vector.get('metadata', {})

                # Optional: filter by namespace
                if namespace:
                    vec_namespace = self._extract_string_value(metadata.get('namespace'))
                    if vec_namespace != namespace:
                        continue

                # Extract values
                text_content = self._extract_string_value(metadata.get('text'))
                extracted = {
                    "id": vector.get('key'),
                    "text": text_content,
                    "content": text_content,  # Alias for LLM providers expecting 'content'
                    **{
                        k: self._extract_value(v)
                        for k, v in metadata.items()
                        if k not in ("text", "namespace") and (not fields or k in fields)
                    }
                }
                results.append(extracted)

        return results

    @property
    def capabilities(self) -> set:
        """S3 Vectors has limited capabilities - no metadata scanning or export"""
        return set()  # No advanced capabilities yet

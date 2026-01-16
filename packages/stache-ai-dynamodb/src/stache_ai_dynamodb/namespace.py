"""DynamoDB namespace provider - Serverless namespace registry for AWS Lambda"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from stache_ai.providers.base import NamespaceProvider
from stache_ai.config import Settings
from . import sanitize_for_dynamodb

logger = logging.getLogger(__name__)


class DynamoDBNamespaceProvider(NamespaceProvider):
    """DynamoDB-based namespace registry provider for AWS Lambda deployments

    Required IAM permissions:
    - dynamodb:DescribeTable
    - dynamodb:GetItem
    - dynamodb:PutItem
    - dynamodb:UpdateItem
    - dynamodb:DeleteItem
    - dynamodb:Query (for listing with parent_id-index GSI)
    - dynamodb:Scan (for listing all namespaces)
    """

    def __init__(self, settings: Settings):
        self.dynamodb = boto3.resource('dynamodb', region_name=settings.aws_region)
        self.table_name = settings.dynamodb_namespace_table
        self.table = self.dynamodb.Table(self.table_name)
        self._validate_table()
        logger.info(f"DynamoDB namespace provider initialized: {self.table_name}")

    def _validate_table(self):
        """Validate that the DynamoDB table exists (must be pre-provisioned)"""
        client = boto3.client('dynamodb', region_name=self.dynamodb.meta.client.meta.region_name)

        try:
            response = client.describe_table(TableName=self.table_name)
            status = response['Table']['TableStatus']
            if status != 'ACTIVE':
                raise ValueError(
                    f"DynamoDB table '{self.table_name}' exists but is not ACTIVE (status: {status})"
                )
            logger.info(f"DynamoDB table validated: {self.table_name}")
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceNotFoundException':
                raise ValueError(
                    f"DynamoDB table '{self.table_name}' not found. "
                    "Please create it using Terraform/CDK with the following schema:\n"
                    "  - Primary key: id (String)\n"
                    "  - GSI: parent_id-index (parent_id -> id)\n"
                    "  - BillingMode: PAY_PER_REQUEST"
                ) from e
            raise

    def _to_dynamodb_item(
        self,
        id: str,
        name: str,
        description: str,
        parent_id: Optional[str],
        metadata: Optional[Dict[str, Any]],
        filter_keys: Optional[List[str]],
        created_at: str,
        updated_at: str
    ) -> Dict[str, Any]:
        """Convert namespace data to DynamoDB item format"""
        item = {
            'id': id,
            'name': name,
            'description': description,
            'metadata': json.dumps(metadata or {}),
            'filter_keys': json.dumps(filter_keys or []),
            'created_at': created_at,
            'updated_at': updated_at
        }
        # DynamoDB doesn't support None in GSI, use special value for root namespaces
        item['parent_id'] = parent_id if parent_id else '__ROOT__'
        return item

    def _from_dynamodb_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Convert DynamoDB item to namespace dict"""
        parent_id = item.get('parent_id')
        if parent_id == '__ROOT__':
            parent_id = None

        return {
            'id': item['id'],
            'name': item['name'],
            'description': item.get('description', ''),
            'parent_id': parent_id,
            'metadata': json.loads(item.get('metadata', '{}')),
            'filter_keys': json.loads(item.get('filter_keys', '[]')),
            'created_at': item.get('created_at'),
            'updated_at': item.get('updated_at')
        }

    def create(
        self,
        id: str,
        name: str,
        description: str = "",
        parent_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        filter_keys: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Create a new namespace"""
        # Validate parent exists if specified
        if parent_id and not self.exists(parent_id):
            raise ValueError(f"Parent namespace not found: {parent_id}")

        # Check if already exists
        if self.exists(id):
            raise ValueError(f"Namespace already exists: {id}")

        now = datetime.now(timezone.utc).isoformat()
        item = self._to_dynamodb_item(id, name, description, parent_id, metadata, filter_keys, now, now)

        # Sanitize floats to Decimal for DynamoDB compatibility
        self.table.put_item(Item=sanitize_for_dynamodb(item))
        logger.info(f"Created namespace: {id}")

        return self.get(id)

    def get(self, id: str) -> Optional[Dict[str, Any]]:
        """Get a namespace by ID"""
        try:
            response = self.table.get_item(Key={'id': id})
            item = response.get('Item')
            if item:
                return self._from_dynamodb_item(item)
            return None
        except ClientError as e:
            logger.error(f"Error getting namespace {id}: {e}")
            return None

    def list(
        self,
        parent_id: Optional[str] = None,
        include_children: bool = False
    ) -> List[Dict[str, Any]]:
        """List namespaces, optionally filtered by parent"""
        if include_children and parent_id is None:
            # Get all namespaces
            response = self.table.scan()
            items = response.get('Items', [])
            # Handle pagination
            while 'LastEvaluatedKey' in response:
                response = self.table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
                items.extend(response.get('Items', []))
            # Sort by id for consistent ordering
            items.sort(key=lambda x: x.get('id', ''))
            return [self._from_dynamodb_item(item) for item in items]

        # Query by parent_id using GSI
        parent_key = parent_id if parent_id else '__ROOT__'
        response = self.table.query(
            IndexName='parent_id-index',
            KeyConditionExpression=Key('parent_id').eq(parent_key)
        )
        items = response.get('Items', [])

        # Handle pagination
        while 'LastEvaluatedKey' in response:
            response = self.table.query(
                IndexName='parent_id-index',
                KeyConditionExpression=Key('parent_id').eq(parent_key),
                ExclusiveStartKey=response['LastEvaluatedKey']
            )
            items.extend(response.get('Items', []))

        # Sort by name
        items.sort(key=lambda x: x.get('name', ''))
        return [self._from_dynamodb_item(item) for item in items]

    def update(
        self,
        id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        parent_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        filter_keys: Optional[List[str]] = None
    ) -> Optional[Dict[str, Any]]:
        """Update a namespace"""
        existing = self.get(id)
        if not existing:
            return None

        # Build update expression
        update_parts = []
        expression_values = {}
        expression_names = {}

        if name is not None:
            update_parts.append('#n = :name')
            expression_values[':name'] = name
            expression_names['#n'] = 'name'  # 'name' is a reserved keyword

        if description is not None:
            # 'description' might be reserved in some DynamoDB contexts
            update_parts.append('#desc = :desc')
            expression_values[':desc'] = description
            expression_names['#desc'] = 'description'

        if parent_id is not None:
            # Validate parent exists
            if parent_id and not self.exists(parent_id):
                raise ValueError(f"Parent namespace not found: {parent_id}")
            if parent_id == id:
                raise ValueError("Namespace cannot be its own parent")
            update_parts.append('#parent_id = :parent')
            expression_values[':parent'] = parent_id if parent_id else '__ROOT__'
            expression_names['#parent_id'] = 'parent_id'

        if metadata is not None:
            # Merge with existing metadata
            merged = {**existing['metadata'], **metadata}
            update_parts.append('#metadata = :meta')
            expression_values[':meta'] = json.dumps(merged)
            expression_names['#metadata'] = 'metadata'

        # Handle filter_keys (replace, not merge)
        if filter_keys is not None:
            update_parts.append('#filter_keys = :filter_keys')
            expression_values[':filter_keys'] = json.dumps(filter_keys)
            expression_names['#filter_keys'] = 'filter_keys'

        if not update_parts:
            return existing

        # Always update updated_at
        update_parts.append('#updated_at = :updated')
        expression_values[':updated'] = datetime.now(timezone.utc).isoformat()
        expression_names['#updated_at'] = 'updated_at'

        update_expression = 'SET ' + ', '.join(update_parts)

        update_params = {
            'Key': {'id': id},
            'UpdateExpression': update_expression,
            'ExpressionAttributeValues': expression_values,
            'ExpressionAttributeNames': expression_names  # Always include now
        }

        self.table.update_item(**update_params)
        logger.info(f"Updated namespace: {id}")

        return self.get(id)

    def delete(self, id: str, cascade: bool = False) -> bool:
        """Delete a namespace"""
        if not self.exists(id):
            return False

        # Check for children
        children = self.list(parent_id=id)
        if children and not cascade:
            raise ValueError(
                f"Namespace has {len(children)} children. Use cascade=True to delete."
            )

        # Delete children recursively if cascade
        if cascade:
            for child in children:
                self.delete(child['id'], cascade=True)

        # Delete the namespace
        self.table.delete_item(Key={'id': id})
        logger.info(f"Deleted namespace: {id}")

        return True

    def get_tree(self, root_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get namespace hierarchy as a tree"""
        all_namespaces = self.list(include_children=True)

        # Build lookup dict
        by_id = {ns['id']: {**ns, 'children': []} for ns in all_namespaces}

        # Build tree structure
        roots = []
        for ns in all_namespaces:
            ns_with_children = by_id[ns['id']]
            parent_id = ns['parent_id']

            if parent_id and parent_id in by_id:
                by_id[parent_id]['children'].append(ns_with_children)
            elif parent_id is None:
                roots.append(ns_with_children)

        # If root_id specified, return just that subtree
        if root_id:
            if root_id in by_id:
                return [by_id[root_id]]
            return []

        return roots

    def exists(self, id: str) -> bool:
        """Check if a namespace exists"""
        try:
            response = self.table.get_item(
                Key={'id': id},
                ProjectionExpression='id'
            )
            return 'Item' in response
        except ClientError:
            return False

    def get_ancestors(self, id: str) -> List[Dict[str, Any]]:
        """Get all ancestor namespaces (parent, grandparent, etc.)"""
        ancestors = []
        current = self.get(id)

        while current and current['parent_id']:
            parent = self.get(current['parent_id'])
            if parent:
                ancestors.append(parent)
                current = parent
            else:
                break

        return list(reversed(ancestors))  # Root first

    def get_path(self, id: str) -> str:
        """Get the full path of a namespace (e.g., 'MBA > Finance > Corporate Finance')"""
        ancestors = self.get_ancestors(id)
        current = self.get(id)

        if not current:
            return ""

        names = [a['name'] for a in ancestors] + [current['name']]
        return " > ".join(names)

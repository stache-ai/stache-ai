# stache-ai-dynamodb

DynamoDB providers for [Stache AI](https://github.com/stache-ai/stache-ai) - serverless namespace registry and document index for AWS Lambda deployments.

## Installation

```bash
pip install stache-ai-dynamodb
```

## Providers

This package includes two providers:

| Provider | Type | Description |
|----------|------|-------------|
| `dynamodb` | Namespace | Hierarchical namespace registry with parent-child relationships |
| `dynamodb` | Document Index | Document metadata storage with namespace filtering |

## Configuration

```python
from stache_ai.config import Settings

settings = Settings(
    namespace_provider="dynamodb",
    dynamodb_namespace_table="my-namespaces",  # Required

    # Optional: Document index
    enable_document_index=True,
    document_index_provider="dynamodb",
    dynamodb_document_table="my-documents",
)
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `NAMESPACE_PROVIDER` | Set to `dynamodb` | `none` |
| `DYNAMODB_NAMESPACE_TABLE` | Namespace table name | Required |
| `DOCUMENT_INDEX_PROVIDER` | Set to `dynamodb` | `none` |
| `DYNAMODB_DOCUMENT_TABLE` | Document table name | Required if using document index |
| `AWS_REGION` | AWS region | `us-east-1` |

## Table Schemas

### Namespace Table

Primary key: `id` (String)
GSI: `parent_id-index` on `parent_id` (String)

| Attribute | Type | Description |
|-----------|------|-------------|
| `id` | String | Unique namespace identifier (primary key) |
| `name` | String | Display name |
| `description` | String | Optional description |
| `parent_id` | String | Parent namespace ID (`__ROOT__` for top-level) |
| `metadata` | String | JSON-encoded metadata |
| `filter_keys` | String | JSON-encoded list of filter keys |
| `created_at` | String | ISO 8601 timestamp |
| `updated_at` | String | ISO 8601 timestamp |

### Document Table

Uses single-table design with composite keys:

**Primary Key:**
- `PK` (String): `DOC#{namespace}#{doc_id}`
- `SK` (String): `METADATA`

**Global Secondary Indexes:**
- `GSI1`: Namespace queries
  - `GSI1PK`: `NAMESPACE#{namespace}`
  - `GSI1SK`: `CREATED#{timestamp}`
- `GSI2`: Filename lookups
  - `GSI2PK`: `FILENAME#{namespace}#{filename}`
  - `GSI2SK`: `CREATED#{timestamp}`

| Attribute | Type | Description |
|-----------|------|-------------|
| `PK` | String | Primary key: `DOC#{namespace}#{doc_id}` |
| `SK` | String | Sort key: `METADATA` |
| `GSI1PK` | String | Namespace index: `NAMESPACE#{namespace}` |
| `GSI1SK` | String | Created timestamp: `CREATED#{timestamp}` |
| `GSI2PK` | String | Filename index: `FILENAME#{namespace}#{filename}` |
| `GSI2SK` | String | Created timestamp: `CREATED#{timestamp}` |
| `doc_id` | String | Document ID |
| `namespace` | String | Namespace ID |
| `filename` | String | Original filename |
| `title` | String | Document title |
| `source` | String | Source identifier |
| `content_type` | String | MIME type |
| `chunk_count` | Number | Number of chunks |
| `metadata` | Map | Document metadata |
| `created_at` | String | ISO 8601 timestamp |
| `updated_at` | String | ISO 8601 timestamp |

## Infrastructure Examples

### AWS SAM Template

```yaml
Resources:
  # Namespace registry table
  NamespaceTable:
    Type: AWS::DynamoDB::Table
    Properties:
      TableName: !Sub '${AWS::StackName}-namespaces'
      BillingMode: PAY_PER_REQUEST
      AttributeDefinitions:
        - AttributeName: id
          AttributeType: S
        - AttributeName: parent_id
          AttributeType: S
      KeySchema:
        - AttributeName: id
          KeyType: HASH
      GlobalSecondaryIndexes:
        - IndexName: parent_id-index
          KeySchema:
            - AttributeName: parent_id
              KeyType: HASH
          Projection:
            ProjectionType: ALL

  # Document index table (single-table design)
  DocumentsTable:
    Type: AWS::DynamoDB::Table
    Properties:
      TableName: !Sub '${AWS::StackName}-documents'
      BillingMode: PAY_PER_REQUEST
      AttributeDefinitions:
        - AttributeName: PK
          AttributeType: S
        - AttributeName: SK
          AttributeType: S
        - AttributeName: GSI1PK
          AttributeType: S
        - AttributeName: GSI1SK
          AttributeType: S
        - AttributeName: GSI2PK
          AttributeType: S
        - AttributeName: GSI2SK
          AttributeType: S
      KeySchema:
        - AttributeName: PK
          KeyType: HASH
        - AttributeName: SK
          KeyType: RANGE
      GlobalSecondaryIndexes:
        - IndexName: GSI1
          KeySchema:
            - AttributeName: GSI1PK
              KeyType: HASH
            - AttributeName: GSI1SK
              KeyType: RANGE
          Projection:
            ProjectionType: ALL
        - IndexName: GSI2
          KeySchema:
            - AttributeName: GSI2PK
              KeyType: HASH
            - AttributeName: GSI2SK
              KeyType: RANGE
          Projection:
            ProjectionType: ALL

  # Lambda function with DynamoDB access
  StacheFunction:
    Type: AWS::Serverless::Function
    Properties:
      Environment:
        Variables:
          NAMESPACE_PROVIDER: dynamodb
          DYNAMODB_NAMESPACE_TABLE: !Ref NamespaceTable
          DOCUMENT_INDEX_PROVIDER: dynamodb
          DYNAMODB_DOCUMENT_TABLE: !Ref DocumentsTable
      Policies:
        - DynamoDBCrudPolicy:
            TableName: !Ref NamespaceTable
        - DynamoDBCrudPolicy:
            TableName: !Ref DocumentsTable
```

### Terraform

```hcl
resource "aws_dynamodb_table" "namespaces" {
  name         = "${var.prefix}-namespaces"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"

  attribute {
    name = "id"
    type = "S"
  }

  attribute {
    name = "parent_id"
    type = "S"
  }

  global_secondary_index {
    name            = "parent_id-index"
    hash_key        = "parent_id"
    projection_type = "ALL"
  }
}

resource "aws_dynamodb_table" "documents" {
  name         = "${var.prefix}-documents"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  attribute {
    name = "GSI1PK"
    type = "S"
  }

  attribute {
    name = "GSI1SK"
    type = "S"
  }

  attribute {
    name = "GSI2PK"
    type = "S"
  }

  attribute {
    name = "GSI2SK"
    type = "S"
  }

  global_secondary_index {
    name            = "GSI1"
    hash_key        = "GSI1PK"
    range_key       = "GSI1SK"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "GSI2"
    hash_key        = "GSI2PK"
    range_key       = "GSI2SK"
    projection_type = "ALL"
  }
}
```

### AWS CLI

```bash
# Create namespace table
aws dynamodb create-table \
  --table-name stache-namespaces \
  --attribute-definitions \
    AttributeName=id,AttributeType=S \
    AttributeName=parent_id,AttributeType=S \
  --key-schema AttributeName=id,KeyType=HASH \
  --global-secondary-indexes \
    'IndexName=parent_id-index,KeySchema=[{AttributeName=parent_id,KeyType=HASH}],Projection={ProjectionType=ALL}' \
  --billing-mode PAY_PER_REQUEST

# Create documents table
aws dynamodb create-table \
  --table-name stache-documents \
  --attribute-definitions \
    AttributeName=PK,AttributeType=S \
    AttributeName=SK,AttributeType=S \
    AttributeName=GSI1PK,AttributeType=S \
    AttributeName=GSI1SK,AttributeType=S \
    AttributeName=GSI2PK,AttributeType=S \
    AttributeName=GSI2SK,AttributeType=S \
  --key-schema \
    AttributeName=PK,KeyType=HASH \
    AttributeName=SK,KeyType=RANGE \
  --global-secondary-indexes \
    'IndexName=GSI1,KeySchema=[{AttributeName=GSI1PK,KeyType=HASH},{AttributeName=GSI1SK,KeyType=RANGE}],Projection={ProjectionType=ALL}' \
    'IndexName=GSI2,KeySchema=[{AttributeName=GSI2PK,KeyType=HASH},{AttributeName=GSI2SK,KeyType=RANGE}],Projection={ProjectionType=ALL}' \
  --billing-mode PAY_PER_REQUEST
```

## IAM Permissions

The Lambda function needs these permissions on both tables:

```yaml
- dynamodb:DescribeTable
- dynamodb:GetItem
- dynamodb:PutItem
- dynamodb:UpdateItem
- dynamodb:DeleteItem
- dynamodb:Query
- dynamodb:Scan
```

Or use the SAM `DynamoDBCrudPolicy` as shown above.

## Requirements

- Python >= 3.10
- stache-ai >= 0.1.0
- boto3 >= 1.34.0

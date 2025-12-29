# stache-ai-s3vectors

S3 Vectors provider for [Stache AI](https://github.com/stache-ai/stache-ai) - serverless vector database using Amazon S3 Vectors.

## Installation

```bash
pip install stache-ai-s3vectors
```

## Usage

Install the package and configure the provider in your settings:

```python
from stache_ai.config import Settings

settings = Settings(
    vectordb_provider="s3vectors",
    s3vectors_bucket_name="my-vector-bucket",  # Required
    s3vectors_region="us-east-1",              # Optional, defaults to AWS_REGION
)
```

The provider will be automatically discovered via entry points.

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `VECTORDB_PROVIDER` | Set to `s3vectors` | Required |
| `S3VECTORS_BUCKET_NAME` | S3 Vectors bucket name | Required |
| `S3VECTORS_REGION` | AWS region for S3 Vectors | `us-east-1` |
| `AWS_REGION` | Fallback region | `us-east-1` |

## IAM Permissions

The S3 Vectors provider requires specific IAM permissions. Note that S3 Vectors uses its own service namespace (`s3vectors:`), not the standard S3 namespace.

### Minimum Required Permissions

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3vectors:GetVectorBucket"
      ],
      "Resource": "arn:aws:s3vectors:REGION:ACCOUNT:vector-bucket/BUCKET_NAME"
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3vectors:CreateIndex",
        "s3vectors:GetIndex",
        "s3vectors:ListIndexes",
        "s3vectors:PutVectors",
        "s3vectors:QueryVectors",
        "s3vectors:ListVectors",
        "s3vectors:DeleteVectors",
        "s3vectors:GetVectors"
      ],
      "Resource": "arn:aws:s3vectors:REGION:ACCOUNT:vector-bucket/BUCKET_NAME/index/*"
    }
  ]
}
```

### SAM Template Example

```yaml
Resources:
  S3VectorsBucket:
    Type: AWS::S3Vectors::VectorBucket
    Properties:
      VectorBucketName: !Sub '${AWS::StackName}-vectors'

  StacheFunction:
    Type: AWS::Serverless::Function
    Properties:
      Environment:
        Variables:
          VECTORDB_PROVIDER: s3vectors
          S3VECTORS_BUCKET_NAME: !GetAtt S3VectorsBucket.VectorBucketName
      Policies:
        - Version: '2012-10-17'
          Statement:
            - Effect: Allow
              Action:
                - s3vectors:GetVectorBucket
              Resource:
                - !GetAtt S3VectorsBucket.VectorBucketArn
            - Effect: Allow
              Action:
                - s3vectors:CreateIndex
                - s3vectors:GetIndex
                - s3vectors:ListIndexes
                - s3vectors:PutVectors
                - s3vectors:QueryVectors
                - s3vectors:ListVectors
                - s3vectors:DeleteVectors
                - s3vectors:GetVectors
              Resource:
                - !Sub '${S3VectorsBucket.VectorBucketArn}/index/*'
```

### Terraform Example

```hcl
data "aws_iam_policy_document" "s3vectors" {
  statement {
    effect = "Allow"
    actions = [
      "s3vectors:GetVectorBucket"
    ]
    resources = [
      "arn:aws:s3vectors:${var.region}:${data.aws_caller_identity.current.account_id}:vector-bucket/${var.bucket_name}"
    ]
  }

  statement {
    effect = "Allow"
    actions = [
      "s3vectors:CreateIndex",
      "s3vectors:GetIndex",
      "s3vectors:ListIndexes",
      "s3vectors:PutVectors",
      "s3vectors:QueryVectors",
      "s3vectors:ListVectors",
      "s3vectors:DeleteVectors",
      "s3vectors:GetVectors"
    ]
    resources = [
      "arn:aws:s3vectors:${var.region}:${data.aws_caller_identity.current.account_id}:vector-bucket/${var.bucket_name}/index/*"
    ]
  }
}
```

## Important Notes

### Bucket Name vs ARN

The provider uses the **bucket name** (not the ARN) for API calls, but IAM policies require the full ARN format:

- **Environment variable**: `S3VECTORS_BUCKET_NAME=my-vectors-bucket` (just the name)
- **IAM Resource**: `arn:aws:s3vectors:us-east-1:123456789012:vector-bucket/my-vectors-bucket` (full ARN)

S3 Vectors bucket names are **globally unique** across AWS, so include your account ID or a unique prefix:

```yaml
# SAM template example
VectorBucketName: !Sub '${AWS::StackName}-vectors-${AWS::AccountId}'
```

### Metadata Limits

S3 Vectors has metadata size limits:
- **Filterable metadata**: 2KB limit (used in query filters)
- **Non-filterable metadata**: Part of 40KB total (returned but can't filter)

When creating indexes, specify large fields like `text` as non-filterable:

```bash
aws s3vectors create-index \
  --vector-bucket-name my-bucket \
  --index-name my-index \
  --dimension 1024 \
  --distance-metric cosine \
  --metadata-configuration 'nonFilterableMetadataKeys=["text"]'
```

### list_vectors Limitation

The `list_vectors` API does NOT support metadata filtering - only `query_vectors` supports filtering. For operations that need to filter without a query vector, the provider lists all vectors and filters client-side.

## Requirements

- Python >= 3.10
- stache-ai >= 0.1.0
- boto3 >= 1.34.0

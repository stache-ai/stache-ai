# stache-ai-bedrock

Amazon Bedrock provider for [Stache AI](https://github.com/stache-ai/stache-ai) - LLM and embedding support via AWS Bedrock.

## Installation

```bash
pip install stache-ai-bedrock
```

## Usage

Install the package and configure the provider in your settings:

```python
from stache_ai.config import Settings

settings = Settings(
    llm_provider="bedrock",
    embedding_provider="bedrock",
    bedrock_model_id="anthropic.claude-sonnet-4-20250514-v1:0",  # Optional
    bedrock_embedding_model_id="cohere.embed-english-v3",        # Optional
)
```

The provider will be automatically discovered via entry points.

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `LLM_PROVIDER` | Set to `bedrock` for LLM | - |
| `EMBEDDING_PROVIDER` | Set to `bedrock` for embeddings | - |
| `BEDROCK_MODEL_ID` | LLM model ID | `anthropic.claude-sonnet-4-20250514-v1:0` |
| `BEDROCK_EMBEDDING_MODEL_ID` | Embedding model ID | `cohere.embed-english-v3` |
| `AWS_REGION` | AWS region | `us-east-1` |

## Supported Models

### LLM Models

The provider supports all Bedrock-available models including:

| Provider | Models | Tier |
|----------|--------|------|
| Anthropic | Claude Opus 4, Claude Sonnet 4, Claude Sonnet 3.5 v2, Claude Haiku 3.5 | Premium/Balanced/Fast |
| Amazon | Nova Pro, Nova Lite, Nova Micro, Titan Text | Balanced/Fast |
| Meta | Llama 3.1 405B, Llama 3.2 90B, Llama 3 70B/8B | Premium/Balanced/Fast |
| Mistral | Mistral Large, Mixtral 8x7B, Mistral 7B | Premium/Balanced/Fast |
| Cohere | Command R+, Command R | Premium/Balanced |
| AI21 | Jamba 1.5 Large, Jamba 1.5 Mini | Premium/Balanced |

### Embedding Models

| Model ID | Dimensions | Description |
|----------|------------|-------------|
| `cohere.embed-english-v3` | 1024 | English text (recommended) |
| `cohere.embed-multilingual-v3` | 1024 | Multilingual text |
| `amazon.titan-embed-text-v2:0` | 1024 | Amazon Titan embeddings |

## IAM Permissions

The Bedrock provider requires specific IAM permissions for model invocation.

### Minimum Required Permissions

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
        "bedrock:Converse"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "aws-marketplace:ViewSubscriptions",
        "aws-marketplace:Subscribe"
      ],
      "Resource": "*"
    }
  ]
}
```

### Why `Resource: "*"`?

Bedrock uses **cross-region inference profiles** for some models, which require wildcard resource permissions. Specific model ARNs (e.g., `arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-*`) will fail for cross-region requests.

### SAM Template Example

```yaml
Resources:
  StacheFunction:
    Type: AWS::Serverless::Function
    Properties:
      Environment:
        Variables:
          LLM_PROVIDER: bedrock
          EMBEDDING_PROVIDER: bedrock
          BEDROCK_MODEL_ID: anthropic.claude-sonnet-4-20250514-v1:0
          BEDROCK_EMBEDDING_MODEL_ID: cohere.embed-english-v3
      Policies:
        - Version: '2012-10-17'
          Statement:
            - Effect: Allow
              Action:
                - bedrock:InvokeModel
                - bedrock:InvokeModelWithResponseStream
                - bedrock:Converse
              Resource: '*'
            - Effect: Allow
              Action:
                - aws-marketplace:ViewSubscriptions
                - aws-marketplace:Subscribe
              Resource: '*'
```

### Terraform Example

```hcl
data "aws_iam_policy_document" "bedrock" {
  statement {
    effect = "Allow"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream",
      "bedrock:Converse"
    ]
    resources = ["*"]
  }

  statement {
    effect = "Allow"
    actions = [
      "aws-marketplace:ViewSubscriptions",
      "aws-marketplace:Subscribe"
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "bedrock" {
  name   = "bedrock-access"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.bedrock.json
}
```

## Important Notes

### Model Access

Before using a model, you must **enable access** in the AWS Bedrock console:
1. Go to AWS Console → Bedrock → Model access
2. Request access to the models you want to use
3. Wait for access approval (usually instant for most models)

### Converse API

This provider uses the Bedrock **Converse API** (not the legacy InvokeModel API for chat). This requires the `bedrock:Converse` permission - `bedrock:InvokeModel` alone is not sufficient for LLM chat operations.

### Embeddings

Embeddings use `bedrock:InvokeModel` with the embedding model. The Cohere embed models return 1024-dimensional vectors by default.

## Requirements

- Python >= 3.10
- stache-ai >= 0.1.0
- boto3 >= 1.34.0

# Stache MCP Setup Guide

This guide explains how to expose your Stache instance via MCP (Model Context Protocol) so it can be used with Claude and other MCP-compatible clients.

## Architecture Overview

Stache supports two MCP integration paths:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CLAUDE CLIENTS                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Claude Web ──────────► AgentCore Gateway ──────────► Lambda (direct invoke)│
│  (claude.ai)            (MCP protocol)                                       │
│       │                      │                                               │
│       │              OAuth (code flow)                                       │
│       │                                                                      │
│  Claude Code ─────────► Local MCP Server ───────────► API Gateway ──► Lambda│
│  (CLI/Desktop)          (stdio transport)             (REST + JWT)           │
│                              │                                               │
│                      OAuth (client_credentials)                              │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Path 1: Claude Web (via AgentCore Gateway)**
- AWS Bedrock AgentCore Gateway handles MCP protocol
- Directly invokes Lambda (no API Gateway)
- Uses OAuth code flow with PKCE
- Best for: Claude Web users

**Path 2: Claude Code (via Local MCP Server)**
- Lightweight Python server runs locally
- Communicates with your API Gateway via REST
- Uses OAuth client_credentials flow
- Best for: Claude Code/Desktop, programmatic access

## Prerequisites

Before setting up MCP, you need:

1. **Deployed Stache instance** with:
   - Lambda function running the FastAPI app
   - API Gateway with HTTP endpoints
   - OAuth2/OpenID Connect provider (Cognito recommended)

2. **OAuth Provider** configured with:
   - User Pool/Domain
   - Resource server with scopes (e.g., `stache-mcp/read`, `stache-mcp/write`)
   - App clients for different flows (see below)

3. **MCP Tools** you want to expose:
   - `search` - Semantic search with optional AI synthesis
   - `list_namespaces` - List all namespaces
   - `list_documents` - List documents with pagination
   - `get_document` - Get document metadata by ID
   - `ingest_text` - Add text content to knowledge base

## Option 1: Claude Code (Local MCP Server)

This is the simpler option and works with Claude Desktop and Claude Code CLI.

### Step 1: Configure OAuth

Create an OAuth app client with:
- **Flow**: `client_credentials`
- **Scopes**: Your resource server scopes (e.g., `stache-mcp/read`, `stache-mcp/write`)
- **Grant types**: Client credentials only

Save the client ID and secret.

### Step 2: Update API Gateway Authorizer

Configure your API Gateway JWT authorizer to accept tokens from this client:

```bash
aws apigatewayv2 update-authorizer \
  --api-id YOUR_API_ID \
  --authorizer-id YOUR_AUTHORIZER_ID \
  --jwt-configuration 'Audience=["YOUR_CLIENT_ID"],Issuer=YOUR_ISSUER_URL'
```

Where:
- `YOUR_API_ID` - Your HTTP API Gateway ID
- `YOUR_AUTHORIZER_ID` - Your JWT authorizer ID
- `YOUR_CLIENT_ID` - Client ID from Step 1
- `YOUR_ISSUER_URL` - Your OAuth provider's issuer URL (e.g., `https://cognito-idp.REGION.amazonaws.com/YOUR_POOL_ID`)

### Step 3: Install Local MCP Server

```bash
cd stache/tools/mcp-server
./install.sh
```

The install script will:
1. Create a Python virtual environment
2. Install dependencies (`mcp`, `httpx`)
3. Update your `~/.claude.json` configuration

### Step 4: Configure Environment

The installer updates `~/.claude.json` with:

```json
{
  "mcpServers": {
    "stache": {
      "command": "/path/to/stache/tools/mcp-server/venv/bin/python",
      "args": ["/path/to/stache/tools/mcp-server/stache_mcp.py"],
      "env": {
        "STACHE_API_URL": "https://YOUR_API_GATEWAY_URL",
        "COGNITO_CLIENT_ID": "YOUR_CLIENT_ID",
        "COGNITO_CLIENT_SECRET": "YOUR_CLIENT_SECRET",
        "COGNITO_TOKEN_URL": "https://YOUR_COGNITO_DOMAIN/oauth2/token"
      }
    }
  }
}
```

Replace the placeholders:
- `YOUR_API_GATEWAY_URL` - Your API Gateway invoke URL
- `YOUR_CLIENT_ID` - Client ID from Step 1
- `YOUR_CLIENT_SECRET` - Client secret from Step 1
- `YOUR_COGNITO_DOMAIN` - Your Cognito domain (e.g., `https://your-app.auth.region.amazoncognito.com`)

### Step 5: Test

Restart Claude Code/Desktop and verify the MCP server is loaded:

```bash
# Claude Code will show "stache" in available tools
# Try: "Search my stache knowledge base for X"
```

## Option 2: Claude Web (AgentCore Gateway)

This option integrates with Claude Web (claude.ai) via AWS Bedrock AgentCore Gateway.

### Step 1: Configure OAuth

Create an OAuth app client with:
- **Flow**: `authorization_code`
- **Scopes**: Your resource server scopes + OpenID scopes
- **Grant types**: Authorization code, refresh token
- **Callback URLs**:
  - `http://127.0.0.1:33418` (for local testing)
  - `https://claude.ai/api/mcp/auth_callback` (for Claude Web)

Save the client ID and secret.

### Step 2: Create IAM Role for AgentCore

Create an IAM role that AgentCore can assume to invoke your Lambda:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "bedrock-agentcore.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

Attach policy to invoke Lambda:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "lambda:InvokeFunction",
      "Resource": "arn:aws:lambda:REGION:ACCOUNT:function:YOUR_LAMBDA_NAME"
    }
  ]
}
```

### Step 3: Create AgentCore Gateway

Create the gateway with Cognito JWT authorization:

```bash
aws bedrock-agentcore-control create-gateway \
  --name stache-mcp-gateway \
  --region us-east-1 \
  --protocol-type MCP \
  --role-arn arn:aws:iam::YOUR_ACCOUNT:role/YOUR_AGENTCORE_ROLE \
  --authorizer-type CUSTOM_JWT \
  --authorizer-configuration 'customJWTAuthorizer={discoveryUrl=YOUR_OIDC_DISCOVERY_URL,allowedClients=["YOUR_CLIENT_ID"]}'
```

Where:
- `YOUR_ACCOUNT` - Your AWS account ID
- `YOUR_AGENTCORE_ROLE` - Role ARN from Step 2
- `YOUR_OIDC_DISCOVERY_URL` - OAuth provider's discovery URL (e.g., `https://cognito-idp.REGION.amazonaws.com/POOL_ID/.well-known/openid-configuration`)
- `YOUR_CLIENT_ID` - Client ID from Step 1

Save the gateway URL from the output.

### Step 4: Create Target

Add your Lambda as a target:

```bash
aws bedrock-agentcore-control create-target \
  --gateway-identifier YOUR_GATEWAY_ID \
  --name stache-tools \
  --target-type LAMBDA_FUNCTION \
  --lambda-function-target 'lambdaArn=arn:aws:lambda:REGION:ACCOUNT:function:YOUR_LAMBDA_NAME'
```

### Step 5: Configure Claude Web

1. Go to claude.ai Settings → Integrations
2. Add custom MCP server
3. Enter:
   - **Gateway URL**: Your AgentCore gateway URL
   - **OAuth Client ID**: Client ID from Step 1
   - **OAuth Client Secret**: Client secret from Step 1
4. Authenticate via your OAuth provider's login page

## Configuration Details

### OAuth Resource Server

Your OAuth provider needs a resource server configured:

**Identifier**: Choose a unique identifier (e.g., `stache-mcp`)

**Scopes**:
- `stache-mcp/read` - Read operations (search, list, get)
- `stache-mcp/write` - Write operations (ingest)

### App Client Strategy

You'll need different OAuth clients for different use cases:

| Client Type | Flow | Use Case |
|-------------|------|----------|
| Local MCP Server | `client_credentials` | Claude Code, programmatic access |
| AgentCore Gateway | `authorization_code` | Claude Web with user login |
| PKCE Public Client | `authorization_code` + PKCE | Mobile apps, desktop apps (no secret) |

**Important**: Some OAuth providers (like Cognito) don't allow mixing `client_credentials` with `authorization_code` on the same client. Create separate clients.

### JWT Authorizer Configuration

Your API Gateway JWT authorizer needs:

**Issuer**: Your OAuth provider's issuer URL
- Cognito: `https://cognito-idp.REGION.amazonaws.com/POOL_ID`
- Auth0: `https://YOUR_DOMAIN.auth0.com/`
- Okta: `https://YOUR_DOMAIN.okta.com/oauth2/default`

**Audiences**: List of allowed client IDs (one per app client)

**Example**:
```json
{
  "Audience": [
    "client-id-1",  // stache-app (Vue frontend)
    "client-id-2",  // stache-mcp-local (Claude Code)
    "client-id-3"   // stache-mcp-client (Claude Web)
  ],
  "Issuer": "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_XXXXXXXXX"
}
```

## Troubleshooting

### "Unauthorized" errors from Claude Code

**Check**:
1. Client ID/secret are correct in `~/.claude.json`
2. Token URL is correct and accessible
3. API Gateway authorizer includes your client ID in audiences
4. Client has `client_credentials` grant type enabled

**Debug**:
```bash
# Test token acquisition directly
curl -X POST https://YOUR_COGNITO_DOMAIN/oauth2/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials&client_id=YOUR_CLIENT_ID&client_secret=YOUR_CLIENT_SECRET&scope=stache-mcp/read stache-mcp/write"
```

### "Tools not showing up" in Claude

**Check**:
1. `~/.claude.json` has correct paths (absolute, not relative)
2. Python virtual environment exists at specified path
3. MCP server script is executable
4. Restart Claude after config changes

**Debug**:
```bash
# Run MCP server manually to see errors
/path/to/venv/bin/python /path/to/stache_mcp.py
```

### AgentCore Gateway authentication fails

**Check**:
1. OIDC discovery URL is accessible
2. Client ID is in `allowedClients` list
3. Callback URL is registered in OAuth client
4. Gateway role has permission to invoke Lambda

**Debug**:
```bash
# Verify OIDC discovery
curl https://YOUR_COGNITO_DOMAIN/.well-known/openid-configuration

# Check gateway configuration
aws bedrock-agentcore-control get-gateway --gateway-identifier YOUR_GATEWAY_ID
```

### Cognito PKCE limitations

**Issue**: Cognito supports PKCE but doesn't advertise `code_challenge_methods_supported` in OIDC discovery. This breaks some MCP clients.

**Workaround**: Use the local stdio MCP server (Option 1) which handles auth internally and doesn't rely on PKCE advertisement.

## Security Best Practices

1. **Use separate clients** for different access patterns:
   - User-facing flows: `authorization_code` with user login
   - Machine-to-machine: `client_credentials` with strong secrets

2. **Rotate secrets regularly**:
   - Client secrets should be rotated every 90 days
   - Store secrets securely (AWS Secrets Manager, environment variables)

3. **Scope permissions appropriately**:
   - Read-only clients: Only `stache-mcp/read` scope
   - Admin tools: Both `stache-mcp/read` and `stache-mcp/write`

4. **Monitor OAuth usage**:
   - Track token issuance
   - Alert on unusual patterns
   - Revoke compromised clients immediately

## Next Steps

Once MCP is configured:

1. **Test the tools** in Claude:
   - "Search my stache knowledge base for [topic]"
   - "List all namespaces in stache"
   - "Ingest this text into stache: [content]"

2. **Monitor usage**:
   - Check Lambda CloudWatch logs
   - Review OAuth provider metrics
   - Track API Gateway requests

3. **Customize tools** (optional):
   - Edit `stache/tools/mcp-server/stache_mcp.py`
   - Add new tools or modify existing ones
   - Update `STACHE.md` with usage examples

## Files Reference

| File | Purpose |
|------|---------|
| `stache/tools/mcp-server/stache_mcp.py` | Local MCP server implementation |
| `stache/tools/mcp-server/install.sh` | Installation script for local server |
| `stache/tools/mcp-server/STACHE.md` | Tool usage guide for Claude |
| `stache/docs/mcp-setup.md` | This guide |

For implementation details and private deployment notes, see `stache/docs/mcp-deployment.md` (not included in public distribution).

#!/bin/bash
# Install Stache MCP server for Claude Code
#
# This script:
# 1. Creates a virtual environment
# 2. Installs dependencies
# 3. Updates ~/.claude.json with the MCP server config
#
# See /mnt/devbuntu/dev/stache/docs/mcp-deployment.md for full documentation.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Configuration - must be provided via environment variables
# DO NOT hardcode credentials here!
#
# For local development:
#   export STACHE_API_URL="http://localhost:8000"
#   ./install.sh
#
# For cloud deployment:
#   export STACHE_API_URL="https://your-api-gateway.execute-api.us-east-1.amazonaws.com"
#   export COGNITO_CLIENT_ID="your-client-id"
#   export COGNITO_CLIENT_SECRET="your-client-secret"
#   export COGNITO_TOKEN_URL="https://your-domain.auth.us-east-1.amazoncognito.com/oauth2/token"
#   ./install.sh

STACHE_API_URL="${STACHE_API_URL:-}"
COGNITO_CLIENT_ID="${COGNITO_CLIENT_ID:-}"
COGNITO_CLIENT_SECRET="${COGNITO_CLIENT_SECRET:-}"
COGNITO_TOKEN_URL="${COGNITO_TOKEN_URL:-}"

# Validate required variable
if [ -z "$STACHE_API_URL" ]; then
    echo "ERROR: STACHE_API_URL environment variable is required"
    echo ""
    echo "For local development, set:"
    echo "  export STACHE_API_URL='http://localhost:8000'"
    echo ""
    echo "Then run: ./install.sh"
    exit 1
fi

echo "Installing Stache MCP server for Claude Code..."
echo "  API URL: $STACHE_API_URL"
echo ""

# Create virtual environment if it doesn't exist
if [ ! -d "$SCRIPT_DIR/venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$SCRIPT_DIR/venv"
fi

# Activate and install dependencies
echo "Installing dependencies..."
source "$SCRIPT_DIR/venv/bin/activate"
pip install -q -r "$SCRIPT_DIR/requirements.txt"

# Update ~/.claude.json
CLAUDE_CONFIG="$HOME/.claude.json"

if [ -f "$CLAUDE_CONFIG" ]; then
    echo "Updating $CLAUDE_CONFIG..."

    # Use Python to safely update the JSON
    python3 << EOF
import json

config_path = "$CLAUDE_CONFIG"

with open(config_path, 'r') as f:
    config = json.load(f)

config['mcpServers'] = config.get('mcpServers', {})
config['mcpServers']['stache'] = {
    'command': '$SCRIPT_DIR/venv/bin/python',
    'args': ['$SCRIPT_DIR/stache_mcp.py'],
    'env': {
        'STACHE_API_URL': '$STACHE_API_URL',
        'COGNITO_CLIENT_ID': '$COGNITO_CLIENT_ID',
        'COGNITO_CLIENT_SECRET': '$COGNITO_CLIENT_SECRET',
        'COGNITO_TOKEN_URL': '$COGNITO_TOKEN_URL'
    }
}

with open(config_path, 'w') as f:
    json.dump(config, f, indent=2)

print(f"  Added stache to mcpServers")
EOF
else
    echo "Creating $CLAUDE_CONFIG..."
    cat > "$CLAUDE_CONFIG" << EOF
{
  "mcpServers": {
    "stache": {
      "command": "$SCRIPT_DIR/venv/bin/python",
      "args": ["$SCRIPT_DIR/stache_mcp.py"],
      "env": {
        "STACHE_API_URL": "$STACHE_API_URL",
        "COGNITO_CLIENT_ID": "$COGNITO_CLIENT_ID",
        "COGNITO_CLIENT_SECRET": "$COGNITO_CLIENT_SECRET",
        "COGNITO_TOKEN_URL": "$COGNITO_TOKEN_URL"
      }
    }
  }
}
EOF
fi

echo ""
echo "============================================"
echo "  Installation complete!"
echo "============================================"
echo ""
echo "Restart Claude Code to use the stache MCP server."
echo ""
echo "Available tools:"
echo "  - search         Search the knowledge base"
echo "  - list_namespaces   List all namespaces"
echo "  - list_documents    List documents"
echo "  - get_document      Get document details"
echo "  - ingest_text       Add content to knowledge base"
echo ""
echo "Documentation: $SCRIPT_DIR/../docs/mcp-deployment.md"
echo "Tool guide:    $SCRIPT_DIR/STACHE.md"
echo ""

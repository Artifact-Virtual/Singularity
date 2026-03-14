#!/usr/bin/env bash
# ⚡ Singularity Workspace — OAuth Client Setup Helper
#
# This script creates the OAuth2 client credentials needed for 
# Google Workspace integration. Run this once, then use:
#   singularity workspace setup
#
# Requirements: gcloud CLI authenticated

set -euo pipefail

PROJECT="artifact-virtual"
CLIENT_SECRET_PATH="$HOME/.singularity/workspace_client_secret.json"

echo ""
echo "⚡ Singularity Workspace — OAuth Client Setup"
echo "=============================================="
echo ""

# Check gcloud auth
if ! gcloud auth print-access-token &>/dev/null; then
    echo "❌ Not authenticated with gcloud. Run: gcloud auth login"
    exit 1
fi

echo "✅ Authenticated with gcloud"
echo ""

# Step 1: Ensure OAuth consent screen is configured
echo "Step 1: OAuth Consent Screen"
echo ""
echo "  You need to configure the OAuth consent screen in GCP Console."
echo "  This is a one-time setup that cannot be done via CLI."
echo ""
echo "  1. Go to: https://console.cloud.google.com/apis/credentials/consent?project=$PROJECT"
echo "  2. If not configured:"
echo "     - User Type: External"  
echo "     - App name: Singularity Workspace"
echo "     - Support email: ali.shakil.backup@gmail.com"
echo "     - Add scopes: Gmail, Drive, Docs, Sheets, Slides, Calendar, Tasks"
echo "     - Test users: add ali.shakil.backup@gmail.com"
echo "  3. Save"
echo ""
read -p "Press Enter once OAuth consent screen is configured..."

# Step 2: Create OAuth client
echo ""
echo "Step 2: Create OAuth Client ID"
echo ""
echo "  1. Go to: https://console.cloud.google.com/apis/credentials?project=$PROJECT"
echo "  2. Click '+ CREATE CREDENTIALS' → 'OAuth client ID'"
echo "  3. Application type: 'Desktop app'"
echo "  4. Name: 'Singularity Workspace'"
echo "  5. Click 'Create'"
echo "  6. Click 'DOWNLOAD JSON' on the confirmation dialog"
echo "  7. Save the file to: $CLIENT_SECRET_PATH"
echo ""

# Open browser
if command -v xdg-open &>/dev/null; then
    read -p "Open GCP Console in browser? (y/N): " OPEN
    if [[ "$OPEN" == "y" || "$OPEN" == "Y" ]]; then
        xdg-open "https://console.cloud.google.com/apis/credentials?project=$PROJECT" 2>/dev/null || true
    fi
fi

read -p "Press Enter once the JSON is saved to $CLIENT_SECRET_PATH..."

# Verify
mkdir -p "$(dirname "$CLIENT_SECRET_PATH")"

if [[ -f "$CLIENT_SECRET_PATH" ]]; then
    # Validate JSON
    if python3 -c "import json; json.load(open('$CLIENT_SECRET_PATH'))" 2>/dev/null; then
        CLIENT_ID=$(python3 -c "import json; d=json.load(open('$CLIENT_SECRET_PATH')); print(d.get('installed',d.get('web',{})).get('client_id','unknown'))")
        echo ""
        echo "✅ Client secret found and valid"
        echo "   Client ID: $CLIENT_ID"
        echo "   Path: $CLIENT_SECRET_PATH"
    else
        echo "❌ File exists but is not valid JSON: $CLIENT_SECRET_PATH"
        exit 1
    fi
else
    echo "❌ File not found: $CLIENT_SECRET_PATH"
    echo "   Please download the JSON and save it there."
    exit 1
fi

# Step 3: Run the Singularity workspace setup
echo ""
echo "Step 3: Authenticate"
echo ""
echo "  Running: singularity workspace setup"
echo ""

# Check if singularity command exists
if command -v singularity &>/dev/null; then
    singularity workspace setup
else
    # Run directly from Python module
    cd "$(dirname "$0")/.."
    python3 -m singularity.workspace.cli setup 2>/dev/null || \
    python3 -c "from singularity.workspace.cli import cmd_setup; cmd_setup([])"
fi

echo ""
echo "=============================================="
echo "⚡ Setup complete!"
echo ""
echo "Quick commands:"
echo "  singularity workspace status"
echo "  singularity workspace gmail inbox"
echo "  singularity workspace drive list"
echo "  singularity workspace podcast paper.md --duration 10"

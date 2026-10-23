#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd "$(dirname "$0")" && pwd)"
cd "$project_dir"

mode="${1:-docker}"

# `stdio` is used by Copilot to start the MCP as a local child process.
if [[ "$mode" == "stdio" ]]; then
  exec python3 "$project_dir/mcp_server.py"
fi

# `server` is useful for local development; the default starts the full bundle.
if [[ "$mode" == "server" ]]; then
  exec python3 mcp_server.py --http
fi

if [[ "$mode" == "docker" ]]; then
  # Compose starts the app, R runtime, Ollama, and the model-download step.
  if ! docker compose version >/dev/null 2>&1; then
    echo "Docker Compose is required. Install Docker Desktop, then run this again." >&2
    exit 1
  fi
  exec docker compose up --build
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required. Install Docker Desktop, then run this again." >&2
  exit 1
fi
# Optional lightweight path for running only the deterministic baseline.
docker build -t local-forecast-validation .
docker run --rm -v "$project_dir/output:/app/output" local-forecast-validation python forecast_workflow.py
echo "Open $project_dir/output/report.html to review the results."

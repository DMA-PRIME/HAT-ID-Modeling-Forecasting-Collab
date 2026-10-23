FROM python:3.12-slim
# R is included because submitted model files are executed as R scripts.
RUN apt-get update && apt-get install -y --no-install-recommends r-base && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY forecast_workflow.py mcp_server.py forecast_eval_adapter.R rules.json expert_rules.json model.R ./
COPY data ./data
# Docker starts the persistent web/MCP server by default.
CMD ["python", "mcp_server.py", "--http", "--host", "0.0.0.0"]

#!/usr/bin/env python3
"""Small persistent MCP server for local model review.

MCP clients first discover tools with ``tools/list`` and then invoke one with
``tools/call``. This file keeps that protocol layer thin: each MCP tool calls
one ordinary Python function, and the same functions power the web form.
"""

import argparse
import cgi
import csv
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import forecast_workflow as workflow

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")


def path_arg(arguments, name):
    """Read and normalize a required local file path from a tool request."""
    # Tool inputs are file paths because this is a local, file-based MVP.
    value = arguments.get(name)
    if not value:
        raise ValueError(f"Missing required argument: {name}")
    return Path(value).expanduser().resolve()


def write_json(path, value):
    """Write a structured tool result so later tools can use it as input."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return str(path)


def run_model(arguments):
    """MCP tool: execute the submitted R script and return its forecast file."""
    # Model contract: Rscript model.R input.csv forecast.csv.
    data_file = path_arg(arguments, "data_file")
    model_file = path_arg(arguments, "model_file")
    output_dir = Path(arguments.get("output_dir", "output/review")).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    workflow.read_data(data_file)
    forecast_file = output_dir / "forecast.csv"
    completed = subprocess.run(["Rscript", str(model_file), str(data_file), str(forecast_file)], capture_output=True, text=True, timeout=300)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "The model script failed")
    if not forecast_file.exists():
        raise RuntimeError("The model finished but did not create forecast.csv")
    return {"forecast_file": str(forecast_file), "stdout": completed.stdout[-2000:]}


def evaluate_model(arguments):
    """MCP tool: compare submitted forecasts with observed values and calculate metrics."""
    # Compare submitted forecasts with the matching observed dates.
    data_file = path_arg(arguments, "data_file")
    forecast_file = path_arg(arguments, "forecast_file")
    output_file = Path(arguments.get("output_file", "output/review/evaluation.json")).expanduser().resolve()
    actual = {row["date"]: row["value"] for row in workflow.read_data(data_file)}
    with forecast_file.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or not {"date", "forecast"}.issubset(rows[0]):
        raise ValueError("Forecast CSV must contain date and forecast columns")
    predictions = [{"date": row["date"], "actual": actual[row["date"]], "forecast": float(row["forecast"])} for row in rows if row["date"] in actual]
    if not predictions:
        raise ValueError("Forecast CSV has no dates matching the input data")
    errors = [item["actual"] - item["forecast"] for item in predictions]
    evaluation = {"method": "submitted_model", "observations": len(predictions), "mae": round(sum(abs(error) for error in errors) / len(errors), 4), "rmse": round((sum(error * error for error in errors) / len(errors)) ** 0.5, 4), "predictions": predictions}
    return {"evaluation_file": write_json(output_file, evaluation), **evaluation}


def review_model_code(arguments):
    """MCP tool: scan source text for a few obvious reproducibility and safety concerns."""
    # This is a small transparent scanner, not a replacement for human review.
    model_file = path_arg(arguments, "model_file")
    output_file = Path(arguments.get("output_file", "output/review/code_review.json")).expanduser().resolve()
    source = model_file.read_text(encoding="utf-8")
    checks = [
        (r"eval\s*\(\s*parse", "dynamic_code", "Dynamic code execution makes model behavior difficult to audit."),
        (r"system2?\s*\(", "shell_command", "The model invokes an external command; review its safety and reproducibility."),
        (r"setwd\s*\(", "working_directory", "A hard-coded working directory may prevent reproducible execution."),
        (r"read\.csv\s*\(", "data_input", "The model reads CSV input; confirm the expected columns are validated."),
        (r"library\s*\(", "package_dependency", "The model depends on R packages; record versions for reproducibility."),
    ]
    findings = []
    for pattern, finding_id, message in checks:
        for line_number, line in enumerate(source.splitlines(), start=1):
            if re.search(pattern, line, flags=re.IGNORECASE):
                findings.append({"id": finding_id, "line": line_number, "message": message})
    result = {"model_file": str(model_file), "lines": len(source.splitlines()), "findings": findings}
    return {"code_review_file": write_json(output_file, result), **result}


def ollama_model(requested=None):
    """Choose the configured Ollama model, or discover the first local model."""
    model = requested or os.environ.get("OLLAMA_MODEL")
    if model:
        return model
    request = urllib.request.Request(f"{OLLAMA_URL}/api/tags")
    with urllib.request.urlopen(request, timeout=10) as response:
        models = json.load(response).get("models", [])
    if not models:
        raise RuntimeError("Ollama is running but has no downloaded models")
    return models[0]["name"]


def generate_recommendations(arguments):
    """MCP tool: send evaluation, code findings, and expert rules to local Ollama."""
    # Ollama sees the evidence and expert rules, but never edits the model.
    evaluation_file = path_arg(arguments, "evaluation_file")
    code_review_file = path_arg(arguments, "code_review_file")
    rules_file = Path(arguments.get("rules_file", "expert_rules.json")).expanduser().resolve()
    output_file = Path(arguments.get("output_file", "output/review/recommendations.json")).expanduser().resolve()
    evaluation = json.loads(evaluation_file.read_text(encoding="utf-8"))
    code_review = json.loads(code_review_file.read_text(encoding="utf-8"))
    expert_rules = json.loads(rules_file.read_text(encoding="utf-8"))
    model = ollama_model(arguments.get("model"))
    prompt = """You are reviewing a forecasting model. Use only the supplied evidence.
Return concise JSON with keys: summary, recommendations (array), limitations.
Each recommendation must include evidence, action, and expected_benefit.

PERFORMANCE:
{performance}

CODE REVIEW:
{code_review}
EXPERT RULES (additional guidance; do not ignore your independent analysis):
{expert_rules}
""".format(performance=json.dumps(evaluation), code_review=json.dumps(code_review), expert_rules=json.dumps(expert_rules))
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False, "format": "json"}).encode()
    request = urllib.request.Request(f"{OLLAMA_URL}/api/generate", data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            raw = json.load(response).get("response", "")
    except urllib.error.URLError as error:
        raise RuntimeError(f"Could not reach Ollama at {OLLAMA_URL}: {error.reason}") from error
    try:
        recommendation = json.loads(raw)
    except json.JSONDecodeError:
        recommendation = {"summary": raw, "recommendations": [], "limitations": ["Ollama returned non-JSON text."]}
    recommendations = recommendation.setdefault("recommendations", [])
    for rule in expert_rules:
        if rule.get("always"):
            recommendations.append({"source": "expert_rule", "rule_id": rule.get("id"), "evidence": "Expert rule marked always", "action": rule.get("recommendation", rule.get("instruction")), "expected_benefit": "Addresses an expert-defined improvement area."})
    recommendation["model"] = model
    recommendation["expert_rules_file"] = str(rules_file)
    recommendation["approval"] = "pending"
    return {"recommendations_file": write_json(output_file, recommendation), **recommendation}


def page(title, body):
    """Wrap a small piece of HTML in the shared page layout and styles."""
    # Keep the UI inline so the project has no frontend build step.
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>body{{font:16px system-ui;max-width:900px;margin:32px auto;padding:0 20px;color:#222}}form,section{{border:1px solid #ddd;border-radius:8px;padding:20px;margin:16px 0}}label{{display:block;margin:14px 0 6px;font-weight:600}}input[type=file]{{display:block;margin-bottom:16px}}button{{background:#1769aa;color:white;border:0;border-radius:5px;padding:10px 16px;font-size:16px;cursor:pointer}}.notice{{background:#fff4cc;padding:12px;border-radius:5px}}.error{{background:#ffe0e0;padding:12px;border-radius:5px}}dt{{font-weight:600;margin-top:10px}}dd{{margin:2px 0 0 0}}li{{margin:8px 0}}pre{{white-space:pre-wrap;background:#f5f5f5;padding:12px;border-radius:5px}}</style></head><body>{body}</body></html>"""


def form_page():
    """Render the upload form shown at the server's root URL."""
    return page("Local model review", """<h1>Review a forecasting model</h1>
<p>Choose the data CSV and the R model script. The local workflow will run the model, calculate performance, scan the code, and ask Ollama for recommendations.</p>
<form id="review-form" action="/review" method="post" enctype="multipart/form-data" onsubmit="showWaiting()">
<label for="data_file">Data CSV</label><input id="data_file" name="data_file" type="file" accept=".csv" required>
<label for="model_file">R model script</label><input id="model_file" name="model_file" type="file" accept=".R,.r" required>
<button id="submit-button" type="submit">Run model review</button>
<div id="waiting" class="notice" hidden><strong>Your review is running.</strong><br>
The model is running, performance is being evaluated, the code is being reviewed, and Ollama is preparing recommendations. This may take a few minutes. Please keep this page open.</div></form>
<script>function showWaiting(){{document.getElementById('submit-button').disabled=true;document.getElementById('submit-button').textContent='Review running...';document.getElementById('waiting').hidden=false;}}</script>
<p class="notice">The model script must accept: <code>Rscript model.R input.csv forecast.csv</code>. Recommendations always require human approval.</p>""")


def review_page(result):
    """Render the completed review, including metrics, findings, and recommendations."""
    evaluation = result["evaluation"]
    findings = "".join(f"<li>Line {item['line']}: {html.escape(item['message'])}</li>" for item in result["code_review"]["findings"])
    findings = findings or "<li>No configured code-review findings.</li>"
    recommendation = result.get("recommendation")
    if recommendation:
        items = recommendation.get("recommendations", [])
        recs = "".join(f"<li><strong>{html.escape(str(item.get('action', '')))}</strong><br>Evidence: {html.escape(str(item.get('evidence', '')))}<br>Expected benefit: {html.escape(str(item.get('expected_benefit', '')))}</li>" for item in items)
        recs = recs or f"<li>{html.escape(str(recommendation.get('summary', 'No recommendation returned.')))}</li>"
        ai_note = f"<p>Model: <code>{html.escape(str(recommendation.get('model', 'unknown')))}</code> | Approval: <strong>pending</strong></p>"
    else:
        recs = "<li>Ollama recommendations were not available. Review the run and code findings above.</li>"
        ai_note = f"<p class=\"error\">{html.escape(result.get('recommendation_error', 'Recommendation step failed.'))}</p>"
    return page("Model review results", f"""<h1>Model review results</h1><p class="notice">Review complete. No code or model changes were made automatically.</p>
<section><h2>Run statistics</h2><dl><dt>Model</dt><dd>{html.escape(result['model_file'])}</dd><dt>Data</dt><dd>{html.escape(result['data_file'])}</dd><dt>Observations evaluated</dt><dd>{evaluation['observations']}</dd><dt>MAE</dt><dd>{evaluation['mae']}</dd><dt>RMSE</dt><dd>{evaluation['rmse']}</dd></dl></section>
<section><h2>Code review</h2><ul>{findings}</ul></section>
<section><h2>AI recommendations</h2>{ai_note}<ul>{recs}</ul></section>
<p><a href="/">Review another model</a></p>""")


def run_uploaded_review(form):
    """Compose the independent tools for the browser's one-click review flow."""
    # The browser flow composes the same independent tools exposed through MCP.
    data_item = form["data_file"] if "data_file" in form else None
    model_item = form["model_file"] if "model_file" in form else None
    if not hasattr(data_item, "file") or not hasattr(model_item, "file"):
        raise ValueError("Please choose both a data CSV and an R model script")
    review_dir = Path("output/reviews") / time.strftime("%Y%m%d-%H%M%S")
    review_dir.mkdir(parents=True, exist_ok=True)
    data_path = review_dir / Path(data_item.filename).name
    model_path = review_dir / Path(model_item.filename).name
    data_path.write_bytes(data_item.file.read())
    model_path.write_bytes(model_item.file.read())
    model_result = run_model({"data_file": str(data_path), "model_file": str(model_path), "output_dir": str(review_dir)})
    evaluation = evaluate_model({"data_file": str(data_path), "forecast_file": model_result["forecast_file"], "output_file": str(review_dir / "evaluation.json")})
    code_review = review_model_code({"model_file": str(model_path), "output_file": str(review_dir / "code_review.json")})
    result = {"data_file": data_path.name, "model_file": model_path.name, "evaluation": evaluation, "code_review": code_review}
    try:
        result["recommendation"] = generate_recommendations({"evaluation_file": evaluation["evaluation_file"], "code_review_file": code_review["code_review_file"], "rules_file": "expert_rules.json", "output_file": str(review_dir / "recommendations.json")})
    except Exception as error:
        result["recommendation_error"] = str(error)
    return result


TOOLS = [
    # These schemas let an MCP client discover and call each capability separately.
    {"name": "run_model", "description": "Run an R model script against a data CSV.", "inputSchema": {"type": "object", "properties": {"data_file": {"type": "string"}, "model_file": {"type": "string"}, "output_dir": {"type": "string"}}, "required": ["data_file", "model_file"]}},
    {"name": "evaluate_model", "description": "Calculate performance metrics from input data and a forecast CSV.", "inputSchema": {"type": "object", "properties": {"data_file": {"type": "string"}, "forecast_file": {"type": "string"}, "output_file": {"type": "string"}}, "required": ["data_file", "forecast_file"]}},
    {"name": "review_model_code", "description": "Scan model source code for basic reproducibility and safety findings.", "inputSchema": {"type": "object", "properties": {"model_file": {"type": "string"}, "output_file": {"type": "string"}}, "required": ["model_file"]}},
    {"name": "generate_recommendations", "description": "Use the local Ollama model to combine performance, code-review, and expert-rule evidence.", "inputSchema": {"type": "object", "properties": {"evaluation_file": {"type": "string"}, "code_review_file": {"type": "string"}, "rules_file": {"type": "string"}, "model": {"type": "string"}, "output_file": {"type": "string"}}, "required": ["evaluation_file", "code_review_file"]}},
]
FUNCTIONS = {"run_model": run_model, "evaluate_model": evaluate_model, "review_model_code": review_model_code, "generate_recommendations": generate_recommendations}


def rpc_response(request_id, result=None, error=None):
    """Create the JSON-RPC response format used by MCP."""
    message = {"jsonrpc": "2.0", "id": request_id}
    message["error" if error else "result"] = error or result
    return message


def handle(request):
    """Route one MCP request: initialize, discover tools, or call a tool."""
    # Minimal MCP JSON-RPC dispatcher for stdio and HTTP clients.
    method = request.get("method")
    request_id = request.get("id")
    if method == "initialize":
        # The handshake tells the client this server supports MCP tools.
        return rpc_response(request_id, {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "local-forecast-review", "version": "0.2.0"}})
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "ping":
        return rpc_response(request_id, {})
    if method == "tools/list":
        # Clients use these schemas to choose tools and construct valid arguments.
        return rpc_response(request_id, {"tools": TOOLS})
    if method == "tools/call":
        try:
            # Dispatch the requested MCP tool to its matching local function.
            params = request.get("params", {})
            value = FUNCTIONS[params["name"]](params.get("arguments", {}))
            return rpc_response(request_id, {"isError": False, "content": [{"type": "text", "text": json.dumps(value, indent=2)}], "structuredContent": value})
        except Exception as error:
            value = {"error": str(error)}
            return rpc_response(request_id, {"isError": True, "content": [{"type": "text", "text": json.dumps(value)}], "structuredContent": value})
    if request_id is not None:
        return rpc_response(request_id, error={"code": -32601, "message": f"Method not found: {method}"})
    return None


class MCPHandler(BaseHTTPRequestHandler):
    # The same process serves both the browser form and the /mcp endpoint.
    def do_GET(self):
        """Serve the browser form or a simple health check."""
        if self.path in ("/", "/index.html"):
            body = form_page().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_error(404)

    def do_POST(self):
        """Accept browser uploads or one JSON-RPC MCP request."""
        if self.path == "/review":
            try:
                form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": self.headers.get("Content-Type", "")})
                body = review_page(run_uploaded_review(form)).encode()
                status = 200
            except Exception as error:
                body = page("Review error", f"<h1>Review could not be completed</h1><p class=\"error\">{html.escape(str(error))}</p><p><a href=\"/\">Try again</a></p>").encode()
                status = 400
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path != "/mcp":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        result = handle(json.loads(self.rfile.read(length)))
        if result is None:
            self.send_response(202)
            self.end_headers()
            return
        body = json.dumps(result).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        """Keep HTTP logs on stderr so they never corrupt stdio MCP responses."""
        print(format % args, file=sys.stderr)


def main():
    """Start either the persistent HTTP server or the stdio MCP transport."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", action="store_true", help="Run as a persistent HTTP MCP server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.http:
        print(f"MCP server listening at http://{args.host}:{args.port}/mcp", file=sys.stderr)
        ThreadingHTTPServer((args.host, args.port), MCPHandler).serve_forever()
        return
    for line in sys.stdin:
        if line.strip():
            result = handle(json.loads(line))
            if result is not None:
                print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()

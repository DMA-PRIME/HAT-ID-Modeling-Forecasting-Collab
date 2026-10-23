# Minimal Local Forecast Validation

This is a deliberately small local workflow for validating a forecast model.

For complete setup and instructions for sharing this with other users, see
[SETUP.md](SETUP.md).

## Run it

For the complete packaged version, with the web form, R runtime, Ollama, and
`qwen2.5-coder:3b`:

```sh
./run.sh
```

Then open:

```sh
http://127.0.0.1:8000/
```

If port 8000 is already in use, run `APP_PORT=8080 ./run.sh` and open
`http://127.0.0.1:8080/` instead.

The first run downloads the Ollama model, which is about 1.9 GB. Docker keeps
the model in a named volume, so later runs reuse it.

For the lightweight local-only workflow without the packaged Ollama service:

```sh
./run.sh workflow
```

## Persistent MCP server

Start the persistent local MCP server:

```sh
./run.sh server
```

Then open `http://127.0.0.1:8000/` in a browser. The simple form accepts a
data CSV and R model script, runs the complete review, and displays the run
statistics, code findings, and Ollama recommendations on one page.

The same server listens at `http://127.0.0.1:8000/mcp` and provides separate tools for
running an R model, evaluating its forecast, reviewing its source code, and
generating recommendations with Ollama. The R model must use this interface:

```sh
Rscript model.R input.csv forecast.csv
```

Set `OLLAMA_MODEL` to choose the local Ollama model, or pass `model` to the
recommendation tool. Ollama is expected at `http://127.0.0.1:11434`.

## Use the richer forecastEvalReport evaluation

The MCP also exposes a separate `evaluate_complex_model` tool for forecast files
that do not fit the small `date,forecast` format. It calls the external
`forecastEvalReport-BETA` R package and keeps that package outside this repository
so the MCP remains small.

Install the external package once on the computer running the MCP:

```sh
R CMD INSTALL /path/to/forecastEvalReport-BETA
```

The package's normal R dependencies must also be installed. The tool will give a
clear message naming the missing setup if R cannot load the package.

The tool requires a completed `report_options.R` file and variables crosswalk,
along with the submitted forecast and observed truth CSVs. For example, an MCP
client can call it with:

```json
{
  "name": "evaluate_complex_model",
  "arguments": {
    "forecast_file": "/path/to/FluSight_submission.csv",
    "truth_file": "/path/to/target-hospital-admissions.csv",
    "package_dir": "/path/to/forecastEvalReport-BETA",
    "options_file": "/path/to/forecastEvalReport-BETA/DMA_PRIME_DLM.R",
    "period": "realtime",
    "output_dir": "output/complex_review"
  }
}
```

The adapter temporarily replaces the model, truth, and output paths in a copy of
the options, leaving the original options file unchanged. It returns the package's
JSON, CSV, and Markdown output paths. Use the returned JSON file as the input to
`generate_recommendations`, then keep human approval as the final step.

## Use with VS Code Copilot

The repository includes `.vscode/mcp.json`, which lets Copilot start this MCP
server over local stdio. In VS Code, open Copilot Chat in Agent mode, start the
`forecast-review` MCP server from the tools/MCP controls, and ask Copilot to
use the model-review tools. The local machine must have Python, R, and Ollama
available for this stdio configuration.

Expert guidance is stored separately in `expert_rules.json`. These rules are
provided to Ollama as additional guidance, while the model is still asked to
make independent recommendations. Rules marked `always` are also enforced in
the final output. The placeholder rule currently always recommends improving
the data.

Review `output/report.html`. Recommendations are always marked `pending`; this
first version never changes code or approves a model automatically.

## Files

- `forecast_workflow.py`: complete deterministic workflow.
- `mcp_server.py`: persistent MCP server and independent review tools.
- `forecast_eval_adapter.R`: small bridge to the external forecastEvalReport package.
- `data/fixture.csv`: small synthetic input for testing.
- `rules.json`: human-editable evaluation rules.
- `expert_rules.json`: expert guidance supplied alongside Ollama's analysis.
- `model.R`: simple file-based R model boundary for later integration.
- `Dockerfile` and `run.sh`: local reproducible execution.

The input CSV needs `date` and `value` columns, with dates in `YYYY-MM-DD`
format and at least eight observations.

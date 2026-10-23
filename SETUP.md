# Local Forecast Review Setup

This guide explains how to set up and use the local forecast-review workflow.
It is written for people who are not expected to write code.

The project has two ways to run:

1. **Docker and browser:** easiest for the small, standard workflow.
2. **VS Code and MCP:** recommended for the richer `forecastEvalReport-BETA`
   evaluation used by the colleague's FluSight model.

The workflow runs locally. Files are not sent to a cloud service by the MCP.
Ollama is also expected to run locally.

## What the workflow does

The MCP exposes separate tools so each part can be used independently:

- `run_model`: runs a compatible R model script.
- `evaluate_model`: calculates simple metrics for a CSV with `date` and `forecast`.
- `evaluate_complex_model`: runs the external `forecastEvalReport-BETA` evaluation.
- `review_model_code`: scans a submitted model file for basic findings.
- `generate_recommendations`: sends the evaluation and code-review results to
  local Ollama and adds the expert rules.

Recommendations are always marked as pending. The system never edits the model,
changes the data, or approves a recommendation automatically.

## Prerequisites

### Required for the Docker/browser workflow

- macOS or Linux
- Docker Desktop
- A web browser

### Required for the richer MCP workflow

- macOS or Linux
- Python 3
- R
- VS Code
- GitHub Copilot with Agent mode
- Ollama
- The external `forecastEvalReport-BETA` package directory

The richer workflow uses the external R package so this repository stays small.
The package is not copied into this repository or installed into the Docker image.

## 1. Get the project

Download or clone this repository. For example:

```sh
git clone <repository-url>
cd Lior-Stuff
```

If the project was downloaded as a ZIP file, open Terminal and change into the
folder containing `run.sh`.

The project folder should contain files such as:

```text
Dockerfile
mcp_server.py
forecast_eval_adapter.R
run.sh
expert_rules.json
```

## 2. Run the simple Docker/browser workflow

This is the easiest way to confirm the basic project is working.

From the project folder, run:

```sh
./run.sh
```

Open this address in a browser:

```text
http://127.0.0.1:8000/
```

The first run downloads the local Ollama model `qwen2.5-coder:3b`. The download
is approximately 1.9 GB. Later runs reuse the Docker volume.

If port 8000 is already being used:

```sh
APP_PORT=8080 ./run.sh
```

Then open:

```text
http://127.0.0.1:8080/
```

The browser form accepts a data CSV and an R model script using this contract:

```sh
Rscript model.R input.csv forecast.csv
```

It then displays the model run, evaluation, code findings, and recommendations.

Stop the Docker workflow with `Ctrl-C` in the Terminal window running it.

## 3. Install Ollama for the local MCP workflow

Install Ollama from [ollama.com](https://ollama.com/), then make sure it is
running.

Check the installed models:

```sh
ollama list
```

If `qwen2.5-coder:3b` is not listed, download it:

```sh
ollama pull qwen2.5-coder:3b
```

The MCP expects Ollama at:

```text
http://127.0.0.1:11434
```

## 4. Install R and the external evaluation package

The simple Docker workflow includes R inside Docker. The local MCP workflow
needs R installed on the computer because it runs the external evaluator locally.

Check R:

```sh
Rscript --version
```

Install the R packages used by `forecastEvalReport-BETA`:

```sh
Rscript -e 'install.packages(c("anytime","dplyr","DT","htmltools","htmlwidgets","kableExtra","knitr","jsonlite","lubridate","magrittr","plotly","rmarkdown","scoringutils"), repos="https://cloud.r-project.org")'
```

Then install the external package. Replace the path below with the location of
the package directory on the current computer:

```sh
R CMD INSTALL "/full/path/to/forecastEvalReport-BETA"
```

For example:

```sh
R CMD INSTALL "/Users/your-name/Downloads/MCP-Workflow-for-Generative-AI-ID-Forecasting-main/forecastEvalReport-BETA"
```

Confirm that R can load the package:

```sh
Rscript -e 'cat(requireNamespace("forecastEvalReport", quietly=TRUE), "\n")'
```

The expected result is:

```text
TRUE
```

## 5. Configure VS Code to use the MCP

Open the project folder in VS Code. Do not open only an individual file.

The workspace-root `.mcp.json` file starts the local server through `run.sh`.
Because each computer has a different project location, update the path in that
file if necessary:

```json
{
  "mcpServers": {
    "forecast-review": {
      "command": "/bin/bash",
      "args": ["/full/path/to/Lior-Stuff/run.sh", "stdio"]
    }
  }
}
```

Use the full path. Do not use `~` in this file.

For example:

```json
{
  "mcpServers": {
    "forecast-review": {
      "command": "/bin/bash",
      "args": ["/Users/your-name/Documents/GitHub/Lior-Stuff/run.sh", "stdio"]
    }
  }
}
```

After saving the file:

1. Run `Developer: Reload Window` in VS Code.
2. Run `MCP: Reset Cached Tools` from the Command Palette.
3. Run `MCP: List Servers`.
4. Start `forecast-review` if it is not already running.
5. Open Copilot Chat in Agent mode.

The project also contains `.vscode/mcp.json` for the VS Code-specific MCP
connection. The root `.mcp.json` is the important one for Copilot Agent sessions.

## 6. Test the MCP connection

In Copilot Chat, send:

```text
Use the forecast-review MCP server to list its available tools. Do not run a model yet.
```

The response should list:

- `run_model`
- `evaluate_model`
- `evaluate_complex_model`
- `review_model_code`
- `generate_recommendations`

If the server cannot start, see [Troubleshooting](#troubleshooting).

## 7. Run the richer evaluation

The colleague's model has already produced a FluSight forecast CSV. The first
test evaluates that CSV against the observed truth data. It does not execute the
notebook.

The external evaluation requires four important inputs:

- the forecast CSV;
- the observed truth CSV;
- the external package directory; and
- a completed options file and variables crosswalk.

Ask Copilot to call `evaluate_complex_model` with the following pattern. Replace
every `/full/path/...` value with a real path on the current computer:

```text
Use the evaluate_complex_model MCP tool now. Do not use evaluate_model.

forecast_file:
/full/path/to/FluSight_submission.csv

truth_file:
/full/path/to/target-hospital-admissions.csv

package_dir:
/full/path/to/forecastEvalReport-BETA

options_file:
/full/path/to/forecastEvalReport-BETA/DMA_PRIME_DLM.R

crosswalk_file:
/full/path/to/forecastEvalReport-BETA/Md_Sakhawat_Hossain-influenza-FluSight-DLM_Recursive_Forecast_Model.csv

period:
realtime

output_dir:
/full/path/to/Lior-Stuff/output/complex_review
```

For a testing-period evaluation, use:

```text
period: testing
```

and also provide the historical evaluation forecast as `evaluation_model_file`.
The testing-period file must be in the general evaluation forecast format
expected by `forecastEvalReport-BETA`.

The adapter creates a temporary copy of the options file with the submitted
forecast, truth, and output paths. The original options file is not changed.

## 8. Check the evaluation output

The output directory should contain files similar to:

```text
output/complex_review/
├── adapter_result.json
├── forecast_review_realtime.csv
├── forecast_review_realtime.json
└── forecast_review_realtime.md
```

The main structured evaluation file is:

```text
forecast_review_realtime.json
```

The Markdown file is convenient for a person to read. The CSV contains the
long-format evaluation results.

## 9. Review the model code

The code-review tool is separate from the evaluation tool. Ask Copilot to call
`review_model_code` with the model source file and save the result in the same
output directory.

Example:

```text
Use review_model_code with:

model_file:
/full/path/to/DMAPRIME-DLM_Submission_Weekly_US.nbconvert.ipynb

output_file:
/full/path/to/Lior-Stuff/output/complex_review/code_review.json
```

The review is a transparent first-pass scanner. It does not prove that a model
is correct or safe. A human should inspect important findings.

## 10. Generate recommendations

After both evaluation and code review have completed, ask Copilot to call
`generate_recommendations`:

```text
Use generate_recommendations with:

evaluation_file:
/full/path/to/Lior-Stuff/output/complex_review/forecast_review_realtime.json

code_review_file:
/full/path/to/Lior-Stuff/output/complex_review/code_review.json

rules_file:
/full/path/to/Lior-Stuff/expert_rules.json

model:
qwen2.5-coder:3b

output_file:
/full/path/to/Lior-Stuff/output/complex_review/recommendations.json

Do not modify the model or approve any recommendation automatically.
```

The recommendation file combines:

- the calculated evaluation results;
- the code-review findings;
- Ollama's independent analysis; and
- the expert rules in `expert_rules.json`.

The placeholder expert rule always recommends improving the data. This rule is
additional guidance; it does not replace Ollama's independent analysis.

## 11. Updating expert rules

Open `expert_rules.json` in a text editor. Each rule can include:

```json
{
  "id": "better-data",
  "always": true,
  "instruction": "Always recommend getting better data in addition to any other recommendations.",
  "recommendation": "Improve the data before making major model changes by checking its quality, completeness, representativeness, and timeliness."
}
```

Rules marked with `"always": true` are included in the final recommendations.
Keep the file valid JSON.

## Optional: run the persistent HTTP server

The VS Code setup uses stdio and does not need a network port. If another local
application needs the MCP over HTTP, run:

```sh
./run.sh server
```

The MCP endpoint is:

```text
http://127.0.0.1:8000/mcp
```

The browser page is:

```text
http://127.0.0.1:8000/
```

If port 8000 is occupied, start the server directly on another port:

```sh
python3 mcp_server.py --http --port 8080
```

The external `forecastEvalReport-BETA` package must be installed in the same
local R environment used by this HTTP server.

## Troubleshooting

### “No delegate found that can handle connection”

This usually means VS Code is using the wrong MCP configuration format or the
server was added as HTTP instead of stdio.

Check that:

- the root `.mcp.json` uses `mcpServers`;
- the command is `/bin/bash`;
- the first argument is the full path to `run.sh`;
- the second argument is `stdio`;
- VS Code was reloaded; and
- MCP cached tools were reset.

### “forecastEvalReport is not installed”

Run the R dependency installation and `R CMD INSTALL` steps again. Then confirm:

```sh
Rscript -e 'cat(requireNamespace("forecastEvalReport", quietly=TRUE), "\n")'
```

### “A completed variables crosswalk CSV is required”

Pass `crosswalk_file` explicitly to `evaluate_complex_model`. The crosswalk must
be completed, not just an empty template.

### “Could not reach Ollama”

Make sure Ollama is running and check:

```sh
ollama list
```

The expected address is `http://127.0.0.1:11434`.

### Port 8000 is already in use

Use another port for the Docker browser workflow:

```sh
APP_PORT=8080 ./run.sh
```

For the local HTTP server, use:

```sh
python3 mcp_server.py --http --port 8080
```

### The evaluator says there are no observed targets

Check that the forecast dates and locations match the truth data, and that the
truth CSV has the columns expected by the options file. Also confirm that the
correct forecast file was supplied.

### The Docker workflow works but the complex evaluator does not

That is expected if the external R package has not been installed inside the
container. Use the local VS Code MCP setup for the complex evaluator, or create a
separate Docker image that mounts and installs the external package.

## Human approval

The system is designed to assist modelers, not replace their judgment. Reviewers
should inspect the evaluation files, code findings, and recommendations before
making any model or data changes. The MCP does not automatically edit code, edit
data, or approve recommendations.

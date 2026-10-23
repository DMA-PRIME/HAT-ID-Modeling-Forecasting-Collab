#!/usr/bin/env python3
"""Small, deterministic forecast-validation workflow using only the standard library."""

import argparse
import csv
import html
import json
import math
import sys
from datetime import datetime
from pathlib import Path


def read_data(path):
    # Keep validation here so every caller uses the same input checks.
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or "date" not in rows[0] or "value" not in rows[0]:
        raise ValueError("Input CSV must contain date and value columns")
    data = []
    for number, row in enumerate(rows, start=2):
        try:
            date = datetime.strptime(row["date"], "%Y-%m-%d").date().isoformat()
            value = float(row["value"])
        except (TypeError, ValueError) as error:
            raise ValueError(f"Invalid date or value on CSV line {number}") from error
        if not math.isfinite(value):
            raise ValueError(f"Value on CSV line {number} must be finite")
        data.append({"date": date, "value": value})
    if len(data) < 8:
        raise ValueError("At least 8 observations are required")
    if any(left["date"] >= right["date"] for left, right in zip(data, data[1:])):
        raise ValueError("Dates must be strictly increasing")
    return data


def load_rules(path):
    rules = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rules, list):
        raise ValueError("Rules file must contain a JSON list")
    return rules


def evaluate(data, holdout_size):
    # This first slice uses a transparent last-value baseline.
    training = data[:-holdout_size]
    holdout = data[-holdout_size:]
    prediction = training[-1]["value"]
    predictions = [{"date": row["date"], "actual": row["value"], "forecast": prediction} for row in holdout]
    errors = [row["actual"] - row["forecast"] for row in predictions]
    mae = sum(abs(error) for error in errors) / len(errors)
    rmse = math.sqrt(sum(error * error for error in errors) / len(errors))
    return {
        "method": "naive_last_value",
        "training_observations": len(training),
        "evaluation_observations": len(holdout),
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "predictions": predictions,
    }


def apply_rules(metrics, rules):
    # Rules turn numeric results into human-readable review actions.
    recommendations = []
    for rule in rules:
        metric = metrics.get(rule.get("metric"))
        threshold = rule.get("threshold")
        if metric is None or threshold is None:
            continue
        operator = rule.get("operator", ">")
        matched = metric > threshold if operator == ">" else metric >= threshold
        if matched:
            recommendations.append({
                "id": rule.get("id", "unnamed-rule"),
                "severity": rule.get("severity", "info"),
                "reason": rule.get("reason", "Evaluation threshold was exceeded."),
                "action": rule.get("action", "Review the model."),
                "evidence": {rule["metric"]: metric, "threshold": threshold},
                "approval": "pending",
            })
    return recommendations


def write_report(output_dir, result):
    # JSON is for tools; HTML is for modelers reviewing the result.
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    rows = "".join(
        f"<tr><td>{html.escape(item['date'])}</td><td>{item['actual']:.2f}</td><td>{item['forecast']:.2f}</td></tr>"
        for item in result["evaluation"]["predictions"]
    )
    recommendations = "".join(
        f"<li><strong>{html.escape(item['severity'])}</strong>: {html.escape(item['action'])} "
        f"({html.escape(item['reason'])}) — approval: <strong>pending</strong></li>"
        for item in result["recommendations"]
    ) or "<li>No rules were triggered.</li>"
    report = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Forecast validation report</title>
<style>body{{font:16px system-ui;max-width:850px;margin:40px auto;padding:0 20px}}th,td{{padding:6px 12px;text-align:right}}th:first-child,td:first-child{{text-align:left}}.notice{{background:#fff4cc;padding:12px}}</style>
</head><body><h1>Forecast validation report</h1>
<p class="notice">Human approval is required. No recommendation has been applied automatically.</p>
<h2>Summary</h2><p>Method: <strong>{html.escape(result['evaluation']['method'])}</strong><br>
MAE: <strong>{result['evaluation']['mae']:.4f}</strong><br>RMSE: <strong>{result['evaluation']['rmse']:.4f}</strong></p>
<h2>Recommendations</h2><ul>{recommendations}</ul>
<h2>Evaluation predictions</h2><table><tr><th>Date</th><th>Actual</th><th>Forecast</th></tr>{rows}</table>
</body></html>"""
    (output_dir / "report.html").write_text(report, encoding="utf-8")


def run(input_path, rules_path, output_dir):
    # Main deterministic pipeline used by the CLI and MCP tools.
    data = read_data(input_path)
    rules = load_rules(rules_path)
    holdout_size = max(2, min(7, len(data) // 4))
    evaluation = evaluate(data, holdout_size)
    result = {
        "status": "review_required",
        "input": str(input_path),
        "observations": len(data),
        "evaluation": evaluation,
        "recommendations": apply_rules(evaluation, rules),
    }
    write_report(output_dir, result)
    return result


def main():
    parser = argparse.ArgumentParser(description="Run the local forecast validation workflow")
    parser.add_argument("--input", type=Path, default=Path("data/fixture.csv"))
    parser.add_argument("--rules", type=Path, default=Path("rules.json"))
    parser.add_argument("--output", type=Path, default=Path("output"))
    args = parser.parse_args()
    try:
        result = run(args.input, args.rules, args.output)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Workflow failed: {error}", file=sys.stderr)
        return 1
    print(f"Workflow complete: {args.output / 'report.html'}")
    print(f"Status: {result['status']} | recommendations: {len(result['recommendations'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""CSV generator - parses PSAP payload and generates metrics CSV.

Based on model_furnace/visualization/parse_furnace_results.py logic.
"""

import csv
import json
import logging
from pathlib import Path
from typing import Any, Optional

from models import TransformConfig
from utils import extract_token_counts, format_runtime_args, get_nested

logger = logging.getLogger(__name__)

# CSV column names matching parse_furnace_results.py output
CSV_FIELDNAMES = [
    "run",
    "accelerator",
    "model",
    "version",
    "prompt toks",
    "output toks",
    "TP",
    "measured concurrency",
    "intended concurrency",
    "measured rps",
    "output_tok/sec",
    "total_tok/sec",
    "prompt_token_count_mean",
    "prompt_token_count_p99",
    "output_token_count_mean",
    "output_token_count_p99",
    "ttft_median",
    "ttft_p95",
    "ttft_p1",
    "ttft_p999",
    "tpot_median",
    "tpot_p95",
    "tpot_p99",
    "tpot_p999",
    "tpot_p1",
    "itl_median",
    "itl_p95",
    "itl_p999",
    "itl_p1",
    "request_latency_median",
    "request_latency_min",
    "request_latency_max",
    "successful_requests",
    "errored_requests",
    "uuid",
    "ttft_mean",
    "ttft_p99",
    "itl_mean",
    "itl_p99",
    "runtime_args",
    "guidellm_start_time_ms",
    "guidellm_end_time_ms",
]


def parse_psap_file(psap_data: dict[str, Any], version: str) -> list[dict]:
    """Parse PSAP payload and extract benchmark metrics.

    Args:
        psap_data: Parsed PSAP JSON (Experiment format)
        version: Version string for the CSV

    Returns:
        List of row dictionaries for CSV
    """
    uuid = psap_data.get("experiment_id", "")
    model = psap_data.get("model", "")
    inference_server_args = psap_data.get("inference_server_args", {})
    tp = inference_server_args.get("tensor-parallel-size", "1")
    acc = psap_data.get("accelerator_type", "")

    # Format runtime args
    runtime_args_formatted = format_runtime_args(inference_server_args)

    # Get report (GuideLLM output)
    report = psap_data.get("report", {})
    benchmarks = report.get("benchmarks", [])
    profile_data = report.get("args", {}).get("data", [])

    if not benchmarks:
        logger.warning(f"No benchmarks found in PSAP payload {uuid}")
        return []

    # Extract token counts from profile data
    if profile_data:
        token_data = profile_data[0] if isinstance(profile_data, list) else profile_data
        prompt_toks, output_toks = extract_token_counts(str(token_data))
    else:
        prompt_toks, output_toks = 0, 0

    # Get guidellm times from PSAP
    guidellm_start_ms = psap_data.get("guidellm_start_time_ms")
    guidellm_end_ms = psap_data.get("guidellm_end_time_ms")

    rows = []
    for benchmark in benchmarks:
        strategy = benchmark.get("config", {}).get("strategy", {})
        metrics = benchmark.get("metrics", {})
        model_name = f"{acc}-{model}-{tp}"

        row = {
            "run": model_name,
            "accelerator": acc,
            "model": model,
            "version": version,
            "prompt toks": prompt_toks,
            "output toks": output_toks,
            "TP": tp,
            "measured concurrency": get_nested(metrics, "request_concurrency", "successful", "mean"),
            "intended concurrency": strategy.get("streams"),
            "measured rps": get_nested(metrics, "requests_per_second", "successful", "mean"),
            "output_tok/sec": get_nested(metrics, "output_tokens_per_second", "total", "mean"),
            "total_tok/sec": get_nested(metrics, "tokens_per_second", "total", "mean"),
            "prompt_token_count_mean": get_nested(metrics, "prompt_token_count", "successful", "mean"),
            "prompt_token_count_p99": get_nested(metrics, "prompt_token_count", "successful", "percentiles", "p99"),
            "output_token_count_mean": get_nested(metrics, "output_token_count", "successful", "mean"),
            "output_token_count_p99": get_nested(metrics, "output_token_count", "successful", "percentiles", "p99"),
            "ttft_median": get_nested(metrics, "time_to_first_token_ms", "successful", "median"),
            "ttft_p95": get_nested(metrics, "time_to_first_token_ms", "successful", "percentiles", "p95"),
            "ttft_p1": get_nested(metrics, "time_to_first_token_ms", "successful", "percentiles", "p01"),
            "ttft_p999": get_nested(metrics, "time_to_first_token_ms", "successful", "percentiles", "p999"),
            "tpot_median": get_nested(metrics, "time_per_output_token_ms", "successful", "median"),
            "tpot_p95": get_nested(metrics, "time_per_output_token_ms", "successful", "percentiles", "p95"),
            "tpot_p99": get_nested(metrics, "time_per_output_token_ms", "successful", "percentiles", "p99"),
            "tpot_p999": get_nested(metrics, "time_per_output_token_ms", "successful", "percentiles", "p999"),
            "tpot_p1": get_nested(metrics, "time_per_output_token_ms", "successful", "percentiles", "p01"),
            "itl_median": get_nested(metrics, "inter_token_latency_ms", "successful", "median"),
            "itl_p95": get_nested(metrics, "inter_token_latency_ms", "successful", "percentiles", "p95"),
            "itl_p999": get_nested(metrics, "inter_token_latency_ms", "successful", "percentiles", "p999"),
            "itl_p1": get_nested(metrics, "inter_token_latency_ms", "successful", "percentiles", "p01"),
            "request_latency_median": get_nested(metrics, "request_latency", "successful", "median"),
            "request_latency_min": get_nested(metrics, "request_latency", "successful", "min"),
            "request_latency_max": get_nested(metrics, "request_latency", "successful", "max"),
            "successful_requests": len(benchmark.get("requests", {}).get("successful", [])),
            "errored_requests": len(benchmark.get("requests", {}).get("errored", [])),
            "uuid": uuid,
            "ttft_mean": get_nested(metrics, "time_to_first_token_ms", "successful", "mean"),
            "ttft_p99": get_nested(metrics, "time_to_first_token_ms", "successful", "percentiles", "p99"),
            "itl_mean": get_nested(metrics, "inter_token_latency_ms", "successful", "mean"),
            "itl_p99": get_nested(metrics, "inter_token_latency_ms", "successful", "percentiles", "p99"),
            "runtime_args": runtime_args_formatted,
            "guidellm_start_time_ms": guidellm_start_ms,
            "guidellm_end_time_ms": guidellm_end_ms,
        }
        rows.append(row)

    return rows


def write_csv(psap_path: Path, config: TransformConfig) -> Path:
    """Parse PSAP file and write CSV.

    Args:
        psap_path: Path to PSAP JSON file
        config: Transform configuration

    Returns:
        Path to written CSV file
    """
    with open(psap_path) as f:
        psap_data = json.load(f)

    rows = parse_psap_file(psap_data, config.version)

    if not rows:
        logger.warning("No data extracted from PSAP file")
        return None

    output_path = Path(config.output_dir) / "furnace_results.csv"

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    logger.info(f"CSV generated: {output_path} ({len(rows)} rows)")
    return output_path

"""MLflow uploader for benchmark results.

Handles:
- Logging metrics with concurrency step (for Model Metrics tab)
- Uploading artifacts (CSV, HTML, compressed PSAP)
"""

import gzip
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("benchmark-transformer.mlflow")


def _get_nested(d: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Safely get a nested value from a dictionary."""
    for key in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(key, default)
    return d


def extract_metrics_from_benchmark(benchmark: Dict[str, Any]) -> Dict[str, Any]:
    """Extract metrics from a single benchmark object.

    This matches the logic in guidellm/src/benchmark/main.py to ensure
    consistent metrics are logged.
    """
    metrics = {}
    try:
        all_metrics = benchmark.get("metrics", {})
        scheduler_metrics = benchmark.get("scheduler_metrics", {})
        run_stats = benchmark.get("run_stats", {})

        requests_made = scheduler_metrics.get("requests_made", {}) or run_stats.get(
            "requests_made", {}
        )

        metric_map = {
            "total_requests": requests_made.get("total"),
            "successful_requests": requests_made.get("successful"),
            "failed_requests": requests_made.get("errored"),
            "throughput_requests_per_sec": _get_nested(
                all_metrics, "requests_per_second", "successful", "mean"
            ),
            "total_tokens_per_second": _get_nested(
                all_metrics, "tokens_per_second", "successful", "mean"
            ),
            "throughput_output_tokens_per_sec": _get_nested(
                all_metrics, "output_tokens_per_second", "successful", "mean"
            ),
            "request_concurrency_mean": _get_nested(
                all_metrics, "request_concurrency", "successful", "mean"
            ),
            "latency_mean_sec": _get_nested(
                all_metrics, "request_latency", "successful", "mean"
            ),
            "latency_median_sec": _get_nested(
                all_metrics, "request_latency", "successful", "median"
            ),
            "latency_p50_sec": _get_nested(
                all_metrics, "request_latency", "successful", "percentiles", "p50"
            ),
            "latency_p90_sec": _get_nested(
                all_metrics, "request_latency", "successful", "percentiles", "p90"
            ),
            "latency_p95_sec": _get_nested(
                all_metrics, "request_latency", "successful", "percentiles", "p95"
            ),
            "latency_p99_sec": _get_nested(
                all_metrics, "request_latency", "successful", "percentiles", "p99"
            ),
            "ttft_mean_ms": _get_nested(
                all_metrics, "time_to_first_token_ms", "successful", "mean"
            ),
            "ttft_median_ms": _get_nested(
                all_metrics, "time_to_first_token_ms", "successful", "median"
            ),
            "ttft_p95_ms": _get_nested(
                all_metrics,
                "time_to_first_token_ms",
                "successful",
                "percentiles",
                "p95",
            ),
            "ttft_p99_ms": _get_nested(
                all_metrics,
                "time_to_first_token_ms",
                "successful",
                "percentiles",
                "p99",
            ),
            "itl_mean_ms": _get_nested(
                all_metrics, "inter_token_latency_ms", "successful", "mean"
            ),
            "itl_median_ms": _get_nested(
                all_metrics, "inter_token_latency_ms", "successful", "median"
            ),
            "itl_p95_ms": _get_nested(
                all_metrics,
                "inter_token_latency_ms",
                "successful",
                "percentiles",
                "p95",
            ),
            "itl_p99_ms": _get_nested(
                all_metrics,
                "inter_token_latency_ms",
                "successful",
                "percentiles",
                "p99",
            ),
            "tpot_mean_ms": _get_nested(
                all_metrics, "time_per_output_token_ms", "successful", "mean"
            ),
            "tpot_median_ms": _get_nested(
                all_metrics, "time_per_output_token_ms", "successful", "median"
            ),
            "tpot_p95_ms": _get_nested(
                all_metrics,
                "time_per_output_token_ms",
                "successful",
                "percentiles",
                "p95",
            ),
            "tpot_p99_ms": _get_nested(
                all_metrics,
                "time_per_output_token_ms",
                "successful",
                "percentiles",
                "p99",
            ),
            "total_input_tokens": _get_nested(
                all_metrics, "prompt_token_count", "successful", "total_sum"
            ),
            "total_output_tokens": _get_nested(
                all_metrics, "output_token_count", "successful", "total_sum"
            ),
        }

        metrics = {k: v for k, v in metric_map.items() if v is not None}

        if metrics.get("total_requests", 0) > 0 and "failed_requests" in metrics:
            metrics["error_rate"] = metrics["failed_requests"] / metrics["total_requests"]
        elif "total_requests" in metrics:
            metrics["error_rate"] = 0.0

        total_input = metrics.get("total_input_tokens", 0)
        total_output = metrics.get("total_output_tokens", 0)
        if total_input > 0 or total_output > 0:
            metrics["total_tokens"] = total_input + total_output

        logger.debug(f"Extracted {len(metrics)} metrics from benchmark")
        return metrics

    except Exception as e:
        logger.error(f"Error extracting metrics: {e}")
        return {}


def get_concurrency_step(benchmark: Dict[str, Any]) -> int:
    """Extract concurrency step from benchmark config."""
    concurrency_step = 0
    config_or_args = benchmark.get("config") or benchmark.get("args", {})
    try:
        concurrency_step = int(config_or_args["strategy"]["streams"])
    except (KeyError, TypeError, IndexError):
        try:
            concurrency_step = int(config_or_args["profile"]["streams"][0])
        except (KeyError, TypeError, IndexError):
            logger.warning("Could not find concurrency 'streams', using step=0")
    return concurrency_step


def upload_to_mlflow(
    guidellm_output: Dict[str, Any],
    config,
    psap_path: Optional[str] = None,
    csv_path: Optional[str] = None,
    html_path: Optional[str] = None,
) -> Optional[str]:
    """Upload benchmark results to MLflow.

    Args:
        guidellm_output: Raw GuideLLM JSON output
        config: TransformConfig with run metadata
        psap_path: Path to PSAP JSON file (will be compressed before upload)
        csv_path: Path to CSV file
        html_path: Path to HTML report

    Returns:
        MLflow run ID if successful, None otherwise
    """
    try:
        import mlflow
        import urllib3

        urllib3.disable_warnings()
    except ImportError:
        logger.warning("MLflow not available, skipping upload")
        return None

    mlflow_uri = os.environ.get("MLFLOW_TRACKING_URI", "")
    if not mlflow_uri:
        logger.info("MLFLOW_TRACKING_URI not set, skipping upload")
        return None

    try:
        experiment_name = config.model_name.replace("/", "-")
        mlflow.set_experiment(experiment_name)

        client = mlflow.tracking.MlflowClient()

        # Search for existing run with this UUID
        experiment = mlflow.get_experiment_by_name(experiment_name)
        runs = client.search_runs(
            experiment_ids=[experiment.experiment_id],
            filter_string=f"tags.run_uuid = '{config.run_uuid}'",
        )

        if runs:
            run_id = runs[0].info.run_id
            logger.info(f"Found existing MLflow run: {run_id}")
        else:
            logger.info("No existing run found, creating new one")
            with mlflow.start_run(run_name=config.run_uuid) as run:
                mlflow.set_tag("run_uuid", config.run_uuid)
                mlflow.set_tag("pipeline_run_uuid", config.run_uuid)
                mlflow.log_param("model_name", config.model_name)
                mlflow.log_param("accelerator", config.accelerator)
                mlflow.log_param("version", config.version)
                mlflow.log_param("tp", config.tp)
            run_id = run.info.run_id
            logger.info(f"Created new MLflow run: {run_id}")

        # Log metrics from benchmarks
        benchmarks = guidellm_output.get("benchmarks", [])
        logger.info(f"Logging metrics from {len(benchmarks)} benchmarks")

        with mlflow.start_run(run_id=run_id):
            for benchmark in benchmarks:
                concurrency_step = get_concurrency_step(benchmark)
                metrics = extract_metrics_from_benchmark(benchmark)

                if metrics:
                    metrics["concurrency"] = concurrency_step
                    for key, value in metrics.items():
                        mlflow.log_metric(key, value, step=concurrency_step)
                    logger.info(
                        f"Logged {len(metrics)} metrics for concurrency={concurrency_step}"
                    )

        # Upload artifacts
        if csv_path and Path(csv_path).exists():
            client.log_artifact(run_id, csv_path, "results")
            logger.info(f"Uploaded CSV: {Path(csv_path).name}")

        if html_path and Path(html_path).exists():
            client.log_artifact(run_id, html_path, "reports")
            logger.info(f"Uploaded HTML: {Path(html_path).name}")

        # Compress and upload PSAP JSON
        if psap_path and Path(psap_path).exists():
            gz_path = f"{psap_path}.gz"
            with open(psap_path, "rb") as f_in:
                with gzip.open(gz_path, "wb") as f_out:
                    f_out.write(f_in.read())
            client.log_artifact(run_id, gz_path, "results")
            logger.info(f"Uploaded compressed PSAP: {Path(gz_path).name}")

        logger.info(f"MLflow upload complete: {run_id}")
        return run_id

    except Exception as e:
        logger.error(f"MLflow upload failed: {e}")
        import traceback

        traceback.print_exc()
        return None

import argparse
import json
import logging
import subprocess
import sys
import os
import requests
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

import mlflow

# Import BenchmarkProcessor for visualization
try:
    from processor import BenchmarkProcessor

    PROCESSOR_AVAILABLE = True
except ImportError:
    PROCESSOR_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("BenchmarkProcessor not available - reports will not be generated")


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def extract_metrics_from_benchmark(benchmark: Dict[str, Any]) -> Dict[str, Any]:
    metrics = {}
    try:
        # Support both v0.3.0 (run_stats) and v0.4.0+ (scheduler_metrics)
        scheduler_metrics = benchmark.get("scheduler_metrics", {})
        run_stats = benchmark.get("run_stats", {})
        all_metrics = benchmark.get("metrics", {})

        # Request stats - try v0.4.0 first, fallback to v0.3.0
        requests_made = scheduler_metrics.get("requests_made", {}) or run_stats.get(
            "requests_made", {}
        )
        if "total" in requests_made:
            metrics["total_requests"] = requests_made["total"]
        if "successful" in requests_made:
            metrics["successful_requests"] = requests_made["successful"]
        if "errored" in requests_made:
            metrics["failed_requests"] = requests_made["errored"]

        # Error Rate
        if metrics.get("total_requests", 0) > 0 and "failed_requests" in metrics:
            metrics["error_rate"] = (
                metrics["failed_requests"] / metrics["total_requests"]
            )
        elif "total_requests" in metrics:
            metrics["error_rate"] = 0.0

        # Throughput
        req_throughput = all_metrics.get("requests_per_second", {}).get(
            "successful", {}
        )
        if "mean" in req_throughput:
            metrics["throughput_requests_per_sec"] = req_throughput["mean"]

        tok_throughput = all_metrics.get("tokens_per_second", {}).get("successful", {})
        if "mean" in tok_throughput:
            metrics["total_tokens_per_second"] = tok_throughput["mean"]

        output_tok_throughput = all_metrics.get("output_tokens_per_second", {}).get(
            "successful", {}
        )
        if "mean" in output_tok_throughput:
            metrics["throughput_output_tokens_per_sec"] = output_tok_throughput["mean"]

        # Concurrency
        concurrency = all_metrics.get("request_concurrency", {}).get("successful", {})
        if "mean" in concurrency:
            metrics["request_concurrency_mean"] = concurrency["mean"]

        # Latency (Overall Request)
        latency = all_metrics.get("request_latency", {}).get("successful", {})
        latency_pct = latency.get("percentiles", {})
        if "mean" in latency:
            metrics["latency_mean_sec"] = latency["mean"]
        if "median" in latency:
            metrics["latency_median_sec"] = latency["median"]
        if "p50" in latency_pct:
            metrics["latency_p50_sec"] = latency_pct["p50"]
        if "p90" in latency_pct:
            metrics["latency_p90_sec"] = latency_pct["p90"]
        if "p95" in latency_pct:
            metrics["latency_p95_sec"] = latency_pct["p95"]
        if "p99" in latency_pct:
            metrics["latency_p99_sec"] = latency_pct["p99"]

        # TTFT
        ttft = all_metrics.get("time_to_first_token_ms", {}).get("successful", {})
        ttft_pct = ttft.get("percentiles", {})
        if "mean" in ttft:
            metrics["ttft_mean_ms"] = ttft["mean"]
        if "median" in ttft:
            metrics["ttft_median_ms"] = ttft["median"]
        if "p95" in ttft_pct:
            metrics["ttft_p95_ms"] = ttft_pct["p95"]
        if "p99" in ttft_pct:
            metrics["ttft_p99_ms"] = ttft_pct["p99"]

        # ITL
        itl = all_metrics.get("inter_token_latency_ms", {}).get("successful", {})
        itl_pct = itl.get("percentiles", {})
        if "mean" in itl:
            metrics["itl_mean_ms"] = itl["mean"]
        if "median" in itl:
            metrics["itl_median_ms"] = itl["median"]
        if "p95" in itl_pct:
            metrics["itl_p95_ms"] = itl_pct["p95"]
        if "p99" in itl_pct:
            metrics["itl_p99_ms"] = itl_pct["p99"]

        # TPOT (Time Per Output Token)
        tpot = all_metrics.get("time_per_output_token_ms", {}).get("successful", {})
        tpot_pct = tpot.get("percentiles", {})
        if "mean" in tpot:
            metrics["tpot_mean_ms"] = tpot["mean"]
        if "median" in tpot:
            metrics["tpot_median_ms"] = tpot["median"]
        if "p95" in tpot_pct:
            metrics["tpot_p95_ms"] = tpot_pct["p95"]
        if "p99" in tpot_pct:
            metrics["tpot_p99_ms"] = tpot_pct["p99"]

        # Tokens
        input_tokens = all_metrics.get("prompt_token_count", {}).get("successful", {})
        output_tokens = all_metrics.get("output_token_count", {}).get("successful", {})

        total_input = 0
        if "total_sum" in input_tokens:
            total_input = input_tokens["total_sum"]
            metrics["total_input_tokens"] = total_input

        total_output = 0
        if "total_sum" in output_tokens:
            total_output = output_tokens["total_sum"]
            metrics["total_output_tokens"] = total_output

        if total_input > 0 or total_output > 0:
            metrics["total_tokens"] = total_input + total_output

        logger.info(f"Extracted {len(metrics)} metrics from benchmark object")
        return metrics

    except Exception as e:
        logger.error(
            f"Error extracting metrics from benchmark object: {e}", exc_info=True
        )
        return {}


def run_guidellm_cli(
    target: str,
    model: str,
    rate: str,
    backend_type: str = "openai_http",
    rate_type: str = "concurrent",
    data: str = None,
    max_seconds: int = None,
    max_requests: int = None,
    processor: str = None,
    output_path: str = "benchmark_output.json",
) -> tuple[str, str]:
    cmd = [
        "guidellm",
        "benchmark",
        "run",
        "--target",
        target,
        "--model",
        model,
        "--backend-type",
        backend_type,
        "--rate-type",
        rate_type,
        "--rate",
        str(rate),
        "--output-path",
        output_path,
    ]

    if target.startswith("https://"):
        # cmd.extend(["--backend-kwargs", '{"verify": false}'])
        cmd.extend(["--backend-args", '{"verify": false}'])
    if data:
        cmd.extend(["--data", data])
    if max_seconds:
        cmd.extend(["--max-seconds", str(max_seconds)])
    if max_requests:
        cmd.extend(["--max-requests", str(max_requests)])
    if processor:
        cmd.extend(["--processor", processor])

    logger.info(f"Running guidellm command: {' '.join(cmd)}")

    console_log_path = output_path.replace(".json", "_console.log")

    try:
        with open(console_log_path, "w") as log_file:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            for line in process.stdout:
                print(line, end="")
                log_file.write(line)
                log_file.flush()

            return_code = process.wait()

            if return_code != 0:
                logger.error(f"Guidellm command failed with return code {return_code}")
            else:
                logger.info("Guidellm completed successfully")

        return output_path, console_log_path

    except Exception as e:
        logger.error(f"Guidellm command failed: {e}")
        return output_path, console_log_path


def generate_visualization_report(
    json_path: str,
    model: str,
    accelerator: str = None,
    version: str = None,
    tp_size: int = 1,
    runtime_args: str = "",
    output_dir: str = None,
) -> str:
    """
    Generate HTML visualization report from benchmark JSON.
    This is failure-proof - returns None if generation fails.

    Args:
        json_path: Path to benchmark JSON file
        model: Model name
        accelerator: Accelerator type
        version: Version identifier
        tp_size: Tensor parallelism size
        runtime_args: Runtime arguments
        output_dir: Output directory for HTML report

    Returns:
        Path to HTML report, or None if generation failed
    """
    if not PROCESSOR_AVAILABLE:
        logger.info("Skipping visualization - BenchmarkProcessor not available")
        return None

    try:
        logger.info("Generating visualization report...")

        # Get S3 configuration from environment
        s3_bucket = os.environ.get("S3_BUCKET", "rhaiis-psap")
        s3_key = os.environ.get("S3_KEY", "Dashboard_csv's/consolidated_dashboard.csv")

        # Auto-generate output filename
        model_short = model.split("/")[-1].replace(" ", "_").replace("-", "_").lower()
        version_str = version.lower() if version else "unknown"
        html_filename = f"{model_short}_tp{tp_size}_{version_str}_report.html"

        if output_dir:
            html_path = str(Path(output_dir) / html_filename)
        else:
            html_path = f"/tmp/{html_filename}"

        processor = BenchmarkProcessor(
            json_path=json_path,
            s3_bucket=s3_bucket,
            s3_key=s3_key,
            accelerator=accelerator or "unknown",
            model_name=model,
            version=version or "unknown",
            tp_size=tp_size,
            runtime_args="",  # TODO: Extract from deployment
            output_html=html_path,
        )

        processor.process()

        if Path(html_path).exists():
            logger.info(f"Visualization report generated: {html_path}")
            return html_path
        else:
            logger.warning(
                "Visualization report generation completed but file not found"
            )
            return None

    except Exception as e:
        logger.warning(
            f"Visualization report generation failed (non-fatal): {e}", exc_info=True
        )
        return None


def run_benchmark_without_mlflow(
    target: str,
    model: str,
    rate: str,
    backend_type: str = "openai_http",
    rate_type: str = "concurrent",
    data: str = None,
    max_seconds: int = None,
    max_requests: int = None,
    processor: str = None,
    output_dir: str = "/benchmark-results",
    accelerator: str = None,
    version: str = None,
    tp_size: int = 1,
    runtime_args: str = "",
) -> str:
    """Run benchmark without MLflow tracking, saving results to specified directory."""
    logger.info(f"Running benchmark without MLflow tracking")
    logger.info(f"Starting benchmark for rates: {rate}")
    logger.info(f"Results will be saved to: {output_dir}")

    # Ensure output directory exists
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    output_json = f"{output_dir}/benchmark_output.json"
    json_path, console_log_path = run_guidellm_cli(
        target=target,
        model=model,
        rate=rate,
        backend_type=backend_type,
        rate_type=rate_type,
        data=data,
        max_seconds=max_seconds,
        max_requests=max_requests,
        processor=processor,
        output_path=output_json,
    )

    if Path(json_path).exists():
        logger.info(f"Benchmark results saved to: {json_path}")
        with open(json_path, "r") as f:
            result_json = json.load(f)

        benchmarks = result_json.get("benchmarks", [])
        logger.info(f"Found {len(benchmarks)} benchmark results")

        # Print summary metrics
        for i, benchmark in enumerate(benchmarks):
            metrics = extract_metrics_from_benchmark(benchmark)
            if metrics:
                logger.info(
                    f"Benchmark {i + 1} metrics: {json.dumps(metrics, indent=2)}"
                )
    else:
        logger.warning(f"Output JSON not found: {json_path}")

    if Path(console_log_path).exists():
        logger.info(f"Console log saved to: {console_log_path}")
    else:
        logger.warning(f"Console log not found: {console_log_path}")

    # Generate visualization report (failure-proof)
    html_report = generate_visualization_report(
        json_path=json_path,
        model=model,
        accelerator=accelerator,
        version=version,
        tp_size=tp_size,
        runtime_args=runtime_args,
        output_dir=output_dir,
    )

    if html_report and Path(html_report).exists():
        logger.info(f"Visualization report saved to: {html_report}")
    else:
        logger.info("Visualization report not generated (continuing without it)")

    return json_path


def run_benchmark_with_mlflow(
    target: str,
    model: str,
    rate: str,
    backend_type: str = "openai_http",
    rate_type: str = "concurrent",
    data: str = None,
    max_seconds: int = None,
    max_requests: int = None,
    processor: str = None,
    accelerator: str = None,
    experiment_name: str = "guidellm-benchmarks",
    mlflow_tracking_uri: str = None,
    tags: Dict[str, str] = None,
    version: str = None,
    tp_size: int = 1,
    runtime_args: str = "",
) -> str:
    if mlflow_tracking_uri:
        mlflow.set_tracking_uri(mlflow_tracking_uri)

    mlflow.set_experiment(experiment_name)

    # Run name for the whole sweep
    run_name = (
        f"{model.split('/')[-1]}_sweep_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )

    logger.info(f"Starting benchmark sweep: rates={rate}")

    with mlflow.start_run(run_name=run_name) as run:
        try:
            # Common params for the whole sweep
            params = {
                "target": target,
                "model": model,
                "backend_type": backend_type,
                "rate_type": rate_type,
                "rates": rate,
            }
            if data:
                # params["data"] = data  # log data profile splitted
                params.update(
                    {
                        d.split("=")[0].strip(): d.split("=")[1].strip()
                        for d in data.split(",")
                    }
                )
            if max_seconds:
                params["max_seconds"] = max_seconds
            if max_requests:
                params["max_requests"] = max_requests
            if processor:
                params["processor"] = processor
            if accelerator:
                params["accelerator"] = accelerator

            mlflow.log_params(params)

            guidellm_version = os.environ.get("GUIDELLM_VERSION", "unknown")

            try:
                vllm_version = requests.get(f"{target}/version", verify=False).json()[
                    "version"
                ]
            except Exception:
                vllm_version = "unknown"

            default_tags = {
                "model": model,
                "rate_type": rate_type,
                "vllm": vllm_version,
                "guidellm": guidellm_version,
            }
            if accelerator:
                default_tags["accelerator"] = accelerator
            if tags:
                default_tags.update(tags)

            mlflow.set_tags(default_tags)

            output_json = "/tmp/benchmark_sweep.json"
            json_path, console_log_path = run_guidellm_cli(
                target=target,
                model=model,
                rate=rate,
                backend_type=backend_type,
                rate_type=rate_type,
                data=data,
                max_seconds=max_seconds,
                max_requests=max_requests,
                processor=processor,
                output_path=output_json,
            )

            if Path(json_path).exists():
                with open(json_path, "r") as f:
                    result_json = json.load(f)

                benchmarks = result_json.get("benchmarks", [])
                if not benchmarks:
                    logger.warning("No benchmarks found in JSON output")

                logger.info(f"Found {len(benchmarks)} benchmark results in JSON.")

                for benchmark in benchmarks:
                    concurrency_step = 0

                    # Support both v0.3.0 (args) and v0.4.0+ (config)
                    config_or_args = benchmark.get("config") or benchmark.get(
                        "args", {}
                    )

                    try:
                        concurrency_step = int(config_or_args["strategy"]["streams"])
                    except (KeyError, TypeError, IndexError):
                        try:
                            # Fallback for other strategies
                            concurrency_step = int(
                                config_or_args["profile"]["streams"][0]
                            )
                        except (KeyError, TypeError, IndexError):
                            logger.warning(
                                "Could not find concurrency 'streams' or 'measured_concurrencies'. "
                                "Metrics will be logged without a step."
                            )

                    metrics = extract_metrics_from_benchmark(benchmark)

                    if metrics:
                        # Add concurrency as a metric for easier comparison
                        metrics["concurrency"] = concurrency_step

                        # Log each metric with the concurrency as the step
                        for key, value in metrics.items():
                            mlflow.log_metric(key, value, step=concurrency_step)

                        logger.info(
                            f"Logged {len(metrics)} metrics for step "
                            f"(concurrency={concurrency_step})"
                        )

                mlflow.log_artifact(json_path, "results")
                logger.info("Logged full JSON artifact")
            else:
                logger.warning(f"Output JSON not found: {json_path}")

            if Path(console_log_path).exists():
                mlflow.log_artifact(console_log_path, "logs")
                logger.info("Logged console output")
            else:
                logger.warning(f"Console log not found: {console_log_path}")

            # Generate visualization report (failure-proof)
            html_report = generate_visualization_report(
                json_path=json_path,
                model=model,
                accelerator=accelerator,
                version=version,
                tp_size=tp_size,
                runtime_args=runtime_args,
                output_dir="/tmp",
            )

            if html_report and Path(html_report).exists():
                mlflow.log_artifact(html_report, "reports")
                logger.info(f"Logged visualization report to MLflow: {html_report}")
            else:
                logger.info(
                    "Visualization report not generated (continuing without it)"
                )

            logger.info(f"Run completed: {run.info.run_id}")
            return run.info.run_id

        except Exception as e:
            logger.error(f"Benchmark sweep failed: {e}")
            mlflow.log_param("error", str(e))
            raise


def main():
    parser = argparse.ArgumentParser(
        description="GuideLLM Benchmark with MLflow Logging",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("--target", required=True, help="Target URL")
    parser.add_argument("--model", required=True, help="Model name")
    parser.add_argument("--backend-type", default="openai_http", help="Backend type")
    parser.add_argument("--rate-type", default="concurrent", help="Rate type")
    parser.add_argument("--rate", required=True, help="Rate value(s), comma-separated")
    parser.add_argument(
        "--data", help="Data config (e.g., 'prompt_tokens=1000,output_tokens=1000')"
    )
    parser.add_argument("--max-seconds", type=int, help="Max duration in seconds")
    parser.add_argument("--max-requests", type=int, help="Max number of requests")
    parser.add_argument("--processor", help="Processor/tokenizer name")

    parser.add_argument("--accelerator", help="Accelerator type (e.g., H200, A100)")
    parser.add_argument(
        "--version", help="Version identifier for visualization reports"
    )
    parser.add_argument(
        "--tp",
        type=int,
        default=1,
        help="Tensor parallelism size for visualization reports",
    )
    parser.add_argument(
        "--runtime-args", default="", help="Runtime arguments for visualization reports"
    )

    parser.add_argument(
        "--experiment-name",
        default="guidellm-benchmarks",
        help="MLflow experiment name",
    )
    parser.add_argument("--mlflow-tracking-uri", help="MLflow tracking URI")
    parser.add_argument(
        "--tag", action="append", dest="tags", help="Additional tags (key=value)"
    )

    args = parser.parse_args()

    tags = {}
    if args.tags:
        for tag in args.tags:
            key, value = tag.split("=", 1)
            tags[key.strip()] = value.strip()

    logger.info(f"Starting benchmark sweep for rates: {args.rate}")

    # Log in to HF
    hf_authenticated = False
    try:
        subprocess.run(
            ["hf", "auth", "login", "--token", os.environ.get("HF_CLI_TOKEN")],
            check=True,
            capture_output=True,
            timeout=30,
        )
        logger.info("Successfully authenticated with 'hf auth login'")
        hf_authenticated = True
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        subprocess.TimeoutExpired,
    ):
        pass

    if not hf_authenticated:
        try:
            subprocess.run(
                ["huggingface-cli", "login", "--token", os.environ.get("HF_CLI_TOKEN")],
                check=True,
                capture_output=True,
                timeout=30,
            )
            logger.info("Successfully authenticated with 'huggingface-cli login'")
            hf_authenticated = True
        except (
            subprocess.CalledProcessError,
            FileNotFoundError,
            subprocess.TimeoutExpired,
        ):
            pass

    if not hf_authenticated:
        logger.info(
            "Could not authenticate with HuggingFace CLI, continuing without authentication"
        )

    # Check if MLflow is enabled via environment variable
    mlflow_enabled = os.environ.get("MLFLOW_ENABLED", "false").lower() == "true"

    if not mlflow_enabled:
        logger.info("MLflow tracking disabled - running benchmark without MLflow")
        try:
            json_path = run_benchmark_without_mlflow(
                target=args.target,
                model=args.model,
                rate=args.rate,
                backend_type=args.backend_type,
                rate_type=args.rate_type,
                data=args.data,
                max_seconds=args.max_seconds,
                max_requests=args.max_requests,
                processor=args.processor,
                output_dir="/benchmark-results",
                accelerator=args.accelerator,
                version=args.version,
                tp_size=args.tp,
                runtime_args=args.runtime_args,
            )
            logger.info("\nBenchmark completed successfully.")
            logger.info(f"  Results saved to: {json_path}")
            return 0
        except Exception as e:
            logger.error(f"Benchmark failed: {e}")
            return 1

    logger.info("MLflow tracking enabled")
    try:
        run_id = run_benchmark_with_mlflow(
            target=args.target,
            model=args.model,
            rate=args.rate,
            backend_type=args.backend_type,
            rate_type=args.rate_type,
            data=args.data,
            max_seconds=args.max_seconds,
            max_requests=args.max_requests,
            processor=args.processor,
            accelerator=args.accelerator,
            experiment_name=args.experiment_name,
            mlflow_tracking_uri=args.mlflow_tracking_uri,
            tags=tags,
            version=args.version,
            tp_size=args.tp,
            runtime_args=args.runtime_args,
        )
        logger.info("\nBenchmark sweep completed successfully.")
        logger.info(f"  MLflow Run ID: {run_id}")
        return 0
    except Exception as e:
        logger.error(f"Benchmark sweep failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

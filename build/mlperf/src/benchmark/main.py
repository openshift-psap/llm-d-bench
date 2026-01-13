import argparse
import subprocess
import sys
import os
from urllib.parse import urlparse


def derive_model_category(model_name: str) -> str:
    """
    Derive model category from HuggingFace model name.

    Examples:
        "RedHatAI/Meta-Llama-3.1-8B-Instruct-FP8" -> "llama3.1-8b"
        "meta-llama/Llama-3.1-8B" -> "llama3.1-8b"
    """
    name = model_name.split("/")[-1].lower()

    if (
        "llama-3.1-8b" in name
        or "llama-31-8b" in name
        or "llama_3.1_8b" in name
        or "llama_31_8b" in name
    ):
        return "llama3.1-8b"
    elif "llama-2-70b" in name or "llama_2_70b" in name:
        return "llama2-70b"
    elif "deepseek-r1" in name or "deepseek_r1" in name:
        return "deepseek-r1"
    else:
        return name


def main():
    parser = argparse.ArgumentParser(
        description="MLPerf benchmark wrapper for Tekton pipelines"
    )

    # Common parameters (shared with GuideLLM)
    parser.add_argument("--target", required=True, help="Target inference endpoint URL")
    parser.add_argument("--model", required=True, help="HuggingFace model identifier")
    parser.add_argument(
        "--experiment-name", default="mlperf-benchmarks", help="MLflow experiment name"
    )
    parser.add_argument(
        "--mlflow-tracking-uri", default="", help="MLflow tracking server URI"
    )

    # MLPerf-specific parameters
    parser.add_argument(
        "--dataset-path",
        required=True,
        help="Path to dataset file (e.g., /datasets/cnn_eval.json)",
    )
    parser.add_argument("--dataset-name", required=True, help="Dataset name identifier")
    parser.add_argument(
        "--scenario",
        default="Offline",
        choices=["Offline", "Server", "SingleStream", "MultiStream"],
        help="MLPerf scenario",
    )
    parser.add_argument(
        "--test-mode",
        default="accuracy",
        choices=["accuracy", "performance"],
        help="MLPerf test mode",
    )
    parser.add_argument("--batch-size", type=int, help="Batch size for inference")
    parser.add_argument("--num-samples", type=int, help="Number of samples to process")
    parser.add_argument(
        "--server-target-qps",
        type=int,
        default=10,
        help="Target QPS for Server scenario",
    )
    parser.add_argument(
        "--output-dir", default="./test-run", help="Output directory for results"
    )

    args = parser.parse_args()

    print("MLPerf Benchmark Wrapper")
    print("=" * 60)

    model_category = derive_model_category(args.model)
    lg_model_name = model_category

    mlflow_host = ""
    if args.mlflow_tracking_uri:
        parsed = urlparse(args.mlflow_tracking_uri)
        mlflow_host = parsed.netloc or parsed.path.strip("/")

    if not os.path.exists(args.dataset_path):
        print(f"ERROR: Dataset file not found: {args.dataset_path}")
        sys.exit(1)

    cmd = [
        "python3",
        "/app/mlperf-harness/harness/harness_main.py",
        "--model-category",
        model_category,
        "--model",
        args.model,
        "--dataset-path",
        args.dataset_path,
        "--dataset-name",
        args.dataset_name,
        "--scenario",
        args.scenario,
        "--test-mode",
        args.test_mode,
        "--num-samples",
        str(args.num_samples),
        "--output-dir",
        args.output_dir,
        "--lg-model-name",
        lg_model_name,
        "--api-server-url",
        args.target,
        "--mlflow-experiment-name",
        args.experiment_name,
        "--endpoint-type",
        "completions",  # XXX: Hardcoded for now
        "--log-level",
        "DEBUG",
    ]

    if args.scenario == "Server":
        cmd.extend(["--server-target-qps", str(args.server_target_qps)])

    if args.batch_size:
        cmd.extend(["--batch-size", str(args.batch_size)])

    if mlflow_host:
        cmd.extend(["--mlflow-host", mlflow_host])

    print("\nExecuting MLPerf harness with command:")
    print(" ".join(cmd))

    try:
        return_code = subprocess.run(cmd, check=True).returncode

        # XXX: Command output streaming sometimes breaks the pipeline
        # so just uncomment this and rebuild the image if you need
        # to debug something

        # process = subprocess.Popen(
        #     cmd,
        #     stdout=subprocess.PIPE,
        #     stderr=subprocess.STDOUT,
        #     text=True,
        #     bufsize=1,
        #     universal_newlines=True,
        # )

        # for line in process.stdout:
        #     print(line, end="")

        # return_code = process.wait()

        if return_code != 0:
            print(f"\nERROR: MLPerf harness failed with exit code {return_code}")
            sys.exit(return_code)

        print("\nMLPerf harness completed successfully")
        sys.exit(0)

    except FileNotFoundError:
        print("\nERROR: harness_main.py not found")
        print("Please ensure harness_main.py is available in the MLPerf image")
        sys.exit(1)
    except Exception as e:
        print(f"\nERROR: Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

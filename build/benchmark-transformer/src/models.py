"""Data models for benchmark transformation."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class Experiment:
    """PSAP-compatible experiment payload structure.

    Based on model_furnace/validate_model/payload.py Experiment dataclass.
    """
    experiment_id: str
    experiment_type: str  # "perf" or "eval"
    model: str
    inference_server: str
    inference_server_version: str
    container_image: str
    container_image_tag: str
    container_entrypoint: Optional[str]
    inference_server_args: dict[str, str]
    accelerator_type: str
    accelerator_count: int
    accelerator_memory_gb: Optional[int]
    machine_type: Optional[str]
    provider: Optional[str]
    report: dict[str, Any]  # Full GuideLLM output
    timestamp: str
    guidellm_start_time_ms: Optional[int]
    guidellm_end_time_ms: Optional[int]


@dataclass
class TransformConfig:
    """Configuration for benchmark transformation pipeline."""
    input_path: str
    output_dir: str
    run_uuid: str
    model_name: str
    accelerator: str
    version: str
    tp: int
    deployment_image: str = ""
    vllm_args: list[str] = field(default_factory=list)
    guidellm_data: str = ""

    # Optional S3 config for visualization
    s3_bucket: str = "rhaiis-psap"
    s3_key: str = "Dashboard_csv's/consolidated_dashboard.csv"

    # Control which outputs to generate
    generate_visualization: bool = True
    generate_psap: bool = True
    generate_csv: bool = True
    mlflow_upload: bool = False


@dataclass
class BenchmarkMetrics:
    """Extracted metrics from a single benchmark run."""
    run: str
    accelerator: str
    model: str
    version: str
    prompt_tokens: int
    output_tokens: int
    tp: int
    measured_concurrency: Optional[float]
    intended_concurrency: Optional[int]
    measured_rps: Optional[float]
    output_tokens_per_sec: Optional[float]
    total_tokens_per_sec: Optional[float]
    ttft_mean: Optional[float]
    ttft_median: Optional[float]
    ttft_p95: Optional[float]
    ttft_p99: Optional[float]
    ttft_p999: Optional[float]
    ttft_p1: Optional[float]
    tpot_mean: Optional[float]
    tpot_median: Optional[float]
    tpot_p95: Optional[float]
    tpot_p99: Optional[float]
    tpot_p999: Optional[float]
    tpot_p1: Optional[float]
    itl_mean: Optional[float]
    itl_median: Optional[float]
    itl_p95: Optional[float]
    itl_p99: Optional[float]
    itl_p999: Optional[float]
    itl_p1: Optional[float]
    request_latency_median: Optional[float]
    request_latency_min: Optional[float]
    request_latency_max: Optional[float]
    successful_requests: int
    errored_requests: int
    uuid: str
    runtime_args: str
    guidellm_start_time_ms: Optional[int]
    guidellm_end_time_ms: Optional[int]

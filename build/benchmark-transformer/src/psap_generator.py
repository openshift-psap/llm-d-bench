"""PSAP payload generator - wraps GuideLLM output with metadata.

Based on model_furnace/validate_model/payload.py logic.
"""

import dataclasses
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from models import Experiment, TransformConfig
from utils import (
    convert_ms_to_eastern_iso,
    extract_guidellm_times,
    get_profile_name,
    parse_image_tag,
    parse_vllm_args,
    sanitize_model_name,
)

logger = logging.getLogger(__name__)


class EnhancedJSONEncoder(json.JSONEncoder):
    """JSON encoder that handles dataclasses."""

    def default(self, o):
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        return super().default(o)


def generate_psap_payload(
    guidellm_output: dict[str, Any],
    config: TransformConfig,
) -> Experiment:
    """Generate PSAP-format Experiment from GuideLLM output.

    Args:
        guidellm_output: Parsed GuideLLM benchmark_output.json
        config: Transform configuration with model/accelerator/version info

    Returns:
        Experiment dataclass ready to be serialized
    """
    # Parse deployment image
    container_image, container_tag = parse_image_tag(config.deployment_image)

    # Parse vLLM args to dict
    inference_server_args = parse_vllm_args(config.vllm_args)

    # Add TP to args if not present
    if "tensor-parallel-size" not in inference_server_args:
        inference_server_args["tensor-parallel-size"] = str(config.tp)

    # Extract timing from GuideLLM output
    start_ms, end_ms = extract_guidellm_times(guidellm_output)

    # Get timestamp - use guidellm start time or current time
    if start_ms:
        timestamp = convert_ms_to_eastern_iso(start_ms)
    else:
        timestamp = datetime.now().isoformat()

    experiment = Experiment(
        experiment_id=config.run_uuid,
        experiment_type="perf",
        model=config.model_name,
        inference_server="vllm",
        inference_server_version=container_tag,
        container_image=container_image,
        container_image_tag=container_tag,
        container_entrypoint=None,
        inference_server_args=inference_server_args,
        accelerator_type=config.accelerator,
        accelerator_count=config.tp,
        accelerator_memory_gb=None,  # Optional - can be added later
        machine_type=None,
        provider=None,
        report=guidellm_output,
        timestamp=timestamp,
        guidellm_start_time_ms=start_ms,
        guidellm_end_time_ms=end_ms,
    )

    return experiment


def generate_psap_filename(config: TransformConfig) -> str:
    """Generate PSAP filename following model-furnace convention.

    Format: PSAP_perf_{profile}_{accelerator}_{model}_{date}.json

    Args:
        config: Transform configuration

    Returns:
        Filename like "PSAP_perf_profile-1_H200_llama-3-3-70b-fp8_20260205.json"
    """
    profile = get_profile_name(config.guidellm_data)
    model_name = sanitize_model_name(config.model_name)
    date_str = datetime.now().strftime("%Y%m%d")

    return f"PSAP_perf_{profile}_{config.accelerator}_{model_name}_{date_str}.json"


def write_psap_payload(
    guidellm_output: dict[str, Any],
    config: TransformConfig,
) -> Path:
    """Generate and write PSAP payload to output directory.

    Args:
        guidellm_output: Parsed GuideLLM benchmark_output.json
        config: Transform configuration

    Returns:
        Path to written PSAP file
    """
    experiment = generate_psap_payload(guidellm_output, config)
    filename = generate_psap_filename(config)
    output_path = Path(config.output_dir) / filename

    with open(output_path, "w") as f:
        json.dump(experiment, f, cls=EnhancedJSONEncoder, indent=2)

    logger.info(f"PSAP payload written to: {output_path}")
    return output_path

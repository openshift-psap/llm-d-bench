"""Utility functions for benchmark transformation."""

import re
from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo


def get_nested(d: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Safely get a nested value from a dictionary."""
    for key in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(key, default)
    return d


def extract_token_counts(data_str: str) -> tuple[int, int]:
    """Extract prompt_tokens and output_tokens from a data string.

    Args:
        data_str: String like "prompt_tokens=1000,output_tokens=1000"

    Returns:
        Tuple of (prompt_tokens, output_tokens)
    """
    tokens = dict(re.findall(r"(\w+)=([\d.]+)", data_str))
    return int(tokens.get("prompt_tokens", 0)), int(tokens.get("output_tokens", 0))


def format_runtime_args(inference_server_args: dict[str, str]) -> str:
    """Format inference_server_args dict into a semicolon-separated string.

    Args:
        inference_server_args: Dict like {"tensor_parallel_size": "4"}

    Returns:
        String like "tensor-parallel-size: 4; max-model-len: 8192"
    """
    if not inference_server_args:
        return ""

    formatted_args = []
    for key, value in inference_server_args.items():
        formatted_key = key.replace("_", "-")
        formatted_args.append(f"{formatted_key}: {value}")

    return "; ".join(formatted_args)


def parse_vllm_args(vllm_args: list[str]) -> dict[str, str]:
    """Parse vLLM args list into a dictionary.

    Args:
        vllm_args: List like ["--tensor-parallel-size=4", "--max-model-len=8192"]

    Returns:
        Dict like {"tensor-parallel-size": "4", "max-model-len": "8192"}
    """
    result = {}
    for arg in vllm_args:
        if not arg:
            continue
        # Remove leading dashes
        arg = arg.lstrip("-")
        if "=" in arg:
            key, value = arg.split("=", 1)
            result[key] = value
        else:
            # Flag without value
            result[arg] = "true"
    return result


def parse_image_tag(image: str) -> tuple[str, str]:
    """Parse container image into image name and tag.

    Args:
        image: Full image like "registry.redhat.io/rhaiis/vllm-cuda-rhel9:3.2.3"

    Returns:
        Tuple of (image_name, tag)
    """
    if ":" in image:
        parts = image.rsplit(":", 1)
        return parts[0], parts[1]
    return image, "latest"


def convert_ms_to_eastern_iso(timestamp_ms: int) -> str:
    """Convert Unix ms timestamp to Eastern Time ISO 8601 string."""
    dt_utc = datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc)
    eastern_tz = ZoneInfo("America/New_York")
    dt_eastern = dt_utc.astimezone(eastern_tz)
    return dt_eastern.isoformat()


def extract_guidellm_times(report: dict) -> tuple[Optional[int], Optional[int]]:
    """Extract start and end times from GuideLLM report.

    Args:
        report: Full GuideLLM output JSON

    Returns:
        Tuple of (start_time_ms, end_time_ms)
    """
    benchmarks = report.get("benchmarks", [])
    if not benchmarks:
        return None, None

    start_times = []
    end_times = []

    for benchmark in benchmarks:
        scheduler_metrics = benchmark.get("scheduler_metrics", {})
        if "start_time" in scheduler_metrics:
            start_times.append(scheduler_metrics["start_time"])
        if "end_time" in scheduler_metrics:
            end_times.append(scheduler_metrics["end_time"])

    start_ms = int(min(start_times) * 1000) if start_times else None
    end_ms = int(max(end_times) * 1000) if end_times else None

    return start_ms, end_ms


def get_profile_name(data_str: str) -> str:
    """Determine profile name from GuideLLM data string.

    Args:
        data_str: String like "prompt_tokens=1000,output_tokens=1000"

    Returns:
        Profile name like "profile-1", "profile-2", etc.
    """
    if "prompt_tokens=1000,output_tokens=1000" in data_str:
        return "profile-1"
    elif "prompt_tokens=512" in data_str and "stdev" in data_str:
        return "profile-2"
    elif "prompt_tokens=2048,output_tokens=128" in data_str:
        return "profile-3"
    elif "prompt_tokens=32000,output_tokens=512" in data_str:
        return "profile-4"
    else:
        # Extract tokens for custom profile name
        prompt, output = extract_token_counts(data_str)
        return f"p{prompt}-o{output}"


def sanitize_model_name(model_name: str) -> str:
    """Sanitize model name for use in filenames.

    Args:
        model_name: Model name like "Qwen/Qwen3-0.6B"

    Returns:
        Sanitized name like "qwen3-0-6b"
    """
    # Take last part after /
    name = model_name.split("/")[-1]
    # Replace dots and underscores with hyphens
    name = name.replace(".", "-").replace("_", "-")
    # Lowercase
    name = name.lower()
    return name

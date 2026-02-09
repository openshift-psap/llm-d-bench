"""Visualization report generator - generates HTML charts from benchmark data.

This is a simplified wrapper that can be extended later.
For full functionality, see build/guidellm/src/benchmark/processor/processor.py
"""

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

from models import TransformConfig

logger = logging.getLogger(__name__)

# Optional dependencies - visualization is non-critical
try:
    import boto3
    import pandas as pd
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    VISUALIZATION_AVAILABLE = True
except ImportError:
    VISUALIZATION_AVAILABLE = False
    logger.warning("Visualization dependencies not available (pandas, plotly, boto3)")


def generate_visualization_report(
    guidellm_output: dict[str, Any],
    config: TransformConfig,
) -> Optional[Path]:
    """Generate HTML visualization report from GuideLLM output.

    Args:
        guidellm_output: Parsed GuideLLM benchmark_output.json
        config: Transform configuration

    Returns:
        Path to generated HTML file, or None if generation failed
    """
    if not VISUALIZATION_AVAILABLE:
        logger.info("Skipping visualization - dependencies not available")
        return None

    if not config.generate_visualization:
        logger.info("Visualization generation disabled")
        return None

    try:
        # Generate output filename
        model_short = config.model_name.split("/")[-1].replace("-", "_").lower()
        version_str = config.version.lower().replace(".", "").replace("-", "")
        html_filename = f"{model_short}_tp{config.tp}_{version_str}_report.html"
        output_path = Path(config.output_dir) / html_filename

        # Extract benchmark data
        benchmarks = guidellm_output.get("benchmarks", [])
        if not benchmarks:
            logger.warning("No benchmarks found in GuideLLM output")
            return None

        # Create simple visualization
        _generate_simple_report(benchmarks, config, output_path)

        if output_path.exists():
            logger.info(f"Visualization report generated: {output_path}")
            return output_path
        else:
            logger.warning("Visualization report file not created")
            return None

    except Exception as e:
        logger.warning(f"Visualization generation failed (non-fatal): {e}")
        return None


def _generate_simple_report(
    benchmarks: list[dict],
    config: TransformConfig,
    output_path: Path,
) -> None:
    """Generate a simple HTML report with key metrics.

    Args:
        benchmarks: List of benchmark results from GuideLLM
        config: Transform configuration
        output_path: Path to write HTML file
    """
    # Extract metrics for each concurrency level
    data = []
    for benchmark in benchmarks:
        metrics = benchmark.get("metrics", {})
        strategy = benchmark.get("config", {}).get("strategy", {})

        concurrency = strategy.get("streams", 0)
        throughput = _get_nested(metrics, "output_tokens_per_second", "total", "mean", default=0)
        ttft_median = _get_nested(metrics, "time_to_first_token_ms", "successful", "median", default=0)
        tpot_median = _get_nested(metrics, "time_per_output_token_ms", "successful", "median", default=0)

        data.append({
            "concurrency": concurrency,
            "throughput": throughput,
            "ttft_median": ttft_median,
            "tpot_median": tpot_median,
        })

    if not data:
        logger.warning("No data extracted for visualization")
        return

    # Sort by concurrency
    data.sort(key=lambda x: x["concurrency"])

    # Create subplots
    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=[
            "Throughput vs Concurrency",
            "TTFT Median vs Concurrency",
            "TPOT Median vs Concurrency",
            "Summary"
        ],
        vertical_spacing=0.12,
        horizontal_spacing=0.1,
    )

    # Extract x and y values
    x_vals = [d["concurrency"] for d in data]

    # Plot 1: Throughput
    fig.add_trace(
        go.Scatter(
            x=x_vals,
            y=[d["throughput"] for d in data],
            mode="lines+markers",
            name="Throughput",
            line=dict(color="#3274A1", width=2),
            marker=dict(size=8),
        ),
        row=1, col=1,
    )

    # Plot 2: TTFT
    fig.add_trace(
        go.Scatter(
            x=x_vals,
            y=[d["ttft_median"] for d in data],
            mode="lines+markers",
            name="TTFT Median",
            line=dict(color="#E1812C", width=2),
            marker=dict(size=8),
        ),
        row=1, col=2,
    )

    # Plot 3: TPOT
    fig.add_trace(
        go.Scatter(
            x=x_vals,
            y=[d["tpot_median"] for d in data],
            mode="lines+markers",
            name="TPOT Median",
            line=dict(color="#7CB57C", width=2),
            marker=dict(size=8),
        ),
        row=2, col=1,
    )

    # Update layout
    model_short = config.model_name.split("/")[-1]
    fig.update_layout(
        title={
            "text": f"<b>{model_short} Performance Report</b><br>"
                   f"<sub>Version: {config.version} | Accelerator: {config.accelerator} | TP: {config.tp}</sub>",
            "x": 0.5,
            "xanchor": "center",
        },
        height=800,
        width=1200,
        plot_bgcolor="white",
        showlegend=True,
    )

    # Update axes
    fig.update_xaxes(title_text="Concurrency", showgrid=True, gridcolor="lightgray")
    fig.update_yaxes(showgrid=True, gridcolor="lightgray")
    fig.update_yaxes(title_text="Tokens/sec", row=1, col=1)
    fig.update_yaxes(title_text="TTFT (ms)", row=1, col=2)
    fig.update_yaxes(title_text="TPOT (ms)", row=2, col=1)

    # Write HTML
    fig.write_html(str(output_path))


def _get_nested(d: dict, *keys: str, default: Any = None) -> Any:
    """Safely get a nested value from a dictionary."""
    for key in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(key, default)
    return d

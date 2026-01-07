import ast
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional, List

import boto3
import pandas as pd
import plotly.graph_objects as go
import yaml
from botocore.exceptions import ClientError
from plotly.subplots import make_subplots


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("benchmark_processor")


def _get_nested(d: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Safely get a nested value from a dictionary."""
    for key in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(key, default)
    return d


def _parse_request_data(requests_data: Any) -> Dict[str, int]:
    """Parse request data to extract prompt and output tokens."""
    prompt_tokens = 0
    output_tokens = 0
    data_str = ""

    if isinstance(requests_data, str):
        if "=" in requests_data:
            data_str = requests_data
        else:
            try:
                evaluated_data = ast.literal_eval(requests_data)
                if isinstance(evaluated_data, list) and evaluated_data:
                    data_str = evaluated_data[0]
            except (ValueError, SyntaxError):
                pass  # Not a list string, treat as empty
    elif isinstance(requests_data, list) and requests_data:
        data_str = requests_data[0]

    if data_str:
        for part in data_str.split(","):
            if "=" in part:
                key, value = part.strip().split("=")
                try:
                    if key == "prompt_tokens":
                        prompt_tokens = int(value)
                    elif key == "output_tokens":
                        output_tokens = int(value)
                except ValueError:
                    pass  # Ignore non-integer values

    return {"prompt_tokens": prompt_tokens, "output_tokens": output_tokens}


class BenchmarkProcessor:
    """
    Main class for processing benchmark JSON files and generating reports.

    Workflow:
    1. Download consolidated CSV from S3
    2. Process JSON benchmark file to CSV
    3. Merge with consolidated data
    4. Generate HTML report based on config
    """

    def __init__(
        self,
        json_path: str,
        s3_bucket: str,
        s3_key: str,
        accelerator: str,
        model_name: str,
        version: str,
        tp_size: int,
        runtime_args: str,
        compare_versions: Optional[List[str]] = None,
        config_path: Optional[str] = None,
        output_html: Optional[str] = None,
        aws_profile: Optional[str] = None,
    ):
        """
        Initialize the benchmark processor.

        Args:
            json_path: Path to guidellm JSON benchmark file
            s3_bucket: S3 bucket name containing consolidated CSV
            s3_key: S3 key (path) to consolidated CSV file
            accelerator: Accelerator type (e.g., H200, MI300X)
            model_name: Model name
            version: Version/framework identifier
            tp_size: Tensor parallelism size
            runtime_args: Runtime configuration arguments
            compare_versions: List of versions to compare against (includes current version)
            config_path: Optional path to YAML config file (auto-generated if not provided)
            output_html: Output HTML report filename (optional)
            aws_profile: AWS profile name (optional)
        """
        self.json_path = json_path
        self.config_path = config_path
        self.s3_bucket = s3_bucket
        self.s3_key = s3_key
        self.accelerator = accelerator
        self.model_name = model_name
        self.version = version
        self.tp_size = tp_size
        self.runtime_args = runtime_args
        self.output_html = output_html or "benchmark_report.html"

        # Versions to comare (always include the current version)
        if compare_versions is None:
            # XXX: Default versions to compare against
            compare_versions = ["llm-d-0.3", "RHOAI-3.0", "RHAIIS-3.2.3"]

        if version not in compare_versions:
            compare_versions.append(version)

        self.compare_versions = compare_versions

        session = (
            boto3.Session(profile_name=aws_profile) if aws_profile else boto3.Session()
        )
        self.s3_client = session.client("s3")

        self.consolidated_df: Optional[pd.DataFrame] = None
        self.new_data_df: Optional[pd.DataFrame] = None
        self.combined_df: Optional[pd.DataFrame] = None
        self.config: Optional[Dict[str, Any]] = None

    def download_s3_csv(self) -> pd.DataFrame:
        """
        Download consolidated CSV file from S3.

        Returns:
            DataFrame containing consolidated benchmark data
        """
        logger.info(f"Downloading s3://{self.s3_bucket}/{self.s3_key}")

        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", delete=False, suffix=".csv"
            ) as tmp_file:
                self.s3_client.download_fileobj(self.s3_bucket, self.s3_key, tmp_file)
                tmp_path = tmp_file.name

            df = pd.read_csv(tmp_path)
            os.unlink(tmp_path)

            logger.info(f"Downloaded {len(df)} rows from S3")
            return df

        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                logger.warning(
                    f"S3 file not found: s3://{self.s3_bucket}/{self.s3_key}"
                )
                logger.info("Starting with empty consolidated data")
                return pd.DataFrame()
            else:
                raise

    def load_additional_csvs(self, csv_file_paths: List[str]) -> pd.DataFrame:
        """
        Load additional CSV files and merge them with the consolidated data.

        Args:
            csv_file_paths: List of paths to additional CSV files

        Returns:
            DataFrame containing all data merged (S3 CSV + additional CSVs)
        """
        if not csv_file_paths:
            logger.info("No additional CSV files to load")
            return self.consolidated_df

        logger.info(f"Loading {len(csv_file_paths)} additional CSV file(s)")
        additional_dfs = []

        for csv_file in csv_file_paths:
            logger.info(f"Loading additional CSV: {csv_file}")
            try:
                additional_df = pd.read_csv(csv_file)
                logger.info(f"Loaded {len(additional_df)} rows from {csv_file}")
                additional_dfs.append(additional_df)
            except Exception as e:
                logger.error(f"Failed to load {csv_file}: {e}")
                raise ValueError(f"Could not load additional CSV file {csv_file}: {e}")

        # Merge additional CSVs with consolidated CSV
        if additional_dfs:
            logger.info(
                f"Merging {len(additional_dfs)} additional CSV(s) with consolidated data"
            )
            all_csvs = [self.consolidated_df] + additional_dfs
            merged_df = pd.concat(all_csvs, ignore_index=True)
            logger.info(f"After merging: {len(merged_df)} total rows")
            return merged_df

        return self.consolidated_df

    def process_benchmark_section(
        self, benchmark_run: Dict[str, Any], benchmark_index: int
    ) -> Dict[str, Any]:
        """
        Process a single benchmark section and extract performance metrics.

        Args:
            benchmark_run: Benchmark run data from JSON
            benchmark_index: Index of the benchmark run

        Returns:
            Dictionary containing processed benchmark metrics
        """
        full_model_name = f"{self.accelerator}-{self.model_name}-{self.tp_size}"

        uuid = _get_nested(benchmark_run, "config", "run_id") or benchmark_run.get(
            "run_id"
        )

        requests_data = _get_nested(
            benchmark_run, "request_loader", "data"
        ) or _get_nested(benchmark_run, "config", "requests", "data")

        token_info = _parse_request_data(requests_data)
        config_prompt_tokens = token_info["prompt_tokens"]
        config_output_tokens = token_info["output_tokens"]

        profile_args = _get_nested(benchmark_run, "config", "profile") or _get_nested(
            benchmark_run, "args", "profile", default={}
        )
        streams = profile_args.get("streams", [])

        if benchmark_index < len(streams):
            intended_concurrency = streams[benchmark_index]
        else:
            intended_concurrency = streams[0] if streams else None

        metrics = benchmark_run.get("metrics", {})
        successful_metrics = lambda *keys: _get_nested(
            metrics, *keys, "successful", default={}
        )

        measured_concurrency = successful_metrics("request_concurrency").get("mean")
        measured_rps = successful_metrics("requests_per_second").get("mean")
        output_tok_per_sec = successful_metrics("output_tokens_per_second").get(
            "mean", 0
        )
        total_tok_per_sec = successful_metrics("tokens_per_second").get("mean", 0)

        requests_made = _get_nested(
            benchmark_run, "scheduler_metrics", "requests_made", default={}
        )
        successful_reqs = requests_made.get("successful", 0)
        errored_reqs = requests_made.get("errored", 0)

        prompt_tok_metrics = successful_metrics("prompt_token_count")
        output_tok_metrics = successful_metrics("output_token_count")
        ttft_metrics = successful_metrics("time_to_first_token_ms")
        tpot_metrics = successful_metrics("time_per_output_token_ms")
        itl_metrics = successful_metrics("inter_token_latency_ms")
        request_latency_metrics = successful_metrics("request_latency")

        row = {
            "run": full_model_name,
            "accelerator": self.accelerator,
            "model": self.model_name,
            "version": self.version,
            "prompt toks": config_prompt_tokens,
            "output toks": config_output_tokens,
            "TP": self.tp_size,
            "measured concurrency": measured_concurrency,
            "intended concurrency": intended_concurrency,
            "measured rps": measured_rps,
            "output_tok/sec": output_tok_per_sec,
            "total_tok/sec": total_tok_per_sec,
            "prompt_token_count_mean": prompt_tok_metrics.get("mean"),
            "prompt_token_count_p99": _get_nested(
                prompt_tok_metrics, "percentiles", "p99"
            ),
            "output_token_count_mean": output_tok_metrics.get("mean"),
            "output_token_count_p99": _get_nested(
                output_tok_metrics, "percentiles", "p99"
            ),
            "ttft_median": ttft_metrics.get("median"),
            "ttft_p95": _get_nested(ttft_metrics, "percentiles", "p95"),
            "ttft_p1": _get_nested(ttft_metrics, "percentiles", "p01"),
            "ttft_p999": _get_nested(ttft_metrics, "percentiles", "p999"),
            "tpot_median": tpot_metrics.get("median"),
            "tpot_p95": _get_nested(tpot_metrics, "percentiles", "p95"),
            "tpot_p99": _get_nested(tpot_metrics, "percentiles", "p99"),
            "tpot_p999": _get_nested(tpot_metrics, "percentiles", "p999"),
            "tpot_p1": _get_nested(tpot_metrics, "percentiles", "p01"),
            "itl_median": itl_metrics.get("median"),
            "itl_p95": _get_nested(itl_metrics, "percentiles", "p95"),
            "itl_p999": _get_nested(itl_metrics, "percentiles", "p999"),
            "itl_p1": _get_nested(itl_metrics, "percentiles", "p01"),
            "request_latency_median": request_latency_metrics.get("median"),
            "request_latency_min": request_latency_metrics.get("min"),
            "request_latency_max": request_latency_metrics.get("max"),
            "successful_requests": successful_reqs,
            "errored_requests": errored_reqs,
            "uuid": uuid,
            "ttft_mean": ttft_metrics.get("mean"),
            "ttft_p99": _get_nested(ttft_metrics, "percentiles", "p99"),
            "itl_mean": itl_metrics.get("mean"),
            "itl_p99": _get_nested(itl_metrics, "percentiles", "p99"),
            "runtime_args": self.runtime_args,
        }

        return row

    def parse_guidellm_json(self) -> pd.DataFrame:
        """
        Parse GuideLL JSON benchmark results.

        Returns:
            DataFrame containing processed benchmark data
        """
        logger.info(f"Processing JSON file: {self.json_path}")

        try:
            with open(self.json_path) as f:
                data = json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"JSON file not found at {self.json_path}")
        except json.JSONDecodeError:
            raise ValueError(f"Could not decode JSON from {self.json_path}")

        if not data.get("benchmarks"):
            raise ValueError("JSON file does not contain a 'benchmarks' key")

        benchmarks = data["benchmarks"]

        if len(benchmarks) > 1:
            logger.info(f"Processing {len(benchmarks)} separate benchmark sections")
        else:
            logger.info("Processing single benchmark")

        all_run_data = []
        for i, benchmark_run in enumerate(benchmarks):
            row_data = self.process_benchmark_section(benchmark_run, i)
            if row_data:
                all_run_data.append(row_data)

        if not all_run_data:
            raise ValueError("No valid data extracted from benchmark sections")

        df = pd.DataFrame(all_run_data)
        logger.info(f"Extracted {len(df)} rows from JSON")
        return df

    def merge_data(self) -> pd.DataFrame:
        """
        Merge new benchmark data with consolidated CSV.

        Returns:
            Combined DataFrame
        """
        logger.info("Merging new data with consolidated data")

        if self.consolidated_df.empty:
            combined = self.new_data_df
        else:
            combined = pd.concat(
                [self.consolidated_df, self.new_data_df], ignore_index=True
            )

        # Ensure all required columns are present
        fieldnames = [
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
        ]

        for col in fieldnames:
            if col not in combined.columns:
                combined[col] = None

        combined = combined[fieldnames]
        logger.info(f"Combined data has {len(combined)} total rows")

        return combined

    def generate_auto_config(self) -> Dict[str, Any]:
        """
        Auto-generate configuration based on command-line arguments.

        Returns:
            Auto-generated configuration dictionary
        """
        logger.info("Auto-generating configuration from command-line arguments")

        with open(self.json_path) as f:
            data = json.load(f)

        prompt_toks = 1000  # default
        output_toks = 1000  # default

        if data.get("benchmarks"):
            benchmark = data["benchmarks"][0]
            requests_data = _get_nested(
                benchmark, "request_loader", "data"
            ) or _get_nested(benchmark, "config", "requests", "data")
            token_info = _parse_request_data(requests_data)
            prompt_toks = token_info["prompt_tokens"] or prompt_toks
            output_toks = token_info["output_tokens"] or output_toks

        config = {
            "models": [
                {
                    "model": self.model_name,
                    "prompt_toks": prompt_toks,
                    "output_toks": output_toks,
                }
            ],
            "plots": [
                {
                    "x_metric": "intended concurrency",
                    "y_metric": "output_tok/sec",
                    "x_label": "Concurrency",
                    "y_label": "Throughput (Output tokens/sec)",
                    "title": "Throughput vs Concurrency",
                    "higher_is_better": True,
                    "log_x": False,
                    "log_y": False,
                },
                {
                    "x_metric": "intended concurrency",
                    "y_metric": "ttft_median",
                    "x_label": "Concurrency",
                    "y_label": "TTFT median (ms)",
                    "title": "TTFT median vs Concurrency",
                    "higher_is_better": False,
                    "log_x": False,
                    "log_y": False,
                },
                {
                    "x_metric": "intended concurrency",
                    "y_metric": "ttft_p95",
                    "x_label": "Concurrency",
                    "y_label": "TTFT P95 (ms)",
                    "title": "TTFT P95 vs Concurrency",
                    "higher_is_better": False,
                    "log_x": False,
                    "log_y": False,
                },
                {
                    "x_metric": "intended concurrency",
                    "y_metric": "itl_median",
                    "x_label": "Concurrency",
                    "y_label": "ITL median (ms)",
                    "title": "ITL median vs Concurrency",
                    "higher_is_better": False,
                    "log_x": False,
                    "log_y": False,
                },
                {
                    "x_metric": "intended concurrency",
                    "y_metric": "tpot_median",
                    "x_label": "Concurrency",
                    "y_label": "TPOT median (ms)",
                    "title": "TPOT median vs Concurrency",
                    "higher_is_better": False,
                    "log_x": False,
                    "log_y": False,
                },
            ],
            "filters": {
                "accelerators": [self.accelerator],
                "versions": self.compare_versions,
            },
            "styling": {
                "colors": [
                    "#3274A1",
                    "#E1812C",
                    "#7CB57C",
                    "#D95F5F",
                    "#9E67AB",
                    "#B8704F",
                    "#E89CAE",
                    "#7C7C7C",
                    "#1F77B4",
                    "#FF7F0E",
                    "#2CA02C",
                    "#D62728",
                ],
                "markers": [
                    "circle",
                    "square",
                    "diamond",
                    "triangle-up",
                    "triangle-down",
                    "cross",
                    "x",
                    "star",
                    "pentagon",
                    "hexagon",
                ],
            },
        }

        logger.info(f"Auto-generated config for model: {self.model_name}")
        logger.info(f"Comparing versions: {self.compare_versions}")
        logger.info(f"Token configuration: {prompt_toks}in/{output_toks}out")

        return config

    def load_config(self) -> Dict[str, Any]:
        """
        Load configuration from YAML file or auto-generate.

        Returns:
            Configuration dictionary
        """
        if self.config_path:
            config_file = Path(self.config_path)

            if not config_file.exists():
                raise FileNotFoundError(
                    f"Configuration file not found: {self.config_path}"
                )

            logger.info(f"Loading configuration from: {self.config_path}")

            with open(config_file, "r") as f:
                config = yaml.safe_load(f)

            required_sections = ["models", "plots", "filters", "styling"]
            for section in required_sections:
                if section not in config:
                    raise ValueError(
                        f"Missing required configuration section: {section}"
                    )

            logger.info("Configuration loaded successfully")
            return config
        else:
            return self.generate_auto_config()

    def filter_data_for_config(
        self, df: pd.DataFrame, model_config: Dict[str, Any]
    ) -> pd.DataFrame:
        """
        Filter dataframe for a specific model configuration.

        Args:
            df: Input dataframe
            model_config: Model configuration from config file

        Returns:
            Filtered dataframe
        """
        filtered = df.copy()

        if "model" in model_config:
            filtered = filtered[filtered["model"] == model_config["model"]]

        if "prompt_toks" in model_config:
            filtered = filtered[filtered["prompt toks"] == model_config["prompt_toks"]]
        if "output_toks" in model_config:
            filtered = filtered[filtered["output toks"] == model_config["output_toks"]]

        accelerator_filter = self.config["filters"]["accelerators"]
        if accelerator_filter:
            filtered = filtered[filtered["accelerator"].isin(accelerator_filter)]

        version_filter = self.config["filters"]["versions"]
        if version_filter:
            filtered = filtered[filtered["version"].isin(version_filter)]

        return filtered

    def generate_report(self) -> None:
        """
        Generate HTML report based on configuration.
        """
        logger.info("Generating HTML report")

        all_data = self.combined_df

        if all_data.empty:
            logger.error("No data available to plot")
            return

        if "version" not in all_data.columns:
            all_data["version"] = "N/A"
        all_data["version"] = all_data["version"].fillna("N/A").astype(str)

        if "replicas" not in all_data.columns:
            all_data["replicas"] = 1
        all_data["replicas"] = all_data["replicas"].fillna(1).astype(int)

        model_configs = self.config["models"]
        plot_configs = self.config["plots"]
        colors = self.config["styling"]["colors"]
        markers = self.config["styling"]["markers"]

        n_rows = len(plot_configs)
        n_cols = len(model_configs)

        # Create subplot titles with metric names
        subplot_titles = []
        for plot_config in plot_configs:
            for model_config in model_configs:
                better_text = (
                    "Higher is better"
                    if plot_config.get("higher_is_better", True)
                    else "Lower is better"
                )
                subplot_titles.append(
                    f"<b>{plot_config['y_label']}</b><br><sub>{better_text}</sub>"
                )

        fig = make_subplots(
            rows=n_rows,
            cols=n_cols,
            subplot_titles=subplot_titles,
            vertical_spacing=0.08,
            horizontal_spacing=0.08,
        )

        # Collect all configurations for consistent coloring
        # Don't filter by TP here, just show all TP values for the model
        all_configs = set()
        for model_config in model_configs:
            model_data = self.filter_data_for_config(all_data, model_config)
            if not model_data.empty:
                for cfg in model_data.groupby(
                    ["accelerator", "version", "TP", "replicas"]
                ).groups.keys():
                    all_configs.add(cfg)
            else:
                logger.warning(
                    f"No data found for model {model_config['model']} after filtering"
                )

        all_configs = sorted(list(all_configs))

        config_to_color = {}
        config_to_marker = {}
        for idx, cfg in enumerate(all_configs):
            accelerator, version, tp, replicas = cfg
            label = f"{accelerator} | {version} | TP={tp} | R={replicas}"
            config_to_color[label] = colors[idx % len(colors)]
            config_to_marker[label] = markers[idx % len(markers)]

        legend_entries = set()

        for row_idx, plot_config in enumerate(plot_configs, start=1):
            for col_idx, model_config in enumerate(model_configs, start=1):
                filtered_data = self.filter_data_for_config(all_data, model_config)

                if filtered_data.empty:
                    logger.warning(f"No data for {model_config['model']}")
                    continue

                filtered_data = filtered_data.sort_values(by=[plot_config["x_metric"]])

                for group_key, group_data in filtered_data.groupby(
                    ["accelerator", "version", "TP", "replicas"]
                ):
                    accelerator, version, tp, replicas = group_key
                    label = f"{accelerator} | {version} | TP={tp} | R={replicas}"

                    color = config_to_color[label]
                    marker = config_to_marker[label]

                    show_legend = label not in legend_entries
                    if show_legend:
                        legend_entries.add(label)

                    fig.add_trace(
                        go.Scatter(
                            x=group_data[plot_config["x_metric"]],
                            y=group_data[plot_config["y_metric"]],
                            mode="lines+markers",
                            name=label,
                            line=dict(color=color, width=2),
                            marker=dict(
                                size=8, symbol=marker, line=dict(width=1, color="white")
                            ),
                            showlegend=show_legend,
                            legendgroup=label,
                        ),
                        row=row_idx,
                        col=col_idx,
                    )

                xaxis_name = (
                    f"xaxis{(row_idx - 1) * n_cols + col_idx}"
                    if (row_idx - 1) * n_cols + col_idx > 1
                    else "xaxis"
                )
                yaxis_name = (
                    f"yaxis{(row_idx - 1) * n_cols + col_idx}"
                    if (row_idx - 1) * n_cols + col_idx > 1
                    else "yaxis"
                )

                fig.update_layout(
                    {
                        xaxis_name: {
                            "title": plot_config["x_label"],
                            "showgrid": True,
                            "gridwidth": 0.5,
                            "gridcolor": "lightgray",
                            "showline": True,
                            "linewidth": 1,
                            "linecolor": "black",
                            "mirror": True,
                            "type": "log"
                            if plot_config.get("log_x", False)
                            else "linear",
                        },
                        yaxis_name: {
                            "title": plot_config["y_label"],
                            "showgrid": True,
                            "gridwidth": 0.5,
                            "gridcolor": "lightgray",
                            "showline": True,
                            "linewidth": 1,
                            "linecolor": "black",
                            "mirror": True,
                            "type": "log"
                            if plot_config.get("log_y", False)
                            else "linear",
                        },
                    }
                )

        if n_cols == 1:
            plot_width = 1200
            left_margin = 120
        else:
            plot_width = 500 * n_cols
            left_margin = 120

        model_short_name = model_configs[0]["model"].split("/")[-1]
        versions_str = ", ".join(self.compare_versions)

        fig.update_layout(
            title={
                "text": (
                    f"<b>{model_short_name} Performance Report</b><br>"
                    f"<sub>Comparing versions: {versions_str} | "
                    f"Accelerator: {self.accelerator} | TP: {self.tp_size}</sub><br>"
                    f"<sub>Input Tokens: {model_configs[0]['prompt_toks']} | "
                    f"Output Tokens: {model_configs[0]['output_toks']}</sub>"
                ),
                "x": 0.5,
                "xanchor": "center",
                "font": {"size": 18},
                "y": 0.99,
                "yanchor": "top",
            },
            height=450 * n_rows,
            width=plot_width,
            plot_bgcolor="white",
            paper_bgcolor="white",
            font={"family": "Arial, sans-serif", "size": 11},
            margin=dict(t=150, l=left_margin, r=200, b=50),
            legend={
                "title": {"text": "<b>Configuration</b>"},
                "orientation": "v",
                "yanchor": "top",
                "y": 1,
                "xanchor": "left",
                "x": 1.01,
                "bordercolor": "black",
                "borderwidth": 1,
            },
            showlegend=True,
        )

        fig.write_html(self.output_html)
        logger.info(f"Report saved to {self.output_html}")
        logger.info(
            f"Report contains {n_rows} plot types × {n_cols} models = {n_rows * n_cols} total plots"
        )

    def process(self) -> None:
        """
        Execute the full benchmark processing workflow.

        Steps:
        1. Download consolidated CSV from S3
        2. Parse JSON benchmark file
        3. Merge data
        4. Load report configuration
        5. Generate HTML report
        """
        logger.info("Starting benchmark processing workflow")

        self.consolidated_df = self.download_s3_csv()
        self.new_data_df = self.parse_guidellm_json()
        self.combined_df = self.merge_data()
        self.config = self.load_config()
        self.generate_report()

        logger.info("Benchmark processing complete")

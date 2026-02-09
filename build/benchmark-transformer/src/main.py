#!/usr/bin/env python3
"""Benchmark Transformer - Post-processing pipeline for GuideLLM results.

This script transforms GuideLLM benchmark output through a 3-stage pipeline:
1. Generate PSAP payload (add metadata wrapper)
2. Generate CSV metrics file
3. Generate HTML visualization report (optional)

Usage:
    python main.py \
        --input /workspace/results/{UUID}/benchmark_output.json \
        --output-dir /workspace/results/{UUID} \
        --model "Qwen/Qwen3-0.6B" \
        --accelerator H200 \
        --version RHAIIS-3.2.3 \
        --tp 1 \
        --run-uuid abc123-def456
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from models import TransformConfig
from psap_generator import write_psap_payload
from csv_generator import write_csv
from visualization import generate_visualization_report

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("benchmark-transformer")


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Transform GuideLLM benchmark results into PSAP payload and CSV",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Required arguments
    parser.add_argument(
        "--input",
        required=True,
        help="Path to GuideLLM benchmark_output.json",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Output directory for generated files",
    )
    parser.add_argument(
        "--run-uuid",
        required=True,
        help="Pipeline run UUID for tracking",
    )
    parser.add_argument(
        "--model",
        required=True,
        help="Model name (e.g., Qwen/Qwen3-0.6B)",
    )
    parser.add_argument(
        "--accelerator",
        required=True,
        help="Accelerator type (e.g., H200, MI300X)",
    )
    parser.add_argument(
        "--version",
        required=True,
        help="Version identifier (e.g., RHAIIS-3.2.3)",
    )

    # Optional arguments
    parser.add_argument(
        "--tp",
        type=int,
        default=1,
        help="Tensor parallelism size (default: 1)",
    )
    parser.add_argument(
        "--deployment-image",
        default="",
        help="Deployment container image (e.g., registry.redhat.io/rhaiis/vllm-cuda-rhel9:3.2.3)",
    )
    parser.add_argument(
        "--vllm-args",
        nargs="*",
        default=[],
        help="vLLM arguments (e.g., --tensor-parallel-size=4)",
    )
    parser.add_argument(
        "--guidellm-data",
        default="",
        help="GuideLLM data profile (e.g., prompt_tokens=1000,output_tokens=1000)",
    )

    # Control flags
    parser.add_argument(
        "--skip-visualization",
        action="store_true",
        help="Skip HTML visualization generation",
    )
    parser.add_argument(
        "--skip-psap",
        action="store_true",
        help="Skip PSAP payload generation",
    )
    parser.add_argument(
        "--skip-csv",
        action="store_true",
        help="Skip CSV generation",
    )

    return parser.parse_args()


def main() -> int:
    """Main entry point."""
    args = parse_args()

    logger.info("=" * 60)
    logger.info("Benchmark Transformer")
    logger.info("=" * 60)
    logger.info(f"Input: {args.input}")
    logger.info(f"Output Dir: {args.output_dir}")
    logger.info(f"Run UUID: {args.run_uuid}")
    logger.info(f"Model: {args.model}")
    logger.info(f"Accelerator: {args.accelerator}")
    logger.info(f"Version: {args.version}")
    logger.info(f"TP: {args.tp}")
    logger.info("=" * 60)

    # Validate input file exists
    input_path = Path(args.input)
    if not input_path.exists():
        logger.error(f"Input file not found: {args.input}")
        return 1

    # Create output directory if needed
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load GuideLLM output
    try:
        with open(input_path) as f:
            guidellm_output = json.load(f)
        logger.info(f"Loaded GuideLLM output: {len(guidellm_output.get('benchmarks', []))} benchmarks")
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON: {e}")
        return 1

    # Create configuration
    config = TransformConfig(
        input_path=str(input_path),
        output_dir=str(output_dir),
        run_uuid=args.run_uuid,
        model_name=args.model,
        accelerator=args.accelerator,
        version=args.version,
        tp=args.tp,
        deployment_image=args.deployment_image,
        vllm_args=args.vllm_args,
        guidellm_data=args.guidellm_data,
        generate_visualization=not args.skip_visualization,
        generate_psap=not args.skip_psap,
        generate_csv=not args.skip_csv,
    )

    results = {
        "psap_path": None,
        "csv_path": None,
        "html_path": None,
    }

    # Step 1: Generate PSAP payload
    if config.generate_psap:
        logger.info("")
        logger.info("Step 1: Generating PSAP payload...")
        try:
            psap_path = write_psap_payload(guidellm_output, config)
            results["psap_path"] = str(psap_path)
            logger.info(f"PSAP payload: {psap_path}")
        except Exception as e:
            logger.error(f"PSAP generation failed: {e}")
            return 1
    else:
        logger.info("Step 1: Skipping PSAP generation")

    # Step 2: Generate CSV from PSAP
    if config.generate_csv:
        logger.info("")
        logger.info("Step 2: Generating CSV...")
        if results["psap_path"]:
            try:
                csv_path = write_csv(Path(results["psap_path"]), config)
                if csv_path:
                    results["csv_path"] = str(csv_path)
                    logger.info(f"CSV file: {csv_path}")
                else:
                    logger.warning("CSV generation produced no output")
            except Exception as e:
                logger.error(f"CSV generation failed: {e}")
                return 1
        else:
            logger.warning("Skipping CSV - no PSAP file available")
    else:
        logger.info("Step 2: Skipping CSV generation")

    # Step 3: Generate visualization report
    if config.generate_visualization:
        logger.info("")
        logger.info("Step 3: Generating visualization report...")
        try:
            html_path = generate_visualization_report(guidellm_output, config)
            if html_path:
                results["html_path"] = str(html_path)
                logger.info(f"HTML report: {html_path}")
            else:
                logger.info("Visualization report skipped (dependencies not available)")
        except Exception as e:
            logger.warning(f"Visualization generation failed (non-fatal): {e}")
    else:
        logger.info("Step 3: Skipping visualization generation")

    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("Transformation Complete")
    logger.info("=" * 60)
    logger.info(f"PSAP:  {results['psap_path'] or 'not generated'}")
    logger.info(f"CSV:   {results['csv_path'] or 'not generated'}")
    logger.info(f"HTML:  {results['html_path'] or 'not generated'}")
    logger.info("=" * 60)

    # Write results manifest for downstream tasks
    manifest_path = output_dir / "transform_results.json"
    with open(manifest_path, "w") as f:
        json.dump(results, f, indent=2)
    logger.info(f"Results manifest: {manifest_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

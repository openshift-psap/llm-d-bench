"""
Entry point for running the benchmark as a module: python -m run_benchmark
"""

import sys
from .run_benchmark import main

if __name__ == "__main__":
    sys.exit(main())

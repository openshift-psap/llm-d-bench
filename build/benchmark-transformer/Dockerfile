FROM python:3.11-slim

LABEL maintainer="llm-d-bench"
LABEL description="Benchmark Transformer - Post-processing for GuideLLM results"

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src/ /app/

# Set PYTHONPATH so imports work
ENV PYTHONPATH=/app

# Default command
ENTRYPOINT ["python", "/app/main.py"]

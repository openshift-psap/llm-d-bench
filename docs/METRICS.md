# System Metrics and Artifact Collection Guide

This guide covers the system metrics collection and artifact capture capabilities added to llm-d-bench.

## Overview

llm-d-bench now automatically collects:
- **System Metrics**: GPU, CPU, memory, and network metrics from Prometheus/Thanos
- **Pod Logs**: Complete logs from all containers
- **Kubernetes Manifests**: Rendered manifests and deployed state
- **Configuration**: All ConfigMaps used in the pipeline

All artifacts are stored in MLflow alongside benchmark results for reproducibility and analysis.

## Architecture

```
Pipeline Flow:
┌─────────────┐    ┌──────────────┐    ┌─────────────┐    ┌──────────────┐
│   Configs   │───▶│   Export     │───▶│   Deploy    │───▶│   Capture    │
│   Export    │    │   ConfigMaps │    │   Model     │    │   Manifests  │
└─────────────┘    └──────────────┘    └─────────────┘    └──────────────┘
                                                                │
                                                                ▼
┌─────────────┐    ┌──────────────┐    ┌─────────────┐    ┌──────────────┐
│   Metrics   │◀───│   Collect    │◀───│   Collect   │◀───│   Run        │
│   Analysis  │    │   Metrics    │    │   Artifacts │    │   Benchmark  │
└─────────────┘    └──────────────┘    └─────────────┘    └──────────────┘
```

## Quick Start

### 1. Deploy Grafana (One-time Setup)

```bash
# Deploy Grafana with pre-configured Thanos data source
oc apply -k infra/manifests/grafana/

# Create a route for external access
oc create route edge grafana --service=grafana -n grafana

# Get the URL
oc get route grafana -n grafana
```

### 2. Apply Metrics Profiles

```bash
# Apply default metrics collection profile
oc apply -k config/profiles/metrics/
```

### 3. Run a Benchmark

Metrics and artifacts are automatically collected when you run a benchmark with `MLFLOW_ENABLED=true`:

```bash
oc create -f pipelineruns/llm-d/your-benchmark.yaml -n llm-d-bench
```

## MLflow Artifacts Structure

After a benchmark completes, the following artifacts are available in MLflow:

```
artifacts/
├── manifests/
│   ├── rendered/
│   │   ├── manifests.yaml          # Helm-rendered Kubernetes manifests
│   │   └── values.yaml             # Patched Helm values
│   ├── deployed-state/
│   │   ├── deployments.yaml        # Actual deployed deployments
│   │   ├── pods.yaml              # Actual deployed pods
│   │   ├── services.yaml          # Services
│   │   ├── gateways.yaml          # Gateway resources
│   │   ├── httproutes.yaml        # HTTPRoutes
│   │   └── inferencepools.yaml    # InferencePools
│   └── configmaps/
│       ├── configmap-vllm.yaml
│       ├── configmap-deployment.yaml
│       ├── configmap-benchmark.yaml
│       └── configmap-epp.yaml
├── logs/
│   ├── <pod-name>_<container>.log  # Individual container logs
│   └── ...
├── metrics/
│   ├── metrics_summary.json        # Summary of collected metrics
│   └── tags.json                  # MLflow tags with metadata
└── reports/
    ├── benchmark_output.json
    └── benchmark_comparison.html
```

## Grafana Dashboard

### Accessing the Dashboard

1. Open Grafana URL (from route created above)
2. Navigate to Dashboards → LLM Benchmarks
3. Select your namespace and release name from the dropdowns

### Dashboard Variables

The dashboard includes template variables for filtering:

- **Namespace**: The OpenShift namespace (e.g., `llm-d-bench`)
- **Release Name**: The deployment release name (e.g., `llama-31-8b`)
- **MLflow Run ID**: Optional filter for specific runs

### Dashboard Panels

1. **Overview**: Summary statistics (active pods, avg GPU/CPU/memory)
2. **GPU Metrics**: 
   - GPU utilization over time
   - GPU memory usage (used/free)
3. **CPU & Memory**:
   - CPU usage by pod/container
   - Memory working set by pod/container
4. **Network**:
   - Network receive/transmit rates

## Prometheus Queries

The metrics collection task queries Prometheus/Thanos for:

### GPU Metrics (DCGM)
```promql
DCGM_FI_DEV_GPU_UTIL{namespace="$namespace", pod=~".*$release.*"}
DCGM_FI_DEV_FB_USED{namespace="$namespace", pod=~".*$release.*"}
DCGM_FI_DEV_FB_FREE{namespace="$namespace", pod=~".*$release.*"}
DCGM_FI_DEV_GPU_TEMP{namespace="$namespace", pod=~".*$release.*"}
DCGM_FI_DEV_POWER_USAGE{namespace="$namespace", pod=~".*$release.*"}
```

### CPU & Memory
```promql
rate(container_cpu_usage_seconds_total{namespace="$namespace", pod=~".*$release.*"}[5m])
container_memory_working_set_bytes{namespace="$namespace", pod=~".*$release.*"}
```

### Network
```promql
rate(container_network_receive_bytes_total{namespace="$namespace", pod=~".*$release.*"}[5m])
rate(container_network_transmit_bytes_total{namespace="$namespace", pod=~".*$release.*"}[5m])
```

## Metrics Configuration Profiles

Two profiles are provided:

### Default Profile (`metrics-collection-default`)
- Core system metrics only
- 15-second query step
- Quick collection
- Metrics: GPU util/memory, CPU, memory, network basics

### Detailed Profile (`metrics-collection-detailed`)
- Comprehensive metrics including vLLM metrics
- 5-second query step
- Longer collection time
- Additional metrics: GPU power, temperature, PCIe stats, vLLM cache metrics, scheduler metrics

### Using Profiles

Specify the metrics profile in your PipelineRun:

```yaml
params:
  - name: METRICS_CONFIG
    value: "metrics-collection-detailed"  # or "metrics-collection-default"
```

## Troubleshooting

### No Data in Grafana

1. **Check Grafana can access Prometheus**:
   ```bash
   oc logs -n grafana deployment/grafana
   ```

2. **Verify service account permissions**:
   ```bash
   oc auth can-i get pods -n openshift-monitoring --as=system:serviceaccount:grafana:grafana
   ```

3. **Test Prometheus query directly**:
   ```bash
   curl -k -H "Authorization: Bearer $(oc create token grafana -n grafana)" \
     https://thanos-querier.openshift-monitoring.svc:9091/api/v1/query?query=up
   ```

### Artifacts Not Uploaded to MLflow

1. **Check MLflow run ID was captured**:
   ```bash
   oc get pipelinerun <name> -n llm-d-bench -o yaml | grep mlflow-run-id
   ```

2. **Verify MLflow secrets are configured**:
   ```bash
   oc get secret mlflow-ui-auth -n llm-d-bench
   ```

3. **Check task logs**:
   ```bash
   tkn pipelinerun logs <name> -t collect-artifacts -n llm-d-bench
   ```

### Pod Logs Not Found

If pods are deleted before log collection:
- Artifacts task runs immediately after benchmark
- Logs are collected before cleanup
- Check task timeout settings if collection is slow

## Configuration Reference

### Collect System Metrics Task Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `MLFLOW_RUN_ID` | MLflow run ID to upload metrics to | Required |
| `NAMESPACE` | Target namespace | Required |
| `RELEASE_NAME` | Release name for pod filtering | Required |
| `BENCHMARK_START_TIME` | Start time in ISO8601 format | Required |
| `BENCHMARK_END_TIME` | End time in ISO8601 format | Required |
| `METRICS_CONFIG` | ConfigMap name with metrics queries | "" |
| `PROMETHEUS_URL` | Thanos/Prometheus URL | `https://thanos-querier.openshift-monitoring.svc:9091` |
| `QUERY_STEP` | Query step interval | `15s` |
| `GRAFANA_URL` | Grafana URL for dashboard links | "" |

### Collect Artifacts Task Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `NAMESPACE` | Target namespace | Required |
| `RELEASE_NAME` | Release name for pod filtering | Required |
| `MLFLOW_RUN_ID` | MLflow run ID to upload to | "" |
| `LOG_TAIL_LINES` | Number of log lines (`all` for complete logs) | `all` |
| `MLFLOW_TRACKING_URI` | MLflow tracking URI | "" |

## Best Practices

1. **Always enable MLflow** (`MLFLOW_ENABLED=true`) to ensure artifacts are stored
2. **Use descriptive release names** for easier filtering in Grafana
3. **Set appropriate query steps**: Use `15s` for quick benchmarks, `5s` for detailed analysis
4. **Monitor disk space**: Full pod logs can be large; ensure PVCs have sufficient space
5. **Clean up old runs**: Set MLflow artifact retention policies to manage storage

## Additional Resources

- [Grafana Documentation](https://grafana.com/docs/)
- [Prometheus Query Language](https://prometheus.io/docs/prometheus/latest/querying/basics/)
- [MLflow Tracking](https://mlflow.org/docs/latest/tracking.html)
- [OpenShift Monitoring](https://docs.openshift.com/container-platform/latest/monitoring/monitoring-overview.html)

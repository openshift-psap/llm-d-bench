# Grafana Deployment for llm-d-bench

This directory contains manifests for deploying Grafana with OpenShift monitoring integration.

## Overview

Grafana is deployed with:
- Pre-configured Thanos data source (for long-term metrics)
- Pre-configured Prometheus data source
- LLM benchmark dashboard support
- Persistent storage for dashboards and data

## Prerequisites

- OpenShift 4.14+
- OpenShift monitoring stack (Thanos/Prometheus)

## Deployment

```bash
oc apply -k infra/manifests/grafana/
```

Or manually:

```bash
oc apply -f namespace.yaml
oc apply -f pvc.yaml
oc apply -f rbac.yaml
oc apply -f datasources.yaml
oc apply -f deployment.yaml
oc apply -f service.yaml
```

## Accessing Grafana

### Using OpenShift Route (recommended)

```bash
oc create route edge grafana --service=grafana -n grafana
oc get route grafana -n grafana
```

### Port forwarding (for testing)

```bash
oc port-forward svc/grafana 3000:3000 -n grafana
# Access at http://localhost:3000
```

## Configuration

### Admin Credentials

By default, Grafana uses:
- Username: `admin`
- Password: `admin` (if no secret exists)

To set a custom password:

```bash
oc create secret generic grafana-admin-credentials \
  --from-literal=password=your-secure-password \
  -n grafana
```

### Data Sources

The deployment includes two pre-configured data sources:

1. **Thanos** (default): For long-term metrics storage
2. **Prometheus**: For real-time cluster metrics

Both use the Grafana service account token for authentication.

## Dashboards

Place custom dashboards in ConfigMaps:

```bash
oc create configmap llm-d-bench-dashboards \
  --from-file=llm-d-bench-dashboard.json \
  -n grafana
```

Dashboards are loaded from `/var/lib/grafana/dashboards/llm-d-bench/`.

## Troubleshooting

### Grafana pod stuck in pending

Check PVC status:
```bash
oc get pvc -n grafana
```

### No data in dashboards

1. Check data source connectivity:
   ```bash
   oc logs -n grafana deployment/grafana
   ```

2. Verify service account has permissions:
   ```bash
   oc auth can-i get pods -n openshift-monitoring --as=system:serviceaccount:grafana:grafana
   ```

3. Test Thanos query directly:
   ```bash
   curl -k -H "Authorization: Bearer $(oc create token grafana -n grafana)" \
     https://thanos-querier.openshift-monitoring.svc:9091/api/v1/query?query=up
   ```

## Notes

- Grafana uses the cluster's internal CA for TLS verification
- Bearer token is automatically rotated via projected volumes
- Dashboards persist across pod restarts via PVC

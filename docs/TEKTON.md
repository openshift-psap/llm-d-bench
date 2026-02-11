# Tekton components

## Tekton Dashboard

Install the latest release (OpenShift-compatible version)

```bash
kubectl apply --filename https://storage.googleapis.com/tekton-releases/dashboard/latest/release.yaml
```

Expose the Route:
```bash
# Create an OpenShift route for the dashboard service
oc expose service tekton-dashboard -n tekton-pipelines
```

Get the URL:

```bash
oc get route tekton-dashboard -n tekton-pipelines -o jsonpath='{.spec.host}'
```

**After you configure Tekton Results**, you need to patch the Dashboard to use the remote logs:
```bash
oc patch deployment tekton-dashboard -n tekton-pipelines --type=json -p='[
  {"op": "replace", "path": "/spec/template/spec/containers/0/args/1", "value": "--external-logs=http://tekton-results-api-service.tekton-pipelines.svc.cluster.local:8080"}

]'
```

## Tekton Results

Installing Tekton Results on OpenShift (Manual) with S3 Log Backend

### Prerequisites

- OpenShift cluster with Tekton Pipelines installed
- `oc` CLI authenticated with cluster-admin privileges
- An S3 bucket (AWS S3 or S3-compatible) for log storage

### 1. Create the TLS Secret

The API server requires a TLS certificate:

```bash
openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes \
  -subj "/CN=tekton-results-api-service.tekton-pipelines.svc.cluster.local"

oc create secret tls tekton-results-tls \
  -n tekton-pipelines \
  --cert=cert.pem \
  --key=key.pem
```

### 2. Create the PostgreSQL Secret

```bash
oc create secret generic tekton-results-postgres \
  -n tekton-pipelines \
  --from-literal=POSTGRES_USER=postgres \
  --from-literal=POSTGRES_PASSWORD=$(openssl rand -base64 20)
```

### 3. Download the Release Manifest

```bash
curl -LO "https://storage.googleapis.com/tekton-releases/results/previous/latest/release.yaml"
```

### 4. Configure S3 Log Storage in the ConfigMap

> **Important:** The API server reads its configuration from a single `config` key
> in the ConfigMap — it does **not** use individual data entries or environment
> variables injected via `secretKeyRef`. All S3 credentials must be set directly
> in the `config` blob.

In the `tekton-results-api-config` ConfigMap inside `release.yaml`, find the `config`
key and set the following values:

```
LOGS_API=true
LOGS_TYPE=S3
S3_BUCKET_NAME=<your-bucket>
S3_ENDPOINT=<your-s3-endpoint-or-empty-for-aws>
S3_REGION=<region>
S3_ACCESS_KEY_ID=<access-key>
S3_SECRET_ACCESS_KEY=<secret-key>
```

**Both `LOGS_API=true` and `LOGS_TYPE=S3` are required** — without `LOGS_API=true`
the Logs API endpoint is disabled and logs will not be pushed to S3.

> **Note:** `S3_REGION` is mandatory for AWS S3. `S3_ENDPOINT` is only required for
> S3-compatible services (MinIO, Ceph, IBM COS, etc.) — for AWS S3 the SDK resolves
> the endpoint automatically from the region. You can leave it empty.

Alternatively, you can patch the ConfigMap after applying the release manifest:

```bash
oc get configmap tekton-results-api-config -n tekton-pipelines -o json | \
  jq --arg bucket "<your-bucket>" \
     --arg endpoint "<your-s3-endpoint>" \
     --arg region "<region>" \
     --arg key "<access-key>" \
     --arg secret "<secret-key>" \
     '.data.config |= gsub("S3_BUCKET_NAME="; "S3_BUCKET_NAME="+$bucket) |
      .data.config |= gsub("S3_ENDPOINT=\n"; "S3_ENDPOINT="+$endpoint+"\n") |
      .data.config |= gsub("S3_REGION=\n"; "S3_REGION="+$region+"\n") |
      .data.config |= gsub("S3_ACCESS_KEY_ID=\n"; "S3_ACCESS_KEY_ID="+$key+"\n") |
      .data.config |= gsub("S3_SECRET_ACCESS_KEY=\n"; "S3_SECRET_ACCESS_KEY="+$secret+"\n") |
      .data.config |= gsub("LOGS_API=false"; "LOGS_API=true") |
      .data.config |= gsub("LOGS_TYPE=File"; "LOGS_TYPE=S3")' | \
  oc apply -f -
```

### 5. Enable Log Forwarding on the Watcher

By default, the watcher only stores result/record metadata. To have it also forward
pod logs to S3 via the Logs API, add the `-logs_api true` argument to the watcher
Deployment in `release.yaml`:

```yaml
# In the tekton-results-watcher Deployment, find containers[0].args and add:
args:
  - "-api_addr"
  - "$(TEKTON_RESULTS_API_SERVICE)"
  - "-auth_mode"
  - "$(AUTH_MODE)"
  - "-logs_api"
  - "true"
```

Or patch after applying the manifest:

```bash
oc patch deployment tekton-results-watcher -n tekton-pipelines --type=json -p='[
  {"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "-logs_api"},
  {"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "true"}
]'
```

> **This is the most commonly missed step.** Without `-logs_api true`, the watcher
> reconciles results and records but never pushes actual pod logs to the storage backend.

### 6. Fix Watcher RBAC for Logs API

The default `tekton-results-watcher` ClusterRole may be missing the `list` verb for
the `logs` resource, which causes `Unauthenticated` errors when the watcher calls `ListLogs`:

```bash
oc patch clusterrole tekton-results-watcher --type=json -p='[
  {"op": "replace", "path": "/rules/0/verbs", "value": ["create","get","list","update"]}
]'
```

### 7. Create a Privileged ServiceAccount for PostgreSQL

The built-in Bitnami PostgreSQL image requires `anyuid` SCC on OpenShift due to its
`fsGroup` and capability requirements:

```bash
oc create sa tekton-results-postgres -n tekton-pipelines
oc adm policy add-scc-to-user anyuid -z tekton-results-postgres -n tekton-pipelines
```

### 8. Modify the PostgreSQL StatefulSet in `release.yaml`

Find the `tekton-results-postgres` StatefulSet and apply the following changes:

1. Set the `serviceAccountName` to the newly created SA:

    ```yaml
    spec:
      template:
        spec:
          serviceAccountName: tekton-results-postgres
    ```

2. Remove the seccomp annotation if present (under `spec.template.metadata.annotations`):

    ```yaml
    # DELETE this line:
    container.seccomp.security.alpha.kubernetes.io/postgres: ...
    ```

3. Remove the `capabilities` block from the container's `securityContext` (under `spec.template.spec.containers[0].securityContext`):

    ```yaml
    # DELETE this block:
    capabilities:
      add:
        - NET_BIND_SERVICE
    ```

### 9. Apply

```bash
oc apply -f release.yaml
```

### 10. Verify

Check that all pods are running:

```bash
oc get pods -n tekton-pipelines | grep results

# Expected output:
# tekton-results-api-xxxxx        1/1   Running
# tekton-results-watcher-xxxxx    1/1   Running
# tekton-results-postgres-0       1/1   Running
```

Confirm the watcher has the `-logs_api` flag:

```bash
oc get deployment tekton-results-watcher -n tekton-pipelines \
  -o json | jq '.spec.template.spec.containers[0].args'
```

Confirm the API server has the S3 config:

```bash
oc get configmap tekton-results-api-config -n tekton-pipelines \
  -o json | jq -r '.data.config' | grep -E "S3_|LOGS_"
```

Run a PipelineRun/TaskRun and check your S3 bucket for log objects. You can also
check the watcher logs for log-related activity:

```bash
oc logs -n tekton-pipelines deployment/tekton-results-watcher | grep -iE "log|s3|upload"
```

### Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| S3 bucket empty, watcher reconciles OK | Missing `-logs_api true` on watcher | Step 5 |
| `Unauthenticated` on `ListLogs` in API logs | Watcher ClusterRole missing `list` for `logs` | Step 6 |
| S3 values empty in config | Used `secretKeyRef` env vars instead of `config` blob | Step 4 |
| PostgreSQL pod stuck in `Pending`/`CreateContainerConfigError` | OpenShift SCC rejects fsGroup/capabilities | Steps 7-8 |
| `LOGS_API=false` in config | Default value not overridden | Step 4 |

## Tekton Logs Proxy (Dashboard Integration with S3)

### Why It's Needed

When Tekton Results is configured with `LOGS_TYPE=S3`, the Tekton Dashboard cannot directly fetch logs because the dashboard's `--external-logs` parameter expects a specific proxy API format (`/<namespace>/<pod>/<container>`) that Tekton Results with S3 storage doesn't provide. The dashboard shows **"Unable to fetch log"** even though logs are successfully stored in S3.

The **[tekton-logs-proxy](https://github.com/albertoperdomo2/tekton-logs-proxy)** is a lightweight Node.js service that bridges the Tekton Dashboard and S3-stored logs by:
- Querying the Kubernetes API to find TaskRuns by pod name
- Fetching log files from S3
- Filtering logs by individual step (parsing `[step-name]` prefixes)
- Serving logs in the format the dashboard expects

### Deployment

```bash
# 1. Create namespace and S3 secret
oc create namespace tekton-logs-proxy
oc create secret generic tekton-results-s3-creds \
  -n tekton-logs-proxy \
  --from-literal=S3_BUCKET_NAME=your-bucket \
  --from-literal=S3_REGION=us-east-1 \
  --from-literal=S3_ACCESS_KEY_ID=your-key \
  --from-literal=S3_SECRET_ACCESS_KEY=your-secret

# 2. Deploy the proxy
oc apply -f https://raw.githubusercontent.com/albertoperdomo2/tekton-logs-proxy/main/k8s/deployment.yaml

# 3. Grant RBAC permissions to read TaskRuns
oc create clusterrole tekton-logs-proxy-reader \
  --verb=get,list \
  --resource=taskruns.tekton.dev

oc create clusterrolebinding tekton-logs-proxy-reader-binding \
  --clusterrole=tekton-logs-proxy-reader \
  --serviceaccount=tekton-logs-proxy:tekton-logs-proxy

# 4. Configure Tekton Dashboard to use the proxy
oc patch deployment tekton-dashboard -n tekton-pipelines --type json -p '[{
  "op": "add",
  "path": "/spec/template/spec/containers/0/args/-",
  "value": "--external-logs=http://tekton-logs-proxy.tekton-logs-proxy.svc.cluster.local:8080"
}]'
```

### Verification

Check that the proxy is running and the dashboard can fetch logs:

```bash
oc get pods -n tekton-logs-proxy
oc logs -n tekton-logs-proxy deployment/tekton-logs-proxy
```

Open the Tekton Dashboard in your browser, navigate to a completed PipelineRun or TaskRun, and click on individual task steps. Each step should now display its own filtered logs from S3.

**For troubleshooting, advanced configuration, and more details, see the [tekton-logs-proxy repository](https://github.com/albertoperdomo2/tekton-logs-proxy).**

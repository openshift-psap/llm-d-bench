# Tekton Results Setup Guide

This guide covers installing and configuring Tekton Results with S3 log storage for long-term benchmark result persistence in llm-d-bench.

## Overview

Tekton Results provides long-term storage for Tekton CI/CD workload history, separating result storage from the Pipeline controller. This allows you to:

- **Free etcd resources**: Completed PipelineRuns and TaskRuns can be cleaned up from the cluster while their data remains queryable.
- **Query historical data**: Filter and search past benchmark runs using a gRPC/REST API with CEL-based filtering.
- **Store logs durably**: Persist task logs in S3-compatible storage instead of relying on pod log retention.
- **Group related workloads**: Bundle related TaskRuns and PipelineRuns into logical Result groups.

Tekton Results is composed of three components:

1. **API Server**: A gRPC/REST API backed by PostgreSQL for storing Results and Records.
2. **Watcher**: A controller that watches TaskRun/PipelineRun completions and reports them to the API.
3. **Retention Policy Agent**: Manages data lifecycle by deleting older records from the database.

**How it works with llm-d-bench**: Once installed, the Watcher automatically captures all PipelineRun and TaskRun data from the cluster. No changes to existing pipelines or tasks are required.

## Prerequisites

- Tekton Pipelines v0.50+ (already a llm-d-bench prerequisite)
- `kubectl` or `oc` CLI
- `openssl` (for TLS certificate generation)
- AWS CLI (for S3 bucket and IAM user setup)
- S3-compatible object storage (AWS S3, MinIO, Ceph)

## Secret Templates

llm-d-bench provides example templates for all Tekton Results secrets in [config/cluster/secrets/](../config/cluster/secrets/):

| Template | Secret Name | Purpose |
|---|---|---|
| `tekton-results-postgres.example.yaml` | `tekton-results-postgres` | PostgreSQL database credentials |
| `tekton-results-tls.example.yaml` | `tekton-results-tls` | TLS certificate for the API server |
| `tekton-results-s3-creds.example.yaml` | `tekton-results-s3-creds` | S3 credentials for log storage (optional) |

All secrets are created in the `tekton-pipelines` namespace (where Tekton Results runs).

## Installation

### 1. Create the PostgreSQL Password Secret

Tekton Results ships with a bundled PostgreSQL instance. You must create a database password secret before installing:

```bash
kubectl create secret generic tekton-results-postgres \
  --namespace=tekton-pipelines \
  --from-literal=POSTGRES_USER=postgres \
  --from-literal=POSTGRES_PASSWORD=$(openssl rand -base64 20)
```

Alternatively, use the provided template:

```bash
cp config/cluster/secrets/tekton-results-postgres.example.yaml \
   config/cluster/secrets/tekton-results-postgres.yaml
vim config/cluster/secrets/tekton-results-postgres.yaml
oc apply -f config/cluster/secrets/tekton-results-postgres.yaml
```

**Note**: For external PostgreSQL databases, refer to the [upstream documentation](https://github.com/tektoncd/results/blob/main/docs/external-database.md).

### 2. Generate TLS Certificate

The API server requires a TLS certificate. Generate a self-signed certificate:

```bash
openssl req -x509 \
  -newkey rsa:4096 \
  -keyout key.pem \
  -out cert.pem \
  -days 365 \
  -nodes \
  -subj "/CN=tekton-results-api-service.tekton-pipelines.svc.cluster.local" \
  -addext "subjectAltName = DNS:tekton-results-api-service.tekton-pipelines.svc.cluster.local"
```

Create the TLS secret:

```bash
kubectl create secret tls tekton-results-tls \
  --namespace=tekton-pipelines \
  --cert=cert.pem \
  --key=key.pem
```

Clean up local cert files:

```bash
rm -f cert.pem key.pem
```

A template is also available at `config/cluster/secrets/tekton-results-tls.example.yaml` for reference.

### 3. Install Tekton Results

Install the latest release:

```bash
kubectl apply -f https://storage.googleapis.com/tekton-releases/results/latest/release.yaml
```

Or install a specific version:

```bash
export RESULTS_VERSION="v0.12.1"
kubectl apply -f "https://storage.googleapis.com/tekton-releases/results/previous/${RESULTS_VERSION}/release.yaml"
```

### 4. Verify Installation

```bash
kubectl get pods -n tekton-pipelines | grep tekton-results
```

You should see the API server and watcher pods running:

```
tekton-results-api-...       1/1     Running   0          1m
tekton-results-watcher-...   1/1     Running   0          1m
```

## Configuring S3 Log Storage

By default, Tekton Results stores logs on the local filesystem. For production use, configure S3-compatible storage for durable log persistence.

### S3 Requirements

| Requirement | Description |
|---|---|
| AWS Account | AWS account with IAM permissions (or S3-compatible service) |
| S3 Bucket | Private bucket dedicated to Tekton Results logs |
| IAM User | Dedicated user with programmatic access (access key + secret) |
| IAM Policy | Permissions: `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject`, `s3:ListBucket` |
| Region | AWS region where the bucket resides (e.g., `us-east-1`) |
| S3 Endpoint | Custom endpoint URL (only for MinIO/Ceph; leave empty for AWS S3) |

### Creating the S3 Bucket and IAM User

Use the AWS CLI to create the required infrastructure. Replace `tekton-results-logs` with your preferred bucket name throughout.

#### Step 1: Create a Private S3 Bucket

```bash
# Create the bucket
aws s3api create-bucket \
  --bucket tekton-results-logs \
  --region us-east-1

# Block all public access
aws s3api put-public-access-block \
  --bucket tekton-results-logs \
  --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
```

Verify the bucket was created:

```bash
aws s3api head-bucket --bucket tekton-results-logs
```

**Note**: For regions other than `us-east-1`, add the `--create-bucket-configuration` flag:

```bash
aws s3api create-bucket \
  --bucket tekton-results-logs \
  --region eu-west-1 \
  --create-bucket-configuration LocationConstraint=eu-west-1
```

#### Step 2: Create a Dedicated IAM User

```bash
aws iam create-user --user-name tekton-results-s3
```

#### Step 3: Create an IAM Policy

Create a least-privilege policy scoped to the bucket:

```bash
aws iam create-policy \
  --policy-name TektonResultsS3Access \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": [
          "s3:PutObject",
          "s3:GetObject",
          "s3:DeleteObject"
        ],
        "Resource": "arn:aws:s3:::tekton-results-logs/*"
      },
      {
        "Effect": "Allow",
        "Action": [
          "s3:ListBucket"
        ],
        "Resource": "arn:aws:s3:::tekton-results-logs"
      }
    ]
  }'
```

Note the `Policy.Arn` from the output. It will be in the format `arn:aws:iam::<ACCOUNT_ID>:policy/TektonResultsS3Access`.

#### Step 4: Attach the Policy to the User

```bash
aws iam attach-user-policy \
  --user-name tekton-results-s3 \
  --policy-arn arn:aws:iam::<ACCOUNT_ID>:policy/TektonResultsS3Access
```

Replace `<ACCOUNT_ID>` with your AWS account ID. You can retrieve it with:

```bash
aws sts get-caller-identity --query Account --output text
```

#### Step 5: Create Access Keys

```bash
aws iam create-access-key --user-name tekton-results-s3
```

Save the `AccessKeyId` and `SecretAccessKey` from the output. These are used in the next section.

**Important**: The secret access key is only shown once. Store it securely.

### Creating the S3 Credentials Secret

Using the template:

```bash
# Copy the template
cp config/cluster/secrets/tekton-results-s3-creds.example.yaml \
   config/cluster/secrets/tekton-results-s3-creds.yaml

# Edit with your credentials
vim config/cluster/secrets/tekton-results-s3-creds.yaml

# Apply the secret
oc apply -f config/cluster/secrets/tekton-results-s3-creds.yaml
```

Or create directly from the command line:

```bash
oc create secret generic tekton-results-s3-creds \
  --namespace=tekton-pipelines \
  --from-literal=S3_ACCESS_KEY_ID=<your-access-key-id> \
  --from-literal=S3_SECRET_ACCESS_KEY=<your-secret-access-key> \
  --from-literal=S3_BUCKET_NAME=tekton-results-logs \
  --from-literal=S3_REGION=us-east-1 \
  --from-literal=S3_ENDPOINT=
```

Templates are located in: [config/cluster/secrets/](../config/cluster/secrets/)

### Patching the Tekton Results API Configuration

Enable S3 log storage by patching the `tekton-results-api-config` ConfigMap:

```bash
kubectl patch configmap tekton-results-api-config \
  --namespace=tekton-pipelines \
  --type merge \
  -p '{
    "data": {
      "LOGS_API": "true",
      "LOGS_TYPE": "S3",
      "S3_BUCKET_NAME": "tekton-results-logs",
      "S3_REGION": "us-east-1",
      "S3_ACCESS_KEY_ID": "<your-access-key-id>",
      "S3_SECRET_ACCESS_KEY": "<your-secret-access-key>",
      "S3_ENDPOINT": "",
      "S3_HOSTNAME_IMMUTABLE": "false"
    }
  }'
```

Restart the API server to pick up the changes:

```bash
kubectl rollout restart deployment/tekton-results-api -n tekton-pipelines
kubectl rollout status deployment/tekton-results-api -n tekton-pipelines
```

**For MinIO or other S3-compatible storage**, set `S3_ENDPOINT` to the service URL and `S3_HOSTNAME_IMMUTABLE` to `"true"`:

```bash
kubectl patch configmap tekton-results-api-config \
  --namespace=tekton-pipelines \
  --type merge \
  -p '{
    "data": {
      "LOGS_API": "true",
      "LOGS_TYPE": "S3",
      "S3_BUCKET_NAME": "tekton-results-logs",
      "S3_REGION": "us-east-1",
      "S3_ACCESS_KEY_ID": "<your-access-key-id>",
      "S3_SECRET_ACCESS_KEY": "<your-secret-access-key>",
      "S3_ENDPOINT": "https://minio.example.com",
      "S3_HOSTNAME_IMMUTABLE": "true"
    }
  }'
```

## Querying Results

Once Tekton Results is running, all PipelineRun and TaskRun completions are automatically captured. You can query them using the REST API or the `tkn-results` CLI plugin.

### REST API

```bash
# Get a service account token
TOKEN=$(kubectl create token tekton-results-watcher -n tekton-pipelines)

# Port-forward the API server
kubectl port-forward -n tekton-pipelines service/tekton-results-api-service 8080:8080 &

# List all results in the llm-d-bench namespace
curl -ks \
  -H "Authorization: Bearer ${TOKEN}" \
  "https://localhost:8080/apis/results.tekton.dev/v1alpha2/parents/llm-d-bench/results"

# Filter for failed PipelineRuns
curl -ks \
  -H "Authorization: Bearer ${TOKEN}" \
  --data-urlencode "filter=summary.status != SUCCESS" \
  "https://localhost:8080/apis/results.tekton.dev/v1alpha2/parents/llm-d-bench/results"
```

### tkn-results CLI Plugin (Optional)

Install the `tkn-results` plugin for easier querying:

```bash
# List results in the llm-d-bench namespace
tkn results list llm-d-bench

# List records with filtering
tkn results records list "llm-d-bench/results/-" \
  --filter="data_type == 'PIPELINE_RUN'"
```

For full API documentation, see the [Tekton Results API reference](https://tekton.dev/docs/results/api/).

## Troubleshooting

### API Server Not Running

**Symptoms:**
- `kubectl get pods -n tekton-pipelines` shows no `tekton-results-api` pod
- Pod in CrashLoopBackOff

**Solutions:**

1. **Check prerequisites were created:**
   ```bash
   kubectl get secret tekton-results-postgres -n tekton-pipelines
   kubectl get secret tekton-results-tls -n tekton-pipelines
   ```

2. **Check API server logs:**
   ```bash
   kubectl logs -n tekton-pipelines deployment/tekton-results-api
   ```

3. **Verify the release was applied:**
   ```bash
   kubectl get deployment -n tekton-pipelines | grep tekton-results
   ```

### Database Connection Errors

**Symptoms:**
- API server logs show `connection refused` to PostgreSQL
- Watcher unable to store results

**Solutions:**

1. **Check PostgreSQL pod:**
   ```bash
   kubectl get pods -n tekton-pipelines | grep postgres
   kubectl logs -n tekton-pipelines statefulset/tekton-results-postgres
   ```

2. **Verify database secret:**
   ```bash
   kubectl get secret tekton-results-postgres -n tekton-pipelines -o jsonpath='{.data.POSTGRES_USER}' | base64 -d
   ```

### S3 Upload Failures

**Symptoms:**
- Results are stored but logs are missing
- API server logs show S3 errors (`Access Denied`, `NoSuchBucket`)

**Solutions:**

1. **Verify S3 configuration in ConfigMap:**
   ```bash
   kubectl get configmap tekton-results-api-config -n tekton-pipelines -o yaml | grep -E 'LOGS_|S3_'
   ```

2. **Check bucket exists and is accessible:**
   ```bash
   aws s3 ls s3://tekton-results-logs/ --region us-east-1
   ```

3. **Verify IAM permissions:**
   ```bash
   aws iam list-attached-user-policies --user-name tekton-results-s3
   aws iam get-policy-version \
     --policy-arn arn:aws:iam::<ACCOUNT_ID>:policy/TektonResultsS3Access \
     --version-id v1
   ```

4. **Test S3 access with the credentials:**
   ```bash
   AWS_ACCESS_KEY_ID=<key> AWS_SECRET_ACCESS_KEY=<secret> \
     aws s3 ls s3://tekton-results-logs/ --region us-east-1
   ```

5. **For MinIO/Ceph:** Ensure `S3_ENDPOINT` and `S3_HOSTNAME_IMMUTABLE=true` are set in the ConfigMap.

### TLS Certificate Issues

**Symptoms:**
- Watcher logs show TLS handshake errors
- API server fails to start with certificate errors

**Solutions:**

1. **Verify TLS secret exists:**
   ```bash
   kubectl get secret tekton-results-tls -n tekton-pipelines
   ```

2. **Check certificate validity:**
   ```bash
   kubectl get secret tekton-results-tls -n tekton-pipelines -o jsonpath='{.data.tls\.crt}' | \
     base64 -d | openssl x509 -noout -dates -subject
   ```

3. **Regenerate if expired:** Follow [Step 2](#2-generate-tls-certificate) again and restart the API server:
   ```bash
   kubectl delete secret tekton-results-tls -n tekton-pipelines
   # Recreate the secret (see Step 2)
   kubectl rollout restart deployment/tekton-results-api -n tekton-pipelines
   ```

## Best Practices

1. **Use S3 log storage for production** to avoid data loss from pod eviction or node failures
2. **Set `MAX_RETENTION`** in the ConfigMap to control data lifecycle and prevent unbounded storage growth
3. **Monitor PostgreSQL storage** usage if using the bundled database
4. **Use proper TLS certificates** from a trusted CA for production deployments (not self-signed)
5. **Scope IAM policies** to the minimum required permissions (least privilege)
6. **Rotate access keys** periodically for the dedicated IAM user
7. **Enable `LOGS_API`** to make logs queryable through the Results API

# llm-d-bench

Automated [llm-d](https://llm-d.ai/) inference benchmarking on OpenShift with optional MLflow tracking and GitHub Actions integration, by using [GuideLLM](https://github.com/vllm-project/guidellm).

> This might work with any other LLM endpoint but has only been tested with `llm-d` endpoints.

This repo can handle downstream llm-d deployment (distributed inference through `LLInferenceService` via RHOAI 3.0), but infrastructure provisioning is not yet fully automated and it may require manual adjustments. See `infra/manifests/{rhoai,rhcl}`.

## Quick Setup

This project expects the following to be installed and correctly configured when using the provided `infra/`: 

  - [Reflector](https://github.com/emberstack/kubernetes-reflector) - Secret and ConfigMap mirroring across namespaces, can be omitted if the user manually creates the secrets in each namespace.
  - Red Hat OpenShift AI 3.0 requirements, refer to the official documents.

The secrets needed to launch a benchmark can be created via CLI: 

```bash
# HuggingFace Token Secret - Download models
oc create secret generic huggingface-token \
  --from-literal=HF_CLI_TOKEN=<your-huggingface-token> \
  -n <namespace>

# MLFlow Auth (required when mlflow.enabled: true) - Auth to MLFLow API
oc create secret generic mlflow-auth \
  --from-literal=admin-username=<username> \
  --from-literal=admin-password=<password> \
  -n <namespace>

# MLFlow s3 credentials (required when mlflow.enabled: true) - Artifacts logging to s3
oc create secret generic mlflow-s3-creds \
  --from-literal=AWS_ACCESS_KEY_ID=<access-key> \
  --from-literal=AWS_SECRET_ACCESS_KEY=<secret-key> \
  --from-literal=bucket-name=<bucket-name> \
  --from-literal=region=<region> \
  -n <namespace>
```

### Deploy Infrastructure (Optional)

> [!NOTE]
> llm-d-bench can be used without deploying this infra, but it is advised for CI/CD integration or experiment tracking, among others.

The deployment of the experiments infrastructure is completely optional and it is inteded to be a persistent environment for automated benchmarking. The infrastructure is composed by MLFlow, Self Hosted GitHub Action Runners and Kueue with MultiCluster capabilities.

In order to deploy it, create the necessary secrets within `infra/manifests/{mlflow,github-runners,kueue}` and then simply run `oc apply -k .` from the `infra/` dir.

Other manifests for deploying RHOAI and configuring Distributed Inference can be found inside `infra/` too.

#### Running Benchmarks Via Helmfile

> Needs building the benchmark image in the given namespace. See [Build and Push Custom Guidellm Image using OpenShift Builds](./build/README.md)

> [!WARNING]
> If using MLFlow, the user is responsible for creating the needed secrets in the appropriate namespace and configuring the given experiment.

Helmfile deployment must be run from within the `llm-d-bench/` directory. It uses environments to manage different experiment configurations by merging the base `values.yaml` with experiment-specific YAML files.

**Downstream Deployment** (using existing llm-d endpoint):
```bash
cd llm-d-bench
helmfile -e llama-4-1k-1k install
```

**Upstream Deployment** (deploys llm-d infrastructure, scheduler, and model service):
```bash
cd llm-d-bench
helmfile -e llama-4-1k-1k --set upstream=true install
```

**Preview Configuration** (test without deploying):
```bash
cd llm-d-bench
helmfile -e llama-4-1k-1k --set upstream=true template
```

> [!NOTE]
> The user is responsible for ensuring the infrastructure is correctly set up for each deployment type. Upstream deployment requires appropriate cluster resources and permissions. See `helmfile.yaml.gotmpl` for environment definitions and available experiments.

#### Runing Benchmarks Via GitHub Actions (if `infra` deployed)

> Needs building the benchmark image in the given namespace. See [Build and Push Custom Guidellm Image using OpenShift Builds](./build/README.md) and GHA setup.

For more information, refer to the `.github/` directory.

```
# Comment on any PR:
/benchmark qwen-0.6b-baseline

# With parameter overrides:
/benchmark qwen-0.6b-baseline
benchmark.maxSeconds=600
```

## Adding Benchmarks

See [`llm-d-bench/ADDING_BENCHMARKS.md`](llm-d-bench/ADDING_BENCHMARKS.md) for adding new benchmark tools.

**Quick summary:**
1. Add benchmark implementation to `llm-d-bench/templates/benchmarks/<tool-name>/`
2. Create experiment config in `llm-d-bench/experiments/`
3. Trigger via `/benchmark <experiment-name>` in PR comments or manually via CLI

For new experiments, add them in `llm-d-bench/experiments`. **Experiment names cannot include `.` for security reasons.**

## Results

- **MLflow** - Experiments tracked if `mlflow.enabled=true` and other config values.
- **PVC** - If `mlflow.enabled=false` (default), benchmark results will be in a PVC named `<benchmark name>-results`.

## Utils

There is a collection of utility scripts in the `utils/` dirs. None is mandatory to use but they can come in handy.
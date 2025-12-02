# llm-d-bench

Automated [llm-d](https://llm-d.ai/) inference benchmarking on OpenShift with MLflow tracking and GitHub Actions integration, by using [GuideLLM](https://github.com/vllm-project/guidellm).

> This might work with any other LLM endpoint but has only been tested with `llm-d` endpoints.

  
This repo does can handle llm-d deployment, but infrastructure provisioning is not yet fully automated, so RHOAI setup for Distributed Inference is expected to be taken care by the user.

## Quick Setup

This project expects the following to be installed and correctly configured when using the provided `infra/`: 

  - [Reflector](https://github.com/emberstack/kubernetes-reflector) - Secret and ConfigMap mirroring across namespaces, can be omitted if the user manually creates the secrets in each namespace.

### Deploy Infrastructure (Optional)

> [!NOTE]
> llm-d-bench can be used without deploying this infra, but it is advised for CI/CD integration or experiment tracking, among others.

The deployment of the experiments infrastructure is completely optional and it is inteded to be a persistent environment for automated benchmarking. The infrastructure is composed by MLFlow, Self Hosted GitHub Action Runners and Kueue with MultiCluster capabilities.

In order to deploy it, create the necessary secrets within `infra/` for each component and then simply run `oc apply -k .` from the infrastructure dir.

Other manifests for deploying RHOAI and configuring Distributed Inference can be found inside `infra/` too.

#### Runing Benchmarks Via GitHub Actions (if `infra` deployed)

> Needs building the benchmark image in the given namespace. See [Build and Push Custom Guidellm Image using OpenShift Builds](./build/README.md) and GHA setup.

```
# Comment on any PR:
/benchmark qwen-0.6b-baseline

# With parameter overrides:
/benchmark qwen-0.6b-baseline
benchmark.maxSeconds=600
```

#### Runing Benchmarks Via Helm
> Needs building the benchmark image in the given namespace. See [Build and Push Custom Guidellm Image using OpenShift Builds](./build/README.md)

> [!WARNING]
> If using MLFlow, the user is responsible for creating the needed secrets in the appropriate namespace and configuring the given experiment.

```bash
helm install <your_deployment_name> ./llm-d-bench \
  -f llm-d-bench/experiments/qwen-0.6b-baseline.yaml \
  -n <your_namespace>
```

## Adding Benchmarks

See [`llm-d-bench/ADDING_BENCHMARKS.md`](llm-d-bench/ADDING_BENCHMARKS.md) for adding new benchmark tools.

**Quick summary:**
1. Add benchmark implementation to `llm-d-bench/templates/benchmarks/<tool-name>/`
2. Create experiment config in `llm-d-bench/experiments/`
3. Trigger via `/benchmark <experiment-name>` in PR comments

For new experiments, add them in `llm-d-bench/experiments`.

> [!NOTE]
> Experiment names cannot include `.` for security reasons.

## Results

- **MLflow** - Experiments tracked if `mlflow.enabled=True` and other config values.
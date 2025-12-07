#!/bin/bash
set -e

MODEL_NAME="$1"
PVC_NAME="$3"
NAMESPACE="${NAMESPACE:-downstream-llm-d}"
SECRET_NAME="${SECRET_NAME:-huggingface-token}"
SECRET_KEY="${SECRET_KEY:-HF_CLI_TOKEN}"

if [ -z "$MODEL_NAME" ] || [ -z "$PVC_NAME" ]; then
    echo "Usage: $0 <model-name> --pvc <pvc-name>"
    echo "Example: $0 meta-llama/Llama-3.1-8B --pvc models-storage"
    exit 1
fi

MODEL_SANITIZED=$(echo "$MODEL_NAME" | tr '/' '-')
SUBPATH="models/$MODEL_SANITIZED"
POD_NAME="dl-$(date +%s)"

trap "oc delete pod $POD_NAME -n $NAMESPACE --ignore-not-found=true 2>/dev/null" EXIT INT TERM

echo "Downloading $MODEL_NAME to $PVC_NAME/$SUBPATH"

oc apply -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: $POD_NAME
  namespace: $NAMESPACE
spec:
  restartPolicy: Never
  containers:
  - name: downloader
    image: python:3.11-slim
    command: ["/bin/bash", "-c"]
    args:
    - |
      export HOME=/tmp
      export PATH="/tmp/.local/bin:\$PATH"

      pip install --no-cache-dir -q huggingface-hub
      hf auth login --token "\$HF_TOKEN"
      hf download $MODEL_NAME --local-dir /mnt/models/$SUBPATH

      echo "Download complete!"
    env:
    - name: HF_TOKEN
      valueFrom:
        secretKeyRef:
          name: $SECRET_NAME
          key: $SECRET_KEY
    volumeMounts:
    - name: models
      mountPath: /mnt/models
    resources:
      requests:
        memory: 2Gi
        cpu: "1"
      limits:
        memory: 4Gi
        cpu: "2"
  volumes:
  - name: models
    persistentVolumeClaim:
      claimName: $PVC_NAME
EOF

echo "Waiting for download..."
oc wait --for=condition=Ready pod/$POD_NAME -n $NAMESPACE --timeout=300s 2>/dev/null || true
oc logs -f $POD_NAME -n $NAMESPACE

if oc get pod $POD_NAME -n $NAMESPACE -o jsonpath='{.status.phase}' | grep -q "Succeeded"; then
    echo ""
    echo "✓ Model downloaded to: pvc://$PVC_NAME/$SUBPATH"
    echo ""
    echo "Use in LLMInferenceService:"
    echo "  spec.model.uri: pvc://$PVC_NAME/$SUBPATH"
else
    echo "✗ Download failed"
    exit 1
fi
{{/*
Expand the name of the chart.
*/}}
{{- define "llm-d-bench.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "llm-d-bench.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "llm-d-bench.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "llm-d-bench.labels" -}}
helm.sh/chart: {{ include "llm-d-bench.chart" . }}
{{ include "llm-d-bench.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- with .Values.labels }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "llm-d-bench.selectorLabels" -}}
app.kubernetes.io/name: {{ include "llm-d-bench.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Get the namespace
*/}}
{{- define "llm-d-bench.namespace" -}}
{{- default .Release.Namespace .Values.global.namespace }}
{{- end }}

{{/*
Get the PVC name
*/}}
{{- define "llm-d-bench.pvcName" -}}
{{- .Values.pvc.name | default (printf "%s-pvc" (include "llm-d-bench.fullname" .)) }}
{{- end }}

{{/*
Benchmark job name
*/}}
{{- define "llm-d-bench.benchmarkJobName" -}}
{{- .Values.benchmark.name | default (printf "%s-benchmark" (include "llm-d-bench.fullname" .)) }}
{{- end }}

{{/*
Generate a standardized, DNS-compliant name from the Model ID.
Example: "Qwen/Qwen3-0.6B" -> "qwen-qwen3-06b"
Logic: Lowercase -> Replace '/' with '-' -> Remove '.'
*/}}
{{- define "model.serviceName" -}}
{{- .Values.benchmark.model | lower | replace "/" "-" | replace "." "" | trimSuffix "-" | trunc 42 -}}
{{- end -}}

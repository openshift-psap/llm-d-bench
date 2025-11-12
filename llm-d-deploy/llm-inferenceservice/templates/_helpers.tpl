{{- define "llm-inferenceservice.modelShortName" -}}
{{- if contains "/" .Values.model.name }}
{{- $parts := split "/" .Values.model.name }}
{{- $parts._1 }}
{{- else }}
{{- .Values.model.name }}
{{- end }}
{{- end }}

{{- define "llm-inferenceservice.fullname" -}}
{{- include "llm-inferenceservice.modelShortName" . | replace "." "" | lower }}-{{ .Values.role }}
{{- end }}

{{- define "llm-inferenceservice.basename" -}}
{{- include "llm-inferenceservice.modelShortName" . | replace "." "" | lower }}
{{- end }}

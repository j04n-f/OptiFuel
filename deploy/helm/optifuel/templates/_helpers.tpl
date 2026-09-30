{{/* Selector for one component: `dict "root" $ "component" "api"`. */}}
{{- define "optifuel.selector" -}}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{/* All labels for one component; same argument as `optifuel.selector`. */}}
{{- define "optifuel.labels" -}}
app.kubernetes.io/name: optifuel
app.kubernetes.io/managed-by: {{ .root.Release.Service }}
helm.sh/chart: {{ .root.Chart.Name }}-{{ .root.Chart.Version }}
{{ include "optifuel.selector" . }}
{{- end }}

{{- define "optifuel.image" -}}
image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}{{ with .Values.image.digest }}@{{ . }}{{ end }}"
imagePullPolicy: {{ .Values.image.pullPolicy }}
{{- end }}

{{/* The image's `app` user, numeric so the kubelet can verify non-root; code is read-only. */}}
{{- define "optifuel.securityContext" -}}
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  readOnlyRootFilesystem: true
  allowPrivilegeEscalation: false
  capabilities:
    drop: [ALL]
{{- end }}

{{- define "optifuel.secretEnv" -}}
- name: {{ .env }}
  valueFrom:
    secretKeyRef:
      name: {{ .root.Values.secret.name }}
      key: {{ .key }}
{{- end }}

{{/* Env every process reads: `Settings` fields common to API, worker, migrate, cleanup. */}}
{{- define "optifuel.env" -}}
- name: OPTIFUEL_ENVIRONMENT
  value: {{ .Values.environment | quote }}
{{ include "optifuel.secretEnv" (dict "root" . "env" "OPTIFUEL_DATABASE_URL" "key" "database-url") }}
- name: OPTIFUEL_TENANTS
  value: {{ include "optifuel.tenantsJson" . | quote }}
{{- end }}

{{/* `tenants` in the shape `Settings.tenants` parses. Codes land in resource names and SQL. */}}
{{- define "optifuel.tenantsJson" -}}
{{- $out := dict }}
{{- range $code, $t := .Values.tenants }}
{{- if not (regexMatch "^[A-Z0-9]+$" $code) }}
{{- fail (printf "tenants: airline code %q must be upper-case letters and digits" $code) }}
{{- end }}
{{- $types := required (printf "tenants.%s.aircraftTypes is required" $code) $t.aircraftTypes }}
{{- $version := required (printf "tenants.%s.modelVersion is required" $code) $t.modelVersion }}
{{- $_ := set $out $code (dict "aircraft_types" $types "model_version" $version) }}
{{- end }}
{{- toJson $out }}
{{- end }}

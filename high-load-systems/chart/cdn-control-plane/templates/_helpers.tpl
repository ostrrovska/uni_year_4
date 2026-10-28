{{/*
DevOps Lab4 - shared named templates.

Every object name and every label block in this chart comes from here, so that
two releases of the same chart can live in one cluster without colliding and so
that a change to the labelling scheme is a one-file change.
*/}}

{{/* Chart name, overridable, truncated to the 63-character label limit. */}}
{{- define "cdn.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Fully qualified object name: release name plus chart name, unless the release is
already named after the chart (then the repetition is dropped). This is what
makes `helm install a` and `helm install b` coexist - every object below is
named from it, and nothing hard-codes a release name.
*/}}
{{- define "cdn.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "cdn.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Selector labels. Immutable once a Deployment exists - spec.selector cannot be
patched - so this set is deliberately minimal: name, instance, component.
Call as: include "cdn.selectorLabels" (dict "ctx" $ "component" "api")
*/}}
{{- define "cdn.selectorLabels" -}}
app.kubernetes.io/name: {{ include "cdn.name" .ctx }}
app.kubernetes.io/instance: {{ .ctx.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{/* The full label set: selector labels plus the descriptive ones. */}}
{{- define "cdn.labels" -}}
helm.sh/chart: {{ include "cdn.chart" .ctx }}
{{ include "cdn.selectorLabels" . }}
app.kubernetes.io/version: {{ .ctx.Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .ctx.Release.Service }}
app.kubernetes.io/part-of: cdn-control-plane
{{- end -}}

{{/* The image reference, with appVersion as the tag's default. */}}
{{- define "cdn.image" -}}
{{- printf "%s:%s" .Values.image.repository (.Values.image.tag | default .Chart.AppVersion) -}}
{{- end -}}

{{/*
The async SQLAlchemy URL. Built from the in-chart database when one is enabled,
otherwise taken verbatim from externalDatabase.url. The `+asyncpg` driver
suffix is not decoration: app/core/config.py and migrations/env.py both build an
async engine from this string and a plain postgresql:// URL fails at startup.
*/}}
{{- define "cdn.databaseUrl" -}}
{{- if .Values.postgresql.enabled -}}
{{- printf "postgresql+asyncpg://%s:%s@%s-postgresql:5432/%s" .Values.postgresql.auth.username .Values.postgresql.auth.password (include "cdn.fullname" .) .Values.postgresql.auth.database -}}
{{- else -}}
{{- required "postgresql.enabled is false, so externalDatabase.url must be set" .Values.externalDatabase.url -}}
{{- end -}}
{{- end -}}

{{/* Redis URL, empty when the cache is disabled so the app falls back to NullCache. */}}
{{- define "cdn.redisUrl" -}}
{{- if .Values.redis.enabled -}}
{{- printf "redis://%s-redis:6379/0" (include "cdn.fullname" .) -}}
{{- else -}}
{{- .Values.externalRedis.url | default "" -}}
{{- end -}}
{{- end -}}

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

{{/*
DevOps Lab6 - the API pod template, defined once.

Lab 6 needs the same pod in two kinds of object: a Deployment when
rollout.enabled is false, and an Argo Rollout when it is true. The obvious move
is to copy the block into rollout.yaml, and it is the wrong one - two copies of
a pod spec drift, and the first time they disagree only one of them is the
object actually running. Everything that describes the pod lives here; the two
callers differ only in their kind and their update strategy.

Call as: {{- include "cdn.apiPodTemplate" . | nindent 4 }} under `template:`.
*/}}
{{- define "cdn.apiPodTemplate" -}}
metadata:
  labels:
    {{- include "cdn.labels" (dict "ctx" $ "component" "api") | nindent 8 }}
  annotations:
    # Roll the pods when configuration changes but the image does not.
    # Without this, an upgrade that only edits the ConfigMap would leave
    # every replica running on the old values indefinitely.
    checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
    checksum/secret: {{ include (print $.Template.BasePath "/secret.yaml") . | sha256sum }}
    # DevOps Lab5 - wave 2: the API rolls only after the database is
    # Healthy (wave 0) and the migration has completed (wave 1).
    "argocd.argoproj.io/sync-wave": "2"
spec:
  securityContext:
    {{- toYaml .Values.podSecurityContext | nindent 8 }}
  containers:
    - name: api
      image: {{ include "cdn.image" . | quote }}
      imagePullPolicy: {{ .Values.image.pullPolicy }}
      ports:
        - name: http
          containerPort: 8000
      # See k8s/50-api-deployment.yaml: endpoint removal and SIGTERM race,
      # and without this a rolling update drops a request or two. The sleep
      # delays SIGTERM while the removal propagates; it does not extend the
      # shutdown itself.
      lifecycle:
        preStop:
          exec:
            command: ["sleep", {{ .Values.api.preStopSleepSeconds | quote }}]
      envFrom:
        - configMapRef:
            name: {{ include "cdn.fullname" . }}-config
        - secretRef:
            name: {{ include "cdn.secretName" . }}
      # INSTANCE_ID stays unset so the app falls back to the hostname, which
      # here is the pod name - making /health self-identifying.
      livenessProbe:
        httpGet:
          path: /health
          port: http
        periodSeconds: 10
        timeoutSeconds: 3
        failureThreshold: 3
      # Reproduces the HAProxy check: inter 2s, fall 2, rise 2.
      # failureThreshold is 2 rather than 1 on the strength of a measured
      # run - one-strike ejection cost 190 to 110 req/s, because a
      # momentarily saturated instance is not a dead one.
      readinessProbe:
        httpGet:
          path: /health/ready
          port: http
        periodSeconds: 2
        timeoutSeconds: 2
        failureThreshold: 2
        successThreshold: 2
      # The schema is applied by the migrate hook, so first boot gets a
      # generous window without loosening the steady-state probes above.
      startupProbe:
        httpGet:
          path: /health
          port: http
        periodSeconds: 3
        failureThreshold: 30
      resources:
        {{- toYaml .Values.api.resources | nindent 12 }}
{{- end -}}

{{/*
DevOps Lab5 - the name of the Secret holding DATABASE_URL and POSTGRES_PASSWORD.

Default: the Secret this chart renders itself, from .Values (Lab 4 behaviour).
When existingSecret is set, the chart renders no Secret at all and every
workload reads the named one instead. That is what lets the GitOps values file
be committed: under Argo CD there is no `--set` to pass a password through, so
the only way to keep the credential out of Git is for the manifest to name a
Secret that was created in the cluster out of band.
*/}}
{{- define "cdn.secretName" -}}
{{- .Values.existingSecret | default (printf "%s-secrets" (include "cdn.fullname" .)) -}}
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

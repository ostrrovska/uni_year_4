# GitOps — Argo CD configuration (DevOps Lab 5)

This directory is the desired state of the CDN Control Plane on the local
minikube cluster. Lab 4 deployed it by typing `helm upgrade --install`; here the
cluster reads this directory and converges on it by itself.

Assignment point 1 offered a separate `<project>-gitops` repository or these
directories inside the application repository. This is option **(b)**: the repo
is already a monorepo of five courses, and a sixth repository holding a copy of
one chart would be a copy that drifts.

## Layout

```
gitops/
  bootstrap/root-app.yaml            the ONLY object ever applied by hand
  argocd-apps/cdn-control-plane.yaml the application, created by the root
  values/values-minikube.yaml        how it is configured on minikube
```

The chart itself is **not** copied in here. It stays at
[`../chart/cdn-control-plane/`](../chart/cdn-control-plane/) where Lab 4 put it,
and `argocd-apps/cdn-control-plane.yaml` references that path with an Argo CD
multi-source Application. Two copies of a chart in one repository disagree
sooner or later, and when they do the cluster follows the copy nobody has been
editing.

## The one manual command

```bash
kubectl apply -n argocd -f high-load-systems/gitops/bootstrap/root-app.yaml
```

That is the whole bootstrap. The root Application watches `argocd-apps/`, so
every later change — a new application, a new image tag, a different replica
count — is a commit.

## The credential

`values-minikube.yaml` holds no password. The chart's `existingSecret` value
names a Secret that is created in the cluster out of band, once:

```bash
PGPASS='choose-one'
kubectl create namespace cdn-gitops --dry-run=client -o yaml | kubectl apply -f -
kubectl create secret generic cdn-db -n cdn-gitops \
  --from-literal=POSTGRES_PASSWORD="$PGPASS" \
  --from-literal=DATABASE_URL="postgresql+asyncpg://cdn:$PGPASS@cdn-cdn-control-plane-postgresql:5432/cdn_control_plane"
```

With `existingSecret` set the chart renders no Secret of its own, so nothing in
Git ever holds the value — only the name. There is no `--set` under GitOps: Argo
CD renders the chart from what is committed, so a committed values file is the
only input and it must stay free of credentials.

## Releasing a new version

1. Tag the application: `git tag cdn-v1.3.0 && git push origin cdn-v1.3.0`.
   CI builds and publishes `ghcr.io/ostrrovska/cdn-control-plane:1.3.0`.
2. Edit `image.tag` in `values/values-minikube.yaml`, commit, push.
3. Nothing else. Argo CD notices the commit and rolls the Deployment.

`curl http://$(minikube ip):30082/version` reports what actually landed — the
value is baked into the image by `docker/Dockerfile`, so a pod can only report
the build it was made from.

## Full report

[`../docs/devops/lab-05.md`](../docs/devops/lab-05.md), with the run transcripts
in [`../docs/devops/lab-05-output/`](../docs/devops/lab-05-output/).

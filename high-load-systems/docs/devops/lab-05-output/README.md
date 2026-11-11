# Lab 5 run transcripts

Written by `scripts/devops_lab5_setup.ps1` (once) and
`scripts/devops_lab5_demo.ps1` (every run). Both overwrite their own files, so
the directory always holds one coherent run rather than an accumulation.

| File | Written by | Assignment points |
|---|---|---|
| `01-environment.txt` | setup | 3 — minikube, Argo CD install, password change, `cdn-db`, root Application |
| `03-argocd.txt` | demo | 3 — Argo CD pods, CLI version, absence of `argocd-initial-admin-secret` |
| `04-app-of-apps.txt` | demo | 4 — root source, application list, resource tree, Synced/Healthy |
| `05-release.txt` | demo | 5 — values diff, commit, new tag and `/version` |
| `06a-drift.txt` | demo | 6a — `kubectl scale`, OutOfSync, `argocd app diff`, selfHeal reverting it |
| `06b-degraded.txt` | demo | 6b — Synced + Degraded, `ImagePullBackOff`, events |
| `06c-revert.txt` | demo | 6c — `git revert`, `git log`, `argocd app history` |
| `00-wait.txt` | demo | rollout waits |

Empty until the first run on a live cluster. The report
[`../lab-05.md`](../lab-05.md) says which of its claims are static (verified by
`helm lint`, `helm template` and parser checks) and which need this directory.

"""DevOps Lab5 - static checks on the rendered chart.

`helm lint` parses templates, not the YAML they produce, so it accepts a
document with the same key twice - the second silently wins. That is how a
sync-wave annotation block landed next to the existing checksum block in
agents-deployment.yaml and quietly replaced it. This renders every values file
the project ships and refuses duplicate mapping keys.

    python -I scripts/check_chart_render.py
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHART = ROOT / "chart" / "cdn-control-plane"

# release name -> values file, covering every way this chart is deployed.
CASES = {
    "defaults": None,
    "dev": CHART / "values-dev.yaml",
    "prod": CHART / "values-prod.yaml",
    "minikube": ROOT / "gitops" / "values" / "values-minikube.yaml",
}


class StrictLoader(yaml.SafeLoader):
    """SafeLoader that treats a repeated mapping key as an error."""


def _no_duplicates(loader: StrictLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    mapping: dict = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.YAMLError(
                f"duplicate key {key!r} at line {key_node.start_mark.line + 1} "
                f"of the rendered output"
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicates)


def _helm() -> str:
    local = pathlib.Path.home() / "AppData/Local/Programs/k8stools/helm.exe"
    return str(local) if local.exists() else "helm"


def main() -> int:
    failures = 0
    for name, values in CASES.items():
        cmd = [_helm(), "template", "cdn", str(CHART)]
        if values is not None:
            cmd += ["-f", str(values)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"FAIL {name}: helm template failed\n{result.stderr.strip()}")
            failures += 1
            continue
        try:
            docs = [d for d in yaml.load_all(result.stdout, Loader=StrictLoader) if d]
        except yaml.YAMLError as exc:
            print(f"FAIL {name}: {exc}")
            failures += 1
            continue

        kinds = sorted(d.get("kind", "?") for d in docs)
        # The one invariant worth asserting beyond parseability: a committed
        # values file must never make the chart render a credential.
        secrets = [d for d in docs if d.get("kind") == "Secret"]
        rendered_literals = [
            k for s in secrets for k in (s.get("stringData") or {}) if "PASSWORD" in k.upper()
        ]
        note = ""
        if name == "minikube":
            if secrets:
                print(f"FAIL {name}: the GitOps values file rendered {len(secrets)} Secret(s)")
                failures += 1
                continue
            note = "  (no Secret rendered, as required)"
        elif rendered_literals:
            note = f"  (chart-owned Secret: {', '.join(rendered_literals)})"

        print(f"OK   {name}: {len(docs)} documents, kinds {', '.join(kinds)}{note}")

    if failures:
        print(f"\n{failures} case(s) failed.")
        return 1
    print("\nAll render cases parsed cleanly, with no duplicate keys.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

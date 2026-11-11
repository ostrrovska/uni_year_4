r"""Формує results/environment.md.

Відмінність від ЛР7: навчання йшло не на цій машині, а в Google Colab, тому
середовище навчання береться з results/raw/taskN.json (його туди записують самі
ноутбуки), а локальні версії — лише для генерації ноутбуків і збору результатів.

Запуск:  PYTHONUTF8=1 ..\lab7\.venv\Scripts\python.exe scripts\write_environment.py
"""
import json
import platform
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parent.parent
RESULTS = LAB_ROOT / "results"
RAW = RESULTS / "raw"

LOCAL_PACKAGES = ["tensorflow", "keras", "numpy", "matplotlib", "pillow",
                  "scikit-learn", "scipy", "notebook", "nbconvert", "nbformat"]
TASKS = ["task1", "task2", "task3", "task4"]


def pkg(name):
    try:
        return version(name)
    except PackageNotFoundError:
        return "—"


def gpu_name():
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=15)
        return out.stdout.strip().splitlines()[0] if out.returncode == 0 else "—"
    except (OSError, subprocess.SubprocessError, IndexError):
        return "—"


def table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|---" * len(head) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def colab_section():
    found = {}
    for task in TASKS:
        p = RAW / f"{task}.json"
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        found[d["base"]] = d

    if not found:
        return ("## Середовище навчання\n\n"
                "Результатів ще немає — спочатку виконайте ноутбуки в Colab і "
                "розпакуйте зіпи через `scripts/unpack_results.py`.\n")

    first = next(iter(found.values()))
    env = first["environment"]
    rows = [
        ["Платформа", "Google Colab" if env["in_colab"] else "локальний запуск"],
        ["GPU", ", ".join(env["gpu"]) if env["gpu"] else "немає (CPU)"],
        ["TensorFlow", env["tensorflow"]],
        ["Keras", env["keras"]],
    ]
    lines = ["## Середовище навчання", "", table(["Параметр", "Значення"], rows), ""]

    time_rows = []
    for base, d in found.items():
        feat = d["stage_a"].get("feature_extraction_sec", 0)
        b, c = d["stage_b"], d["stage_c"]
        time_rows.append([
            base,
            f"{feat / 60:.1f}",
            f"{b['train_time_sec'] / 60:.1f}",
            f"{c['train_time_sec'] / 60:.1f}",
            f"{(feat + b['train_time_sec'] + c['train_time_sec']) / 60:.1f}",
        ])
    lines += ["### Фактичний час навчання", "",
              table(["Мережа", "кеш ознак (A), хв", "етап B, хв", "етап C, хв",
                     "разом, хв"], time_rows), ""]
    return "\n".join(lines)


def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    local_rows = [[p, pkg(p)] for p in LOCAL_PACKAGES]

    text = "\n".join([
        "# Середовище виконання",
        "",
        colab_section(),
        "## Чому навчання в Colab, а не локально",
        "",
        f"- Відеокарта в системі є ({gpu_name()}), але **TensorFlow ≥ 2.11 не підтримує "
        "GPU на native Windows** — потрібні WSL2 або TensorFlow-DirectML.",
        "- У лабораторній 7 одна епоха невеликої згортки на повному наборі займала "
        "4.9 хв на CPU (`dl/lab7/results/raw/timing_probe.json`). Згорткові частини "
        "VGG16, InceptionV3 і ResNet50 на порядок важчі, тому донавчання на CPU "
        "зайняло б десятки годин.",
        "- Умова роботи й так вимагає посилання на Google Colab.",
        "",
        "## Локальне середовище",
        "",
        "Тут лише генеруються ноутбуки й збираються результати — навчання не виконується.",
        "",
        table(["Параметр", "Значення"], [
            ["ОС", platform.platform()],
            ["Процесор", f"{platform.processor()}, логічних ядер: {__import__('os').cpu_count()}"],
            ["Python", sys.version.split()[0]],
        ]),
        "",
        table(["Пакет", "Версія"], local_rows),
        "",
    ])
    out = RESULTS / "environment.md"
    out.write_text(text, encoding="utf-8")
    print(f"[+] {out}")


if __name__ == "__main__":
    main()

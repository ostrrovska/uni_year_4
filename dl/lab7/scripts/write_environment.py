"""Формує results/environment.md: версії, залізо, режим навчання (CPU/GPU, повний набір чи підмножина)."""
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parent.parent
RAW = LAB_ROOT / "results" / "raw"


def nvidia_smi():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
                              "--format=csv,noheader"], capture_output=True, text=True, timeout=20)
        return out.stdout.strip() or "не визначено"
    except Exception:
        return "nvidia-smi недоступний"


def main():
    import tensorflow as tf
    import keras

    gpus = tf.config.list_physical_devices("GPU")
    probe = json.loads((RAW / "timing_probe.json").read_text(encoding="utf-8")) \
        if (RAW / "timing_probe.json").exists() else {}
    t4 = json.loads((RAW / "task4.json").read_text(encoding="utf-8")) \
        if (RAW / "task4.json").exists() else {}

    pkgs = {}
    for name in ("tensorflow", "keras", "numpy", "matplotlib", "pillow", "scikit-learn", "scipy",
                 "notebook", "nbconvert"):
        try:
            from importlib.metadata import version
            pkgs[name] = version(name)
        except Exception:
            pkgs[name] = "—"

    lines = [
        "# Середовище виконання", "",
        "## Система", "",
        f"- ОС: {platform.platform()}",
        f"- Процесор: {platform.processor() or platform.machine()}, "
        f"логічних ядер: {os.cpu_count()}",
        f"- Відеокарта (nvidia-smi): {nvidia_smi()}",
        f"- Python: {sys.version.split()[0]} (venv `dl/lab7/.venv`)", "",
        "## Бібліотеки", "",
        "| Пакет | Версія |", "|---|---|",
    ]
    lines += [f"| {k} | {v} |" for k, v in pkgs.items()]
    lines += [
        "", "## CPU чи GPU", "",
        f"- TensorFlow бачить GPU-пристроїв: **{len(gpus)}**",
        "- Відеокарта в системі є, але TensorFlow ≥ 2.11 **не підтримує GPU на Windows** "
        "(потрібні WSL2 або TensorFlow-DirectML). Тому все навчання виконано **на CPU**.",
        "- У Google Colab ті самі ноутбуки виконуються на GPU без змін коду.", "",
        "## Розмір набору для завдання 4", "",
    ]
    if probe:
        lines += [
            f"- замір швидкості: {probe['sec_per_train_step']} с на крок "
            f"({probe['probe_steps']} кроків), {probe['full_train_steps']} кроків на епоху",
            f"- прогноз однієї епохи на повному наборі: **{probe['projected_full_epoch_min']} хв**",
            f"- для підмножини 2000/500/500 на клас було б ≈{probe['subset_2000_epoch_min']} хв на епоху",
        ]
    if t4:
        s = t4["subset"]
        if s["full_dataset"]:
            lines += [
                "- оскільки епоха на повному наборі вкладається в поріг 6 хв, навчання виконано "
                f"**на повному наборі**: {s['train_per_class']}/{s['val_per_class']}/"
                f"{s['test_per_class']} на клас (70/15/15 від 12500), разом "
                f"{t4['samples']['train'] + t4['samples']['val'] + t4['samples']['test']} зображень",
                f"- фактичний час навчання: Adam {t4['adam']['train_time_sec'] / 60:.1f} хв "
                f"({t4['adam']['epochs_done']} епох), RMSprop "
                f"{t4['rmsprop']['train_time_sec'] / 60:.1f} хв ({t4['rmsprop']['epochs_done']} епох)",
            ]
        else:
            lines += [
                f"- навчання виконано **на підмножині**: {s['train_per_class']}/{s['val_per_class']}/"
                f"{s['test_per_class']} на клас; повний набір потребує Colab GPU",
            ]
    lines += ["", "## Набори даних", "",
              "- Horses vs Humans: завантажено за посиланнями з базового ноутбука "
              "(1027 навчальних, 256 валідаційних зображень)",
              "- Happy or Sad: `HappyVsSad/data.zip` з архіву лабораторної (40 happy + 40 sad)",
              "- Dogs vs Cats: `dogs-vs-cats.zip` → `train.zip` з архіву лабораторної (25 000 зображень; "
              "`test1.zip` не використовується, бо не має міток)", ""]

    (LAB_ROOT / "results" / "environment.md").write_text("\n".join(lines), encoding="utf-8")
    print("results/environment.md оновлено")


if __name__ == "__main__":
    main()

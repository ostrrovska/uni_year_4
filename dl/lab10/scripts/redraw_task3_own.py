r"""Перемальовує results/task3_own_images.png із виправленими мітками.

Рисунок, що приїхав із Colab, намальований до виправлення помилки в розмітці
обрізаного набору: чотири коти в нижньому ряду підписані «ПОМИЛКА», хоча
модель відповіла правильно (див. scripts/fix_own_labels.py).

Перемалювати його локально можна точно, без моделі й без Colab: у
results/raw/task3.json збережена ймовірність P(собака) по кожному файлу, а
самі зображення лежать у lab7/my_images. Код, розмітка й підписи повторюють
клітинку ноутбука один в один.

Запуск:  PYTHONUTF8=1 ..\..\lab7\.venv\Scripts\python.exe scripts\redraw_task3_own.py
"""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from tensorflow.keras.utils import load_img

LAB_ROOT = Path(__file__).resolve().parent.parent
RAW = LAB_ROOT / "results" / "raw" / "task3.json"
OUT = LAB_ROOT / "results" / "task3_own_images.png"
LAB7_IMAGES = LAB_ROOT.parent / "lab7" / "my_images"

# Теки власних зображень лежать у ЛР7 під іншими іменами, ніж у зібраному
# my_images.zip, — тут потрібні саме вихідні.
FOLDERS = {
    "cats_dogs": "task4_cats_dogs",
    "cats_dogs_hard": "task4_hard",
    "cats_dogs_cropped": "task4_cropped",
}
INPUT_SIZE = 150
COLS = 6


def main():
    data = json.loads(RAW.read_text(encoding="utf-8"))
    title = data["experiments"][data["best"]]["title"]
    records = [(folder, r) for folder, recs in data["own_images"].items()
               for r in recs]

    rows = (len(records) + COLS - 1) // COLS
    fig, axes = plt.subplots(rows, COLS, figsize=(2.7 * COLS, 3.1 * rows))
    flat = axes.ravel()

    for ax, (folder, r) in zip(flat, records):
        conf = r["prob_dog"] if r["predicted"] == "собака" else 1 - r["prob_dog"]
        path = LAB7_IMAGES / FOLDERS[folder] / r["file"]
        if not path.exists():
            raise FileNotFoundError(path)
        ax.imshow(load_img(path, target_size=(INPUT_SIZE, INPUT_SIZE)))
        ax.set_title(f"{r['predicted']} {conf:.0%}\n{'+' if r['correct'] else 'ПОМИЛКА'}",
                     fontsize=7.5, color="green" if r["correct"] else "crimson")
        ax.axis("off")
    for ax in flat[len(records):]:
        ax.axis("off")

    good = sum(r["correct"] for _, r in records)
    fig.suptitle(f"{title}: {good} з {len(records)} власних зображень", fontsize=13)
    plt.tight_layout()
    plt.savefig(OUT, dpi=110, bbox_inches="tight")
    print(f"{OUT} — {good} з {len(records)}, {OUT.stat().st_size // 1024} КБ")


if __name__ == "__main__":
    main()

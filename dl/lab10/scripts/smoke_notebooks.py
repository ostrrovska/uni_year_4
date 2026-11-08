r"""Димовий прогін ноутбуків локально, щоб помилки не спливали вже в Colab.

Виконує справжні клітинки ноутбуків, але підміняє Model.fit так, щоб кожне
навчання робило одну епоху на кількох батчах. Перевіряється саме код — форми
тензорів, імена шарів, препроцесія, збирання таблиць і графіків, — а не якість
навчання: її можна отримати лише повним прогоном на GPU.

Потрібні локальні дані:
  lab7/data/horse-or-human, lab7/data/validation-horse-or-human   (Завдання 2)
  lab10/data/cats_dogs_small  <- scripts/prepare_cats_dogs_2000.py (Завдання 3)
  lab10/my_images/            <- розпакований my_images.zip        (Завдання 2-4)

Запуск:  PYTHONUTF8=1 ..\..\lab7\.venv\Scripts\python.exe scripts\smoke_notebooks.py [2|3|4]
"""
import os
import sys
import warnings
from pathlib import Path

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
warnings.filterwarnings("ignore")

import matplotlib
import nbformat

matplotlib.use("Agg")          # без вікон
import tensorflow as tf        # noqa: E402

LAB_ROOT = Path(__file__).resolve().parent.parent
NB_DIR = LAB_ROOT / "notebooks"

NOTEBOOKS = {
    "2": "Task2_horses_humans_experiments.ipynb",
    "3": "Task3_cats_dogs_small.ipynb",
    "4": "Task4_rock_paper_scissors.ipynb",
}

# Клітинки, які в димовому прогоні пропускаємо: вони лише вивантажують
# результати й у Colab-гілці все одно нічого не роблять.
SKIP_MARKERS = ("files.download",)

_real_fit = tf.keras.Model.fit
_real_evaluate = tf.keras.Model.evaluate


def tiny_fit(self, *args, **kwargs):
    kwargs["epochs"] = 1
    kwargs["steps_per_epoch"] = 2
    kwargs["validation_steps"] = 1
    kwargs["verbose"] = 0
    return _real_fit(self, *args, **kwargs)


def tiny_evaluate(self, *args, **kwargs):
    kwargs["steps"] = 1
    kwargs["verbose"] = 0
    return _real_evaluate(self, *args, **kwargs)


def run_notebook(key):
    path = NB_DIR / NOTEBOOKS[key]
    print(f"\n{'=' * 72}\n{path.name}\n{'=' * 72}")
    nb = nbformat.read(path, as_version=4)

    tf.keras.Model.fit = tiny_fit
    tf.keras.Model.evaluate = tiny_evaluate
    # Клітинки звертаються до Path.cwd().parent, тому стаємо у scripts/.
    os.chdir(Path(__file__).resolve().parent)

    ns = {"__name__": "__main__"}
    for i, cell in enumerate(nb.cells):
        if cell.cell_type != "code":
            continue
        src = cell.source
        if any(m in src for m in SKIP_MARKERS) and "IN_COLAB" not in src:
            print(f"  [{i:>2}] пропущено")
            continue
        # Магія IPython локально не потрібна: гілки з нею під IN_COLAB.
        src = "\n".join(l for l in src.splitlines()
                        if not l.lstrip().startswith(("!", "%")))
        try:
            exec(compile(src, f"{path.name}:{i}", "exec"), ns)
            # Конфігурація 300x300 Завдання 2 — це 227 млн параметрів, матриця
            # Dense важить 867 МБ. На GPU вона проходить, у локальній пам'яті
            # ні, тож у димовому прогоні її пропускаємо.
            if os.environ.get("SMOKE_ALL") != "1" and isinstance(ns.get("CONFIGS"), list):
                big = [c["name"] for c in ns["CONFIGS"] if c.get("size", 0) > 200]
                if big:
                    ns["CONFIGS"] = [c for c in ns["CONFIGS"] if c.get("size", 0) <= 200]
                    print(f"       (локально пропускаю {', '.join(big)})")
            print(f"  [{i:>2}] ok")
        except Exception as e:
            print(f"  [{i:>2}] ПОМИЛКА: {type(e).__name__}: {e}")
            import traceback

            traceback.print_exc(limit=3)
            return False
    return True


def main():
    keys = sys.argv[1:] or list(NOTEBOOKS)
    ok = True
    for key in keys:
        ok &= run_notebook(key)
    print("\nРЕЗУЛЬТАТ:", "усе пройшло" if ok else "є помилки")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

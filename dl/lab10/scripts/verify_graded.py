r"""Перевіряє Expected Output ноутбуків Завдань 1 і 5 на справжніх даних.

Ці два ноутбуки здаються без права щось міняти поза блоками розв'язку, тому
єдиний спосіб переконатися, що вони правильні, — виконати їхній код і звірити
числа з блоками **Expected Output** у самому ноутбуці.

Навчання тут не відбувається: перевіряються форми, типи, кількість параметрів
і те, що кілька кроків навчання проходять без помилок. Повний прогін — у Colab.

Дані:
  Завдання 1 — lab7/data/horse-or-human і validation-horse-or-human
  Завдання 5 — два CSV з Google Drive, завантажуються в data/ при першому запуску

Запуск:  PYTHONUTF8=1 ..\..\lab7\.venv\Scripts\python.exe scripts\verify_graded.py [1|5]
"""
import os
import sys
import urllib.request
from pathlib import Path

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

import matplotlib
import nbformat

matplotlib.use("Agg")

LAB_ROOT = Path(__file__).resolve().parent.parent
NB_DIR = LAB_ROOT / "notebooks"
DATA = LAB_ROOT / "data"

HORSES = LAB_ROOT.parent / "lab7" / "data" / "horse-or-human"
HORSES_VAL = LAB_ROOT.parent / "lab7" / "data" / "validation-horse-or-human"

# Ті самі файли, що тягне клітинка gdown у базовому ноутбуці Завдання 5.
SIGN_CSV = {
    "sign_mnist_train.csv": "1z0DkA9BytlLxO1C0BAWzknLyQmZAp0HR",
    "sign_mnist_test.csv": "1z1BIj4qmri59GWBG4ivMNFtpZ4AXIbzg",
}


def load_cells(name, skip_markers=()):
    """Виконує кодові клітинки ноутбука, пропускаючи магію й довге навчання."""
    nb = nbformat.read(NB_DIR / name, as_version=4)
    ns = {}
    for i, cell in enumerate(nb.cells):
        if cell.cell_type != "code":
            continue
        src = cell.source
        if any(l.lstrip().startswith(("!", "%")) for l in src.splitlines()):
            continue
        if any(m in src for m in skip_markers):
            continue
        try:
            exec(compile(src, f"<{name}:{i}>", "exec"), ns)
        except Exception:
            # Клітинки, що спираються на шляхи Colab, тут падають очікувано —
            # потрібні лише визначення функцій, які вже виконались вище.
            pass
    return ns


def check(label, expected, got):
    ok = expected == got
    print(f"  {label}")
    print(f"    Expected: {expected}")
    print(f"    Отримано: {got}  {'OK' if ok else '<-- РОЗБІЖНІСТЬ'}")
    return ok


def verify_task1():
    print("\n=== Завдання 1: Task1_transfer_learning.ipynb ===")
    if not HORSES.is_dir():
        print(f"  пропускаю: немає {HORSES}")
        return True

    ns = load_cells("Task1_transfer_learning.ipynb",
                    skip_markers=("model.fit(", "plt.imshow", "os.listdir"))
    ok = True

    train_gen, val_gen = ns["train_val_generators"](str(HORSES), str(HORSES_VAL))
    ok &= check("кількість зображень", (1027, 256), (train_gen.samples, val_gen.samples))
    ok &= check("форма входу", (150, 150, 3), train_gen.image_shape)

    # Неіснуючий шлях навмисне: так перевіряється запасний шлях завантаження
    # ваг, бо бакет mledu-datasets віддає 403.
    pre = ns["create_pre_trained_model"]("/nonexistent/weights.h5")
    ok &= check("база: параметрів / навчаних", (21_802_784, 0),
                (pre.count_params(),
                 sum(w.shape.num_elements() for w in pre.trainable_weights)))

    last_output = ns["output_of_last_layer"](pre)
    ok &= check("вихід mixed7", (None, 7, 7, 768), tuple(last_output.shape))

    model = ns["create_final_model"](pre, last_output)
    ok &= check("модель: параметрів / навчаних", (47_512_481, 38_537_217),
                (model.count_params(),
                 sum(w.shape.num_elements() for w in model.trainable_weights)))

    model.fit(train_gen, validation_data=val_gen, epochs=1,
              steps_per_epoch=2, validation_steps=1, verbose=0)
    print("  2 кроки навчання пройшли без помилок")
    return ok


def verify_task5():
    print("\n=== Завдання 5: Task5_sign_language.ipynb ===")
    DATA.mkdir(parents=True, exist_ok=True)
    for name, file_id in SIGN_CSV.items():
        path = DATA / name
        if not path.exists():
            print(f"  завантажую {name} ...")
            urllib.request.urlretrieve(
                f"https://drive.google.com/uc?export=download&id={file_id}", path)

    ns = load_cells("Task5_sign_language.ipynb",
                    skip_markers=("model.fit(", "plot_categories(", "open(TRAINING_FILE)"))
    ok = True

    import time

    t0 = time.time()
    tr_i, tr_l = ns["parse_data_from_input"](str(DATA / "sign_mnist_train.csv"))
    va_i, va_l = ns["parse_data_from_input"](str(DATA / "sign_mnist_test.csv"))
    elapsed = time.time() - t0

    ok &= check("розбір CSV: форми й типи",
                ((27455, 28, 28), "float64", (27455,), "float64",
                 (7172, 28, 28), "float64", (7172,), "float64"),
                (tr_i.shape, str(tr_i.dtype), tr_l.shape, str(tr_l.dtype),
                 va_i.shape, str(va_i.dtype), va_l.shape, str(va_l.dtype)))
    print(f"    час розбору: {elapsed:.1f} с (умова: менше 60)")
    ok &= elapsed < 60

    tg, vg = ns["train_val_generators"](tr_i, tr_l, va_i, va_l)
    ok &= check("генератори: форми",
                ((27455, 28, 28, 1), (27455,), (7172, 28, 28, 1), (7172,)),
                (tg.x.shape, tg.y.shape, vg.x.shape, vg.y.shape))

    model = ns["create_model"]()
    n_conv = sum(1 for l in model.layers if "Conv2D" in type(l).__name__)
    n_pool = sum(1 for l in model.layers if "MaxPooling2D" in type(l).__name__)
    print(f"  Conv2D {n_conv} і MaxPooling2D {n_pool} (умова: не більше 2 кожного)")
    ok &= n_conv <= 2 and n_pool <= 2

    units = model.layers[-1].units
    max_label = int(max(tr_l.max(), va_l.max()))
    print(f"  виходів {units}, найбільша мітка {max_label} "
          f"({'достатньо' if units > max_label else 'ЗАМАЛО'})")
    ok &= units > max_label

    model.fit(tg, epochs=1, steps_per_epoch=5, validation_data=vg,
              validation_steps=2, verbose=0)
    print("  5 кроків навчання пройшли без помилок")
    return ok


def main():
    which = sys.argv[1:] or ["1", "5"]
    ok = True
    if "1" in which:
        ok &= verify_task1()
    if "5" in which:
        ok &= verify_task5()
    print("\nРЕЗУЛЬТАТ:", "усі Expected Output збігаються" if ok else "Є РОЗБІЖНОСТІ")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

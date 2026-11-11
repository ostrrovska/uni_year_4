r"""Пункт 1: розділення Kaggle Dogs vs Cats на train / val / test для лабораторної 8.

Свого коду розподілу тут немає: функції беруться з лабораторної 7
(dl/lab7/scripts/prepare_dataset.py), як і вимагає умова — «взяти з попередньої
лабораторної роботи». Цей скрипт лише підставляє lab8-шляхи, бо в ЛР7 LAB_ROOT
прив'язаний до каталогу lab7.

Локально він потрібен рідко: навчання йде в Colab, а ноутбуки містять ті самі
функції вбудованими. Скрипт лишається для прогону на CPU і для перевірки.

Запуск:
    PYTHONUTF8=1 ..\lab7\.venv\Scripts\python.exe scripts\prepare_dataset.py
    ... scripts\prepare_dataset.py --train-n 2000 --val-n 500 --test-n 500
"""
import argparse
import importlib.util
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parent.parent
LAB7 = LAB_ROOT.parent / "lab7"
LAB7_SCRIPT = LAB7 / "scripts" / "prepare_dataset.py"


def load_lab7():
    """Імпорт модуля ЛР7 за шляхом (lab7 не є пакетом)."""
    if not LAB7_SCRIPT.exists():
        raise SystemExit(f"не знайдено {LAB7_SCRIPT} — скрипт розподілу з ЛР7 обов'язковий")
    spec = importlib.util.spec_from_file_location("lab7_prepare", LAB7_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, default=LAB7 / "data" / "dogs_vs_cats_raw" / "train",
                    help="каталог з 25 000 вихідних cat.N.jpg / dog.N.jpg")
    ap.add_argument("--dst", type=Path, default=LAB_ROOT / "data" / "cats_dogs")
    ap.add_argument("--nb-images", type=int, default=12500)
    ap.add_argument("--val-portion", type=float, default=0.15)
    ap.add_argument("--test-portion", type=float, default=0.15)
    ap.add_argument("--train-n", type=int, default=None, help="підмножина: скільки train на клас")
    ap.add_argument("--val-n", type=int, default=None)
    ap.add_argument("--test-n", type=int, default=None)
    ap.add_argument("--tree-out", type=Path, default=LAB_ROOT / "results" / "dir_tree.txt")
    a = ap.parse_args()

    lab7 = load_lab7()
    print(f"Функції розподілу взято з {LAB7_SCRIPT}")

    if not a.src.is_dir():
        raise SystemExit(f"немає {a.src}: спочатку розпакуйте train.zip "
                         f"(у ЛР7 це робить scripts/extract_data.py)")

    if a.train_n or a.val_n or a.test_n:
        n_train, n_val, n_test = a.train_n or 0, a.val_n or 0, a.test_n or 0
        mode = f"підмножина {n_train}/{n_val}/{n_test} на клас"
    else:
        nb = a.nb_images
        n_train = int(nb * (1 - a.val_portion - a.test_portion))
        n_val = int(nb * (1 - a.test_portion)) - n_train
        n_test = nb - n_train - n_val
        mode = f"повний набір {n_train}/{n_val}/{n_test} на клас (70/15/15 від {nb})"

    train_dir, val_dir, test_dir = a.dst / "train", a.dst / "val", a.dst / "test"
    print(f"Джерело: {a.src}")
    print(f"Призначення: {a.dst}")
    print(f"Режим:   {mode}")

    for d in (train_dir, val_dir, test_dir):
        lab7.create_directory(d)
    lab7.copy_images(0, n_train, a.src, train_dir)
    lab7.copy_images(n_train, n_train + n_val, a.src, val_dir)
    lab7.copy_images(n_train + n_val, n_train + n_val + n_test, a.src, test_dir)

    tree = lab7.print_tree(a.dst)
    print(tree)
    total = 2 * (n_train + n_val + n_test)
    print(f"Усього скопійовано: {total} зображень")
    if a.tree_out:
        a.tree_out.parent.mkdir(parents=True, exist_ok=True)
        a.tree_out.write_text(f"{mode}\n\n{tree}\n\nУсього: {total}\n", encoding="utf-8")
        print(f"Дерево збережено: {a.tree_out}")


if __name__ == "__main__":
    main()

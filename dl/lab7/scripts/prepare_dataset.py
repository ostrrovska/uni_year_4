"""Пункт 21: розділення Kaggle Dogs vs Cats на train / val / test.

Структура, яку вимагає flow_from_directory: <split>/cats, <split>/dogs.
За замовчуванням — 70/15/15 від 12500 зображень кожного класу (як у лекції).
Для прогону на CPU можна взяти підмножину: --train-n 2000 --val-n 500 --test-n 500.
"""
import argparse
import os
import shutil
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parent.parent


def create_directory(dir_name):
    """Чистий каталог split з підкаталогами класів (як у лекції)."""
    if os.path.exists(dir_name):
        shutil.rmtree(dir_name)
    os.makedirs(dir_name)
    os.makedirs(os.path.join(dir_name, "cats"))
    os.makedirs(os.path.join(dir_name, "dogs"))


def copy_images(start_index, end_index, source_dir, dest_dir):
    """Копіює cat.i.jpg / dog.i.jpg з діапазону індексів у відповідні підкаталоги."""
    for i in range(start_index, end_index):
        shutil.copy2(os.path.join(source_dir, f"cat.{i}.jpg"), os.path.join(dest_dir, "cats"))
        shutil.copy2(os.path.join(source_dir, f"dog.{i}.jpg"), os.path.join(dest_dir, "dogs"))


def print_tree(base_dir):
    """Дерево каталогів з кількістю файлів (пункт 21, результат №5)."""
    lines = [str(base_dir)]
    splits = [d for d in ("train", "val", "test") if (base_dir / d).is_dir()]
    for si, split in enumerate(splits):
        s_last = si == len(splits) - 1
        lines.append(f"{'└──' if s_last else '├──'} {split}/")
        classes = sorted(p.name for p in (base_dir / split).iterdir() if p.is_dir())
        for ci, cls in enumerate(classes):
            c_last = ci == len(classes) - 1
            n = len(list((base_dir / split / cls).glob("*.jpg")))
            lines.append(f"{'    ' if s_last else '│   '}{'└──' if c_last else '├──'} {cls}/  {n} файлів")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, default=LAB_ROOT / "data" / "dogs_vs_cats_raw" / "train")
    ap.add_argument("--dst", type=Path, default=LAB_ROOT / "data" / "cats_dogs")
    ap.add_argument("--nb-images", type=int, default=12500, help="зображень кожного класу в наборі")
    ap.add_argument("--val-portion", type=float, default=0.15)
    ap.add_argument("--test-portion", type=float, default=0.15)
    ap.add_argument("--train-n", type=int, default=None, help="підмножина: скільки train на клас")
    ap.add_argument("--val-n", type=int, default=None)
    ap.add_argument("--test-n", type=int, default=None)
    ap.add_argument("--tree-out", type=Path, default=LAB_ROOT / "results" / "dir_tree.txt")
    a = ap.parse_args()

    train_dir = a.dst / "train"
    val_dir = a.dst / "val"
    test_dir = a.dst / "test"

    if a.train_n or a.val_n or a.test_n:
        n_train, n_val, n_test = a.train_n or 0, a.val_n or 0, a.test_n or 0
        mode = f"підмножина {n_train}/{n_val}/{n_test} на клас"
    else:
        nb = a.nb_images
        n_train = int(nb * (1 - a.val_portion - a.test_portion))
        n_val = int(nb * (1 - a.test_portion)) - n_train
        n_test = nb - n_train - n_val
        mode = f"повний набір {n_train}/{n_val}/{n_test} на клас (70/15/15 від {nb})"

    print(f"Джерело: {a.src}")
    print(f"Режим:   {mode}")
    for d in (train_dir, val_dir, test_dir):
        create_directory(d)
    copy_images(0, n_train, a.src, train_dir)
    copy_images(n_train, n_train + n_val, a.src, val_dir)
    copy_images(n_train + n_val, n_train + n_val + n_test, a.src, test_dir)

    tree = print_tree(a.dst)
    print(tree)
    total = 2 * (n_train + n_val + n_test)
    print(f"Усього скопійовано: {total} зображень")
    if a.tree_out:
        a.tree_out.parent.mkdir(parents=True, exist_ok=True)
        a.tree_out.write_text(f"{mode}\n\n{tree}\n\nУсього: {total}\n", encoding="utf-8")
        print(f"Дерево збережено: {a.tree_out}")


if __name__ == "__main__":
    main()

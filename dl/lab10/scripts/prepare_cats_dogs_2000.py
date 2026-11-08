r"""Пункти 5-6: обмежений набір коти-собаки з повного Kaggle Dogs vs Cats.

Умова: 2000 зображень кожного класу для навчання, по 500 кожного класу для
перевірки й по 500 кожного класу для тестування. Усі фотографії різні.

Розподіл за індексами в імені файлу (cat.0.jpg … cat.12499.jpg):

    навчальні   0    … 1999   -> 2000 на клас
    перевірочні 2000 … 2499   ->  500 на клас
    тестові     2500 … 2999   ->  500 на клас

Діапазони не перетинаються, тож жодне зображення не потрапляє у два набори
одночасно, і тестові мережа не бачить ніколи. Беремо перші індекси, а не
випадкові: так набір відтворюваний і його легко перевірити.

Структура каталогів — під `flow_from_directory` (папка = клас), та сама, що в
лабораторних 7 і 8.

Запуск:  PYTHONUTF8=1 ..\..\lab7\.venv\Scripts\python.exe scripts\prepare_cats_dogs_2000.py
Далі:    залити data/cats_dogs_small.zip у MyDrive/dl_lab10/
"""
import shutil
import zipfile
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parent.parent
RAW = LAB_ROOT.parent / "lab7" / "data" / "dogs_vs_cats_raw" / "train"
OUT = LAB_ROOT / "data" / "cats_dogs_small"
ZIP = LAB_ROOT / "data" / "cats_dogs_small.zip"

CLASSES = {"cats": "cat", "dogs": "dog"}
SPLITS = {
    "train": (0, 2000),
    "validation": (2000, 2500),
    "test": (2500, 3000),
}


def create_directory(root):
    """Чиста структура каталогів: root/<спліт>/<клас>."""
    if root.exists():
        shutil.rmtree(root)
    for split in SPLITS:
        for cls in CLASSES:
            (root / split / cls).mkdir(parents=True)


def copy_images(split, cls, start, end):
    """Копіює файли <prefix>.<start..end-1>.jpg у root/<split>/<cls>."""
    prefix = CLASSES[cls]
    dst = OUT / split / cls
    copied = 0
    for i in range(start, end):
        src = RAW / f"{prefix}.{i}.jpg"
        if not src.exists():
            raise FileNotFoundError(f"немає {src}")
        shutil.copy(src, dst / src.name)
        copied += 1
    return copied


def main():
    if not RAW.is_dir():
        raise SystemExit(
            f"немає {RAW}\n"
            "Повний набір Dogs vs Cats лежить у лабораторній 7; "
            "завантажити можна з https://www.kaggle.com/c/dogs-vs-cats"
        )

    create_directory(OUT)

    total = 0
    print(f"{'набір':<12} {'клас':<6} {'індекси':<14} {'файлів':>7}")
    print("-" * 44)
    for split, (start, end) in SPLITS.items():
        for cls in CLASSES:
            n = copy_images(split, cls, start, end)
            total += n
            print(f"{split:<12} {cls:<6} {start}-{end - 1:<9} {n:>7}")
    print("-" * 44)
    print(f"{'РАЗОМ':<12} {'':<6} {'':<14} {total:>7}")

    # Перевірка, що набори справді не перетинаються.
    seen = {}
    for split in SPLITS:
        for cls in CLASSES:
            for p in (OUT / split / cls).iterdir():
                if p.name in seen:
                    raise SystemExit(f"{p.name} є і в {seen[p.name]}, і в {split}")
                seen[p.name] = split
    print(f"\nперевірено: усі {len(seen)} файлів унікальні, набори не перетинаються")

    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(OUT.rglob("*.jpg")):
            z.write(p, p.relative_to(OUT))
    print(f"\n{ZIP} — {ZIP.stat().st_size / 1e6:.0f} МБ")
    print("Залийте його у MyDrive/dl_lab10/ (ноутбук Завдання 3 розпакує сам).")


if __name__ == "__main__":
    main()

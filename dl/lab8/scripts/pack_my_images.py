r"""Збирає власні тестові зображення з ЛР7 у my_images.zip для завантаження в Colab.

Пункт 5 вимагає 5–10 тестових зображень, яких не було в навчальному, тестовому
чи валідаційному наборі. Беремо ті самі 36 зображень з Wikimedia Commons, що в
лабораторній 7: так порівняння «мережа з нуля проти перенесення навчання»
відбувається на однакових даних. Атрибуція — lab7/results/image_sources.md.

Запуск:  PYTHONUTF8=1 ..\lab7\.venv\Scripts\python.exe scripts\pack_my_images.py
Далі:    залити my_images.zip у MyDrive/dl_lab8/
"""
import zipfile
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parent.parent
SRC = LAB_ROOT.parent / "lab7" / "my_images"
FOLDERS = ("task4_cats_dogs", "task4_hard", "task4_cropped")
OUT = LAB_ROOT / "my_images.zip"
EXTS = {".jpg", ".jpeg", ".png"}


def main():
    if not SRC.is_dir():
        raise SystemExit(f"немає {SRC} — зображення беруться з лабораторної 7")

    written = 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for folder in FOLDERS:
            d = SRC / folder
            if not d.is_dir():
                raise SystemExit(f"немає каталогу {d}")
            files = sorted(p for p in d.iterdir() if p.suffix.lower() in EXTS)
            for p in files:
                # У zip шлях без my_images/, бо в Colab розпаковується вже в /content/my_images.
                z.write(p, f"{folder}/{p.name}")
            written += len(files)
            print(f"{folder}: {len(files)} файлів")

    print(f"\n{OUT} — {written} зображень, {OUT.stat().st_size / 1e6:.1f} МБ")
    print("Залийте його у MyDrive/dl_lab8/ (ноутбук розпакує сам).")


if __name__ == "__main__":
    main()

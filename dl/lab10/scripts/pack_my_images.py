r"""Збирає всі власні тестові зображення в один my_images.zip для Colab.

Що куди:

    horses_humans/        12 фото з ЛР7 — Завдання 2 (коні-люди)
    cats_dogs/            20 звичайних  — Завдання 3
    cats_dogs_hard/       10 складних   — Завдання 3
    cats_dogs_cropped/     6 обрізаних  — Завдання 3
    rps/rock|paper|scissors/  ваші фото рук — Завдання 4, пункт 16

Перші чотири папки беруться з лабораторної 7: так порівняння «ЛР7 проти ЛР8
проти ЛР10» відбувається на однакових даних. Атрибуція зображень —
lab7/results/image_sources.md.

Фотографії рук для Завдання 4 треба зняти самостійно й покласти у
lab10/my_images/rps/<клас>/ — їх ніде взяти, це вимога умови.

Запуск:  PYTHONUTF8=1 ..\..\lab7\.venv\Scripts\python.exe scripts\pack_my_images.py
Далі:    залити my_images.zip у MyDrive/dl_lab10/
"""
import zipfile
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parent.parent
LAB7 = LAB_ROOT.parent / "lab7" / "my_images"
LOCAL = LAB_ROOT / "my_images"
OUT = LAB_ROOT / "my_images.zip"
EXTS = {".jpg", ".jpeg", ".png"}

# призначення в архіві -> тека-джерело в ЛР7
FROM_LAB7 = {
    "horses_humans": LAB7 / "task1_horses_humans",
    "cats_dogs": LAB7 / "task4_cats_dogs",
    "cats_dogs_hard": LAB7 / "task4_hard",
    "cats_dogs_cropped": LAB7 / "task4_cropped",
}
RPS_CLASSES = ("rock", "paper", "scissors")


def images(folder):
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in EXTS)


def main():
    entries = []   # (шлях у архіві, файл на диску)
    missing = []

    for name, src in FROM_LAB7.items():
        if not src.is_dir():
            missing.append(f"{src} (з лабораторної 7)")
            continue
        files = images(src)
        entries += [(f"{name}/{p.name}", p) for p in files]
        print(f"{name:<22} {len(files):>3} файлів   <- {src}")

    print()
    rps_total = 0
    for cls in RPS_CLASSES:
        d = LOCAL / "rps" / cls
        d.mkdir(parents=True, exist_ok=True)
        files = images(d)
        rps_total += len(files)
        status = "" if files else "   <- ПОРОЖНЯ, потрібні ваші фото"
        print(f"{'rps/' + cls:<22} {len(files):>3} файлів{status}")
        entries += [(f"rps/{cls}/{p.name}", p) for p in files]

    if missing:
        raise SystemExit("немає джерел:\n  " + "\n  ".join(missing))

    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for arc, path in entries:
            z.write(path, arc)

    print(f"\n{OUT} — {len(entries)} зображень, {OUT.stat().st_size / 1e6:.1f} МБ")

    if rps_total == 0:
        print(
            "\nУВАГА: фотографій рук для Завдання 4 ще немає.\n"
            "Зніміть по 3-4 фото кожного жесту (камінь, ножиці, папір) і покладіть у\n"
            f"  {LOCAL / 'rps' / '<клас>'}\n"
            "Потім запустіть цей скрипт ще раз і перезалийте архів.\n"
            "Решта завдань від цього не залежить — архів уже придатний для Завдань 2 і 3."
        )
    print("\nЗалийте my_images.zip у MyDrive/dl_lab10/")


if __name__ == "__main__":
    main()

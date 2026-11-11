r"""Розпаковує зіпи з Colab (results/incoming/*.zip) у results/ і перевіряє комплектність.

Кожен ноутбук останньою клітинкою віддає lab8_taskN_results.zip. Кладемо їх у
results/incoming/ і запускаємо цей скрипт.

Запуск:  PYTHONUTF8=1 ..\lab7\.venv\Scripts\python.exe scripts\unpack_results.py
"""
import zipfile
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parent.parent
RESULTS = LAB_ROOT / "results"
INCOMING = RESULTS / "incoming"
RAW = RESULTS / "raw"

EXPECTED = {
    "task1": "VGG16",
    "task2": "InceptionV3",
    "task3": "ResNet50",
    "task4": "MobileNetV2",
    "task5": "порівняльний аналіз",
}


def main():
    INCOMING.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)

    zips = sorted(INCOMING.glob("*.zip"))
    if not zips:
        print(f"У {INCOMING} немає зіпів — покладіть туди lab8_taskN_results.zip з Colab.")
    for z_path in zips:
        with zipfile.ZipFile(z_path) as z:
            members = z.namelist()
            # Шляхи в архіві відносні до results/, тому розпаковуємо саме туди.
            z.extractall(RESULTS)
        print(f"{z_path.name}: {len(members)} файлів розпаковано")

    print("\nСтан результатів:")
    missing = []
    for task, title in EXPECTED.items():
        p = RAW / f"{task}.json"
        if p.exists():
            size_kb = p.stat().st_size / 1024
            pngs = sorted(x.name for x in RESULTS.glob(f"{task}_*.png"))
            print(f"  [+] {task} ({title}): {p.name} {size_kb:.0f} КБ, "
                  f"{len(pngs)} графік(ів)")
            for n in pngs:
                print(f"        {n}")
        else:
            missing.append(task)
            print(f"  [ ] {task} ({title}): НЕМАЄ {p.name}")

    if missing:
        print(f"\nЩе не виконано: {', '.join(missing)}")
    else:
        print("\nУсі п'ять наборів результатів на місці — можна запускати collect_results.py")


if __name__ == "__main__":
    main()

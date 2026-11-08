r"""Розпаковує зіпи з Colab (results/incoming/*.zip) у results/ і перевіряє комплектність.

Кожен ноутбук останньою клітинкою віддає lab10_taskN_results.zip. Кладемо їх у
results/incoming/ і запускаємо цей скрипт.

Запуск:  PYTHONUTF8=1 ..\..\lab7\.venv\Scripts\python.exe scripts\unpack_results.py
"""
import zipfile
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parent.parent
RESULTS = LAB_ROOT / "results"
INCOMING = RESULTS / "incoming"
RAW = RESULTS / "raw"

EXPECTED = {
    "task2": "коні-люди: роздільна здатність, аугментація, донавчання",
    "task3": "коти-собаки, скорочений набір",
    "task4": "Rock-Paper-Scissors",
}
# Завдання 1 і 5 здаються самими ноутбуками зі збереженими виводами: умова
# забороняє додавати клітинки, тож експортувати JSON із них нема звідки.
NOTEBOOK_ONLY = {
    "Task1_transfer_learning.ipynb": "Завдання 1 (коні-люди, перенесення навчання)",
    "Task5_sign_language.ipynb": "Завдання 5 (мова жестів)",
}


def main():
    INCOMING.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)

    zips = sorted(INCOMING.glob("*.zip"))
    if not zips:
        print(f"У {INCOMING} немає зіпів — покладіть туди lab10_taskN_results.zip з Colab.")
    for z_path in zips:
        with zipfile.ZipFile(z_path) as z:
            # Шляхи в архіві відносні до results/, тому розпаковуємо саме туди.
            members = z.namelist()
            z.extractall(RESULTS)
        print(f"{z_path.name}: {len(members)} файлів розпаковано")

    print("\nСтан результатів:")
    missing = []
    for task, title in EXPECTED.items():
        p = RAW / f"{task}.json"
        if p.exists():
            pngs = sorted(x.name for x in RESULTS.glob(f"{task}_*.png"))
            print(f"  [+] {task} ({title}): {p.stat().st_size / 1024:.0f} КБ, "
                  f"{len(pngs)} графік(ів)")
            for n in pngs:
                print(f"        {n}")
        else:
            missing.append(task)
            print(f"  [ ] {task} ({title}): НЕМАЄ {p.name}")

    import nbformat

    print()
    for name, title in NOTEBOOK_ONLY.items():
        path = LAB_ROOT / "notebooks" / name
        if not path.exists():
            print(f"  [ ] {title}: немає {name}")
            missing.append(name)
            continue
        has_outputs = any(c.get("outputs") for c in nbformat.read(path, as_version=4).cells)
        state = ("ноутбук зі збереженими виводами" if has_outputs
                 else "ноутбук БЕЗ виводів — перезавантажте з Colab")
        print(f"  [{'+' if has_outputs else ' '}] {title}: {state}")
        if not has_outputs:
            missing.append(name)

    if missing:
        print(f"\nЩе не виконано: {', '.join(missing)}")
    else:
        print("\nУсі набори результатів на місці — можна запускати collect_results.py")


if __name__ == "__main__":
    main()

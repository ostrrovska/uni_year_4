r"""Перераховує мітки власних зображень у results/raw/task3.json.

Навіщо: у першій версії predict_folder клас брався як
`p.stem.lower().startswith('cat')`, а файли обрізаного набору названі
`crop_cat_...` / `crop_dog_...`. Жоден із них не починався на 'cat', тож усім
шістьом приписувався клас «собака»: чотири коти пішли в помилки, два собаки
вгадалися випадково. Через це обрізаний набір показував 2 з 6 замість 6 з 6.

Передбачення моделі при цьому були правильні й збережені в JSON (`prob_dog`),
тож перерахунок точний — перезапускати навчання не треба. Код генератора
виправлено в scripts/nb_cells_t3.py; цей скрипт лагодить уже зібраний
результат.

Запуск:  PYTHONUTF8=1 ..\..\lab7\.venv\Scripts\python.exe scripts\fix_own_labels.py
"""
import json
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parent.parent
RAW = LAB_ROOT / "results" / "raw" / "task3.json"


def actual_class(file_name):
    """0 = кіт, 1 = собака. crop_ прибирається перед перевіркою префікса."""
    stem = Path(file_name).stem.lower().replace("crop_", "")
    return 0 if stem.startswith("cat") else 1


def main():
    data = json.loads(RAW.read_text(encoding="utf-8"))
    changed = []
    summary = {}

    for folder, records in data["own_images"].items():
        for r in records:
            want = actual_class(r["file"])
            pred = 1 if r["prob_dog"] > 0.5 else 0
            new_actual = "собака" if want else "кіт"
            new_correct = pred == want
            if new_actual != r["actual"] or new_correct != r["correct"]:
                changed.append((folder, r["file"], r["actual"], new_actual,
                                r["correct"], new_correct))
            r["actual"] = new_actual
            r["correct"] = new_correct
        good = sum(r["correct"] for r in records)
        summary[folder] = [good, len(records)]

    if not changed:
        print("мітки вже правильні, нічого не змінено")
        return

    print(f"виправлено записів: {len(changed)}\n")
    for folder, name, old_a, new_a, old_c, new_c in changed:
        print(f"  {folder}/{name}")
        print(f"      мітка {old_a} -> {new_a}, "
              f"{'помилка' if not old_c else 'вірно'} -> "
              f"{'вірно' if new_c else 'помилка'}")

    print("\nпідсумок:")
    for folder, (good, total) in summary.items():
        was = data["own_summary"].get(folder)
        mark = "" if was == [good, total] else f"   (було {was[0]}/{was[1]})"
        print(f"  {folder:<20} {good}/{total}{mark}")

    data["own_summary"] = summary
    RAW.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{RAW} оновлено")


if __name__ == "__main__":
    main()

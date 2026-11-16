r"""Складання results/summary.md із JSON-ів, привезених із Colab.

Усе, що потрапляє у звіт, береться звідси, а не переписується руками з виводу
ноутбуків. Якщо якогось ноутбука ще немає — його розділ просто пропускається.

Запуск:  PYTHONUTF8=1 ..\..\lab7\.venv\Scripts\python.exe scripts\collect_results.py
"""
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS = PROJECT_ROOT / "results"
RAW = RESULTS / "raw"


def load(name):
    path = RAW / f"{name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def table(headers, rows):
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        out.append("| " + " | ".join(str(c) for c in row) + " |")
    return out


def section_dataset(nb01):
    lines = ["## Набір даних", "",
             f"Джерело: {nb01['source']}", "",
             *table(["Показник", "Значення"], [
                 ("тек у архіві", nb01.get("n_folders", "?")),
                 ("класів після об'єднання", nb01["n_classes_total"]),
                 ("зображень до очищення", nb01["n_images_raw"]),
                 ("зображень після очищення", nb01["n_images_clean"]),
                 ("битих файлів", nb01["n_corrupt"]),
                 ("точних дублікатів", nb01["n_exact_duplicates"]),
                 ("візуальних дублікатів", nb01["n_near_duplicates"]),
                 ("дисбаланс (макс:мін)", f"{nb01['imbalance_ratio_all']:.1f}:1"),
                 ("поріг трека top-15", f"{nb01['top15_threshold']} зображень"),
                 ("коротка сторона після обробки", f"{nb01['target_short_side']} px"),
             ]), ""]

    if nb01.get("merged_classes"):
        lines += ["Художники, що лежали в кількох теках і були об'єднані в один клас:", ""]
        for class_name, names in nb01["merged_classes"].items():
            lines.append(f"- **{class_name}** — теки: " +
                         ", ".join(f"`{n}`" for n in names))
        lines.append("")

    if nb01.get("names_fixed_by_similarity"):
        lines += ["Назви тек, зіпсовані перекодуванням (mojibake), зіставлені з "
                  "`artists.csv` за схожістю рядків:", "",
                  *table(["Тека в архіві", "Рядок у CSV", "Подібність"],
                         [(f"`{a}`", b, f"{r:.2f}")
                          for a, b, r in nb01["names_fixed_by_similarity"]]), ""]

    if nb01.get("names_fixed_by_normalisation"):
        lines += ["Імена, що збіглися лише після нормалізації Unicode:", ""]
        lines += [f"- тека `{a}` ↔ CSV `{b}`"
                  for a, b in nb01["names_fixed_by_normalisation"]]
        lines.append("")

    for key, title in (("split_sizes_all", "усі класи"),
                       ("split_sizes_top15", "трек top-15")):
        sizes = nb01.get(key, {})
        lines += [f"Поділ ({title}): " + ", ".join(
            f"{k} — {v}" for k, v in sizes.items()), ""]

    top15 = set(nb01["top15"])
    top = [c for c in nb01["class_counts"]
           if c.get("class_dir", c.get("class")) in top15]
    lines += ["### Класи основного треку", "",
              *table(["Художник", "Усього", "Після очищення", "Жанр", "Національність"],
                     [(c["artist"], c["n_files"], c["n_clean"], c["genre"],
                       c["nationality"]) for c in top]), ""]
    return lines


def section_runs(title, runs):
    rows = []
    for name, r in sorted(runs.items(),
                          key=lambda kv: -kv[1]["test_accuracy"]):
        rows.append((name, r["title"], r["n_classes"], f"{r['params']:,}",
                     r["epochs_run"], f"{r['best_val_accuracy']:.4f}",
                     f"{r['test_accuracy']:.4f}", f"{r['test_top3_accuracy']:.4f}",
                     f"{r['overfit_gap']:+.3f}", f"{r['seconds'] / 60:.1f}"))
    return [f"## {title}", "",
            *table(["Експеримент", "Опис", "Класів", "Параметрів", "Епох",
                    "Val acc", "Test acc", "Test top-3", "Розрив", "Хв"], rows), ""]


def section_evaluation(nb04):
    lines = ["## Оцінка найкращої моделі", "",
             f"Модель: **{nb04['best_model']}** — {nb04['best_title']}", "",
             *table(["Метрика", "Значення"], [
                 ("accuracy", f"{nb04['test_accuracy']:.4f}"),
                 ("top-3 accuracy", f"{nb04['test_top3_accuracy']:.4f}"),
                 ("macro precision", f"{nb04['macro']['precision']:.4f}"),
                 ("macro recall", f"{nb04['macro']['recall']:.4f}"),
                 ("macro F1", f"{nb04['macro']['f1']:.4f}"),
                 ("weighted F1", f"{nb04['weighted']['f1']:.4f}"),
                 ("помилок", nb04["n_errors"]),
                 ("середня впевненість: правильні",
                  f"{nb04['mean_confidence_correct']:.3f}"),
                 ("середня впевненість: помилкові",
                  f"{nb04['mean_confidence_wrong']:.3f}"
                  if nb04.get("mean_confidence_wrong") else "—"),
                 ("на зовнішніх зображеннях",
                  f"{nb04['external_accuracy']:.3f}"
                  if nb04.get("external_accuracy") is not None else "не перевірено"),
             ]), ""]

    f1 = nb04["per_class_f1"]
    support = nb04["support"]
    lines += ["### F1 за класами", "",
              *table(["Художник", "F1", "Тестових зображень"],
                     [(name, f"{value:.3f}", support.get(name, "?"))
                      for name, value in sorted(f1.items(), key=lambda kv: -kv[1])]),
              ""]

    if nb04.get("most_confused"):
        lines += ["### Найчастіші плутанини", "",
                  *table(["Насправді", "Прогноз", "Випадків", "Частка класу"],
                         [(c["насправді"], c["прогноз"], c["випадків"],
                           f"{c['частка класу']:.2f}")
                          for c in nb04["most_confused"][:10]]), ""]
    return lines


def section_external(nb04):
    """Зображення з іншого джерела — те, чого модель не бачила взагалі."""
    lines = ["## Зображення, яких модель не бачила ніколи", "",
             "Роботи тих самих художників із Wikimedia Commons і Вікіпедії — "
             "інша зйомка, інший баланс кольору, інше кадрування. Джерела "
             "кожного файла — у `results/image_sources.md`.", ""]

    rows = [("точність", f"{nb04['external_accuracy']:.3f}"),
            ("top-3 точність", f"{nb04['external_top3_accuracy']:.3f}"),
            ("для порівняння: на тестовій вибірці набору",
             f"{nb04['test_accuracy']:.3f}"),
            ("для порівняння: top-3 на тестовій вибірці",
             f"{nb04['test_top3_accuracy']:.3f}")]
    lines += table(["Показник", "Значення"], rows) + [""]

    path = RAW / "nb04_external.csv"
    if path.exists():
        import csv

        with open(path, encoding="utf-8") as f:
            records = list(csv.DictReader(f))
        wrong = [r for r in records if r.get("вгадано", "").strip() != "True"]
        if wrong:
            lines += [f"Помилки ({len(wrong)} з {len(records)}):", "",
                      *table(["Файл", "Насправді", "Прогноз", "Впевненість"],
                             [(f"`{r['файл']}`", r["насправді"], r["прогноз"],
                               r["впевненість"]) for r in wrong]), ""]
    return lines


def section_headline(nb02, nb03, nb04):
    """Головне порівняння двох підходів — те, заради чого робилися обидві серії."""
    runs = {}
    for payload in (nb02, nb03):
        runs.update(payload.get("runs", {}))
    top15 = {k: v for k, v in runs.items() if v["n_classes"] == 15}
    if not top15:
        return []

    scratch = {k: v for k, v in top15.items() if k.startswith("a")}
    transfer = {k: v for k, v in top15.items() if k.startswith("b")}
    if not (scratch and transfer):
        return []

    best_scratch = max(scratch, key=lambda k: scratch[k]["best_val_accuracy"])
    best_transfer = max(transfer, key=lambda k: transfer[k]["best_val_accuracy"])
    gain = (transfer[best_transfer]["test_accuracy"]
            - scratch[best_scratch]["test_accuracy"])

    lines = ["## Порівняння двох підходів", "",
             "В обох випадках переможець обраний за **перевірочною** вибіркою; "
             "тестова використана лише для підсумкового вимірювання.", "",
             *table(["Підхід", "Модель", "Val acc", "Test acc", "Test top-3"],
                    [("мережа з нуля", best_scratch,
                      f"{scratch[best_scratch]['best_val_accuracy']:.4f}",
                      f"{scratch[best_scratch]['test_accuracy']:.4f}",
                      f"{scratch[best_scratch]['test_top3_accuracy']:.4f}"),
                     ("перенесення навчання", best_transfer,
                      f"{transfer[best_transfer]['best_val_accuracy']:.4f}",
                      f"{transfer[best_transfer]['test_accuracy']:.4f}",
                      f"{transfer[best_transfer]['test_top3_accuracy']:.4f}")]),
             "", f"**Приріст від перенесення навчання: {gain:+.4f}** "
                 f"на тестовій вибірці.", ""]

    # Стандартна похибка частки: без неї різниці в кілька тисячних виглядають
    # значущими, хоча такими не є.
    if nb04:
        import math

        n = sum(nb04["support"].values())
        acc = nb04["test_accuracy"]
        se = math.sqrt(acc * (1 - acc) / n)
        lines += [f"Стандартна похибка оцінки точності на {n} тестових "
                  f"зображеннях — близько **{se:.4f}**. Різниці між прогонами, "
                  f"менші за це значення, лежать у межах шуму.", ""]
    return lines


def section_long_tail(nb05):
    """Розділ про рідкісні класи: ноутбук 05."""
    methods = nb05.get("methods", {})
    if not methods:
        return []

    def display(class_dir):
        return class_dir.replace("_", " ")

    ordered = sorted(methods.values(),
                     key=lambda m: m["band_recall"]["tail"], reverse=True)
    bands = nb05.get("bands", {})
    members = bands.get("members", {})
    lines = [
        "## Рідкісні художники (ноутбук 05)", "",
        "Головний показник тут — не загальна точність, а **середня повнота за "
        "класами смуги рідкісних**: класів із малою кількістю картин, яких "
        "загальна точність не помічає.", "",
        *table(["Смуга", "Класів", "Межа за розміром навчальної вибірки"], [
            ("численні", len(members.get("head", [])),
             f"≥ {bands.get('head_min', '?')}"),
            ("середні", len(members.get("mid", [])),
             f"{bands.get('tail_max', '?')}…{bands.get('head_min', 0) - 1}"),
            ("рідкісні", len(members.get("tail", [])),
             f"< {bands.get('tail_max', '?')}"),
        ]), "",
        f"Опорна модель: **{nb05.get('reference_run', '?')}** (з ноутбука 03).", "",
        *table(["Метод", "Що зроблено", "Спосіб", "Accuracy", "Збалансована",
                "macro F1", "Численні", "Середні", "Рідкісні"],
               [(m["name"], m["title"], m["kind"],
                 f"{m['accuracy']:.4f}", f"{m['balanced_accuracy']:.4f}",
                 f"{m['macro_f1']:.4f}", f"{m['band_recall']['head']:.3f}",
                 f"{m['band_recall']['mid']:.3f}", f"{m['band_recall']['tail']:.3f}")
                for m in ordered]), "",
    ]

    shots = nb05.get("few_shot", [])
    if shots:
        lines += [
            "### Скільки зразків потрібно прототипові", "",
            *table(["Зразків на клас", "Усі класи", "Рідкісні", "Численні"],
                   [(row["зразків на клас"], row["усі класи"], row["рідкісні"],
                     row["численні"]) for row in shots]), "",
        ]

    views = [r for r in nb05.get("view_choice", []) if r.get("смуга") == "рідкісні"]
    if views:
        lines += [
            "### Який масштаб обрано для рідкісних класів", "",
            "Вибір зроблено за **перевірочною** вибіркою.", "",
            *table(["Художник", "У навчальній", "Перевірочна: ціле",
                    "Перевірочна: вирізки", "Обрано"],
                   [(r["художник"], r["у навчальній"], r["перевірочна: ціле"],
                     r["перевірочна: вирізки"], r["обрано"]) for r in views]), "",
        ]

    distinct = nb05.get("distinctiveness", [])
    if distinct:
        top = sorted(distinct, key=lambda r: r["виразність"], reverse=True)[:8]
        lines += [
            "### Виразність стилю (ознаки ImageNet, без навчання на мітках)", "",
            *table(["Художник", "У навчальній", "Смуга", "Виразність",
                    "Повнота опорної"],
                   [(r["художник"], r["у навчальній"], r["смуга"],
                     r["виразність"], r["повнота опорної"]) for r in top]), "",
        ]
    return lines


def main():
    nb01, nb02, nb03, nb04, nb05 = (
        load(n) for n in ("nb01", "nb02", "nb03", "nb04", "nb05"))
    if not any((nb01, nb02, nb03, nb04, nb05)):
        print(f"у {RAW} немає жодного nbNN.json — спершу scripts/unpack_results.py")
        return

    lines = ["# Результати прогонів", "",
             "Файл складається `scripts/collect_results.py` з JSON-ів, які "
             "ноутбуки записують у `results/raw/`. Руками його не редагують.", ""]

    if nb01:
        lines += section_dataset(nb01)
    if nb02 and nb02.get("runs"):
        lines += section_runs("Мережі, навчені з нуля (ноутбук 02)", nb02["runs"])
    if nb03 and nb03.get("runs"):
        transfer = {k: v for k, v in nb03["runs"].items() if k.startswith("b")}
        if transfer:
            lines += section_runs("Перенесення навчання (ноутбук 03)", transfer)
    if nb04:
        lines += section_evaluation(nb04)

    if nb04:
        lines += section_external(nb04)
    if nb02 and nb03:
        lines += section_headline(nb02, nb03, nb04)
    if nb05:
        lines += section_long_tail(nb05)

    images = sorted(p.name for p in RESULTS.glob("*.png"))
    if images:
        lines += ["## Графіки", ""] + [f"- `{name}`" for name in images] + [""]

    out = RESULTS / "summary.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"записано {out} ({len(lines)} рядків)")


if __name__ == "__main__":
    main()

"""Збір усіх чисел із results/raw/*.json у results/metrics.json і results/summary.md.

Жодне число не вписується руками — усе береться з виводів виконаних ноутбуків.
"""
import json
import platform
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parent.parent
RAW = LAB_ROOT / "results" / "raw"
RESULTS = LAB_ROOT / "results"


def load(name):
    p = RAW / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def history_table(hist, title):
    keys = [k for k in ("accuracy", "loss", "val_accuracy", "val_loss") if k in hist]
    head = "| Епоха | " + " | ".join(keys) + " |"
    sep = "|---" * (len(keys) + 1) + "|"
    rows = [head, sep]
    for i in range(len(hist[keys[0]])):
        rows.append(f"| {i + 1} | " + " | ".join(f"{hist[k][i]:.4f}" for k in keys) + " |")
    return f"**{title}**\n\n" + "\n".join(rows)


def predictions_table(tasks):
    """Таблиця передбачень на власних зображеннях: колонка на кожну модель."""
    names = [t for t, d in tasks if d]
    files = []
    for _, d in tasks:
        if d:
            for r in d["own_images"]:
                if r["file"] not in files:
                    files.append(r["file"])
    head = "| Файл | Правильний клас | " + " | ".join(f"{n}: p(human) → клас" for n in names) + " |"
    rows = [head, "|---" * (len(names) + 2) + "|"]
    for f in sorted(files):
        exp = next((r["expected"] for _, d in tasks if d
                    for r in d["own_images"] if r["file"] == f), None)
        cells = []
        for _, d in tasks:
            if not d:
                continue
            r = next((x for x in d["own_images"] if x["file"] == f), None)
            if r is None:
                cells.append("—")
            else:
                mark = "" if r["correct"] is None else (" ✔" if r["correct"] else " ✘")
                cells.append(f"{r['prob_human']:.3f} → {r['predicted']}{mark}")
        rows.append(f"| `{f}` | {exp or 'людина+кінь'} | " + " | ".join(cells) + " |")
    return "\n".join(rows)


def accuracy_of(d):
    known = [r for r in d["own_images"] if r.get("correct") is not None]
    return sum(r["correct"] for r in known), len(known)


def cat_dog_table(records, prob_key="prob_dog"):
    rows = ["| Файл | Правильний клас | p(dog) | Передбачено | Вірно |", "|---|---|---|---|---|"]
    for r in records:
        rows.append(f"| `{r['file']}` | {r['expected']} | {r[prob_key]:.3f} | "
                    f"{r['predicted']} | {'✔' if r['correct'] else '✘'} |")
    return "\n".join(rows)


def main():
    t0, t1, t2, t3, t4 = (load(f"task{i}.json") for i in range(5))
    probe = load("timing_probe.json")
    metrics = {k: v for k, v in
               {"task0": t0, "task1": t1, "task2": t2, "task3": t3, "task4": t4,
                "timing_probe": probe}.items() if v}
    (RESULTS / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2),
                                          encoding="utf-8")

    md = ["# Лабораторна 7 — зібрані результати", "",
          "Усі числа взяті з виконаних ноутбуків (`results/raw/*.json`), нічого не оцінювалось «на око».",
          "", f"Машина: {platform.processor() or platform.machine()}, "
          f"навчання на CPU (TensorFlow на Windows не використовує GPU, див. `environment.md`).", ""]

    # ---------------------------------------------------------------- 1 і 2
    if t1:
        md += ["## Завдання 1 — валідація, вхід 300×300 (пункти 1–13)", "",
               f"- навчальний набір: **{t1['train_samples']}** зображень, "
               f"валідаційний: **{t1['validation_samples']}** (`{t1['class_indices']}`)",
               f"- параметрів у моделі: **{t1['total_params']:,}**".replace(",", " "),
               f"- час навчання: **{t1['train_time_sec']:.0f} с** "
               f"({t1['train_time_sec'] / 60:.1f} хв), епох: {t1['epochs_done']}",
               f"- остання епоха: accuracy **{t1['history']['accuracy'][-1]:.4f}**, "
               f"val_accuracy **{t1['history']['val_accuracy'][-1]:.4f}**",
               f"- найкраща val_accuracy: **{max(t1['history']['val_accuracy']):.4f}** "
               f"(епоха {t1['history']['val_accuracy'].index(max(t1['history']['val_accuracy'])) + 1})",
               "", history_table(t1["history"], "Історія навчання, завдання 1"), ""]
    if t2:
        md += ["## Завдання 2 — вхід 150×150, без 4-ї та 5-ї пар Conv+Pool (пункти 14–19)", "",
               f"- параметрів у моделі: **{t2['total_params']:,}**".replace(",", " "),
               f"- час навчання: **{t2['train_time_sec']:.0f} с** ({t2['train_time_sec'] / 60:.1f} хв)",
               f"- остання епоха: accuracy **{t2['history']['accuracy'][-1]:.4f}**, "
               f"val_accuracy **{t2['history']['val_accuracy'][-1]:.4f}**",
               "", history_table(t2["history"], "Історія навчання, завдання 2"), ""]
    if t1 and t2:
        c1, c2 = t1["history"], t2["history"]
        md += ["### Порівняння завдання 1 (300×300) і завдання 2 (150×150)", "",
               "| Показник | Завдання 1 (300×300) | Завдання 2 (150×150) |", "|---|---|---|",
               f"| Параметрів | {t1['total_params']:,} | {t2['total_params']:,} |".replace(",", " "),
               f"| Час навчання, с | {t1['train_time_sec']:.0f} | {t2['train_time_sec']:.0f} |",
               f"| accuracy (остання епоха) | {c1['accuracy'][-1]:.4f} | {c2['accuracy'][-1]:.4f} |",
               f"| val_accuracy (остання епоха) | {c1['val_accuracy'][-1]:.4f} | {c2['val_accuracy'][-1]:.4f} |",
               f"| val_accuracy (найкраща) | {max(c1['val_accuracy']):.4f} | {max(c2['val_accuracy']):.4f} |",
               f"| loss (остання) | {c1['loss'][-1]:.4f} | {c2['loss'][-1]:.4f} |",
               f"| val_loss (остання) | {c1['val_loss'][-1]:.4f} | {c2['val_loss'][-1]:.4f} |",
               f"| Розрив accuracy − val_accuracy | {c1['accuracy'][-1] - c1['val_accuracy'][-1]:+.4f} "
               f"| {c2['accuracy'][-1] - c2['val_accuracy'][-1]:+.4f} |", ""]

    # ---------------------------------------------- власні зображення 0/1/2
    tasks = [("база без валідації", t0), ("завдання 1 (300)", t1), ("завдання 2 (150)", t2)]
    if any(d for _, d in tasks):
        md += ["### Власні зображення (пункти 1, 13, 18)", "",
               "Клас 1 = *humans*, клас 0 = *horses*. Файли `both_*` містять і людину, і коня — "
               "правильної відповіді для них немає, вони не входять у підрахунок.", ""]
        for name, d in tasks:
            if d:
                ok, tot = accuracy_of(d)
                md.append(f"- **{name}**: правильно {ok} з {tot}")
        md += ["", predictions_table(tasks), ""]

    # ---------------------------------------------------------------- 3
    if t3:
        ep = t3["epochs_done"]
        md += ["## Завдання 3 — Happy or Sad (пункт 20)", "",
               f"- набір: **{t3['samples']}** зображень (`{t3['class_indices']}`), параметрів: "
               f"**{t3['total_params']:,}**".replace(",", " "),
               f"- порога 99,9 % досягнуто на **епосі {ep}** з 15 "
               f"(accuracy {t3['history']['accuracy'][-1]:.4f}), callback зупинив навчання",
               "- повідомлення callback: «Досягнуто 99,9% точності, тому скасовуємо навчання!»",
               "- остання клітинка базового ноутбука (`hist.model.metrics_names`) у Keras 3 "
               "друкує хибне попередження «Use 'accuracy' as metric», бо `metrics_names` "
               "заповнюється лише після `evaluate`; метрика задана правильно, клітинку не змінювали.",
               "", history_table(t3["history"], "Історія навчання, завдання 3"), ""]

    # ---------------------------------------------------------------- 4
    if t4:
        s = t4["subset"]
        a, r = t4["adam"], t4["rmsprop"]
        md += ["## Завдання 4 — Dogs vs Cats (пункти 21–26)", "",
               f"- розділення: **{s['train_per_class']}/{s['val_per_class']}/{s['test_per_class']}** "
               f"на клас ({'повний набір 70/15/15' if s['full_dataset'] else 'підмножина'})",
               f"- зображень: train **{t4['samples']['train']}**, val **{t4['samples']['val']}**, "
               f"test **{t4['samples']['test']}** (`{t4['class_indices']}`)",
               f"- параметрів у моделі: **{t4['total_params']:,}**".replace(",", " "), "",
               "### Adam vs RMSprop(0.001)", "",
               "| Показник | Adam | RMSprop(0.001) |", "|---|---|---|",
               f"| Епох виконано (EarlyStopping) | {a['epochs_done']} | {r['epochs_done']} |",
               f"| Час навчання, хв | {a['train_time_sec'] / 60:.1f} | {r['train_time_sec'] / 60:.1f} |",
               f"| accuracy (остання епоха) | {a['history']['accuracy'][-1]:.4f} "
               f"| {r['history']['accuracy'][-1]:.4f} |",
               f"| val_accuracy (найкраща) | {max(a['history']['val_accuracy']):.4f} "
               f"| {max(r['history']['val_accuracy']):.4f} |",
               f"| val_loss (найменша) | {min(a['history']['val_loss']):.4f} "
               f"| {min(r['history']['val_loss']):.4f} |",
               f"| **Test accuracy** | **{a['test_accuracy']:.4f}** | **{r['test_accuracy']:.4f}** |",
               f"| Test loss | {a['test_loss']:.4f} | {r['test_loss']:.4f} |",
               "", f"Краща модель: **{t4['best_model']}**.", "",
               history_table(a["history"], "Історія навчання, Adam"), "",
               history_table(r["history"], "Історія навчання, RMSprop(0.001)"), "",
               "### Матриця помилок на тестовому наборі", "",
               "| | передбачено cat | передбачено dog |", "|---|---|---|",
               f"| **справжній cat** | {t4['confusion_matrix'][0][0]} | {t4['confusion_matrix'][0][1]} |",
               f"| **справжній dog** | {t4['confusion_matrix'][1][0]} | {t4['confusion_matrix'][1][1]} |", ""]
        rep = RAW / "task4_classification_report.txt"
        if rep.exists():
            md += ["```", rep.read_text(encoding="utf-8").strip(), "```", ""]
        ok = sum(x["correct"] for x in t4["own_images"])
        md += [f"### Власні зображення, пункт 23 — правильно {ok} з {len(t4['own_images'])}", "",
               cat_dog_table(t4["own_images"]), ""]
        wrong = [x for x in t4["hard_images"] if not x["correct"]]
        md += [f"### Складні зображення, пункт 25 — помилок {len(wrong)} з {len(t4['hard_images'])}", "",
               cat_dog_table(t4["hard_images"]), ""]
        if t4["cropped_images"]:
            md += ["### Після обрізання, пункт 26", "",
                   "| Файл | Правильний клас | p(dog) до | p(dog) після | Було | Стало | Виправлено |",
                   "|---|---|---|---|---|---|---|"]
            for c in t4["cropped_images"]:
                src = c["file"].replace("crop_", "")
                before = next(x for x in t4["hard_images"] if x["file"] == src)
                md.append(f"| `{src}` | {c['expected']} | {before['prob_dog']:.3f} | "
                          f"{c['prob_dog']:.3f} | {before['predicted']} | {c['predicted']} | "
                          f"{'✔' if c['correct'] else '✘'} |")
            fixed = sum(c["correct"] for c in t4["cropped_images"])
            md += ["", f"Обрізання виправило **{fixed} з {len(t4['cropped_images'])}** помилок.", ""]

    md += ["## Файли", "",
           "- графіки навчання: `task*_history*.png`; сітки передбачень: `task*_predictions*.png`",
           "- матриця помилок: `task4_confusion_matrix.png`; дерево каталогів: `dir_tree.txt`",
           "- описи моделей: `raw/task*_model_summary.txt`; усі числа: `metrics.json`",
           "- джерела зображень: `image_sources.md`; середовище: `environment.md`", ""]

    (RESULTS / "summary.md").write_text("\n".join(md), encoding="utf-8")
    print("results/summary.md і results/metrics.json оновлено")
    print("зібрано завдань:", [k for k in metrics if k.startswith("task")])


if __name__ == "__main__":
    main()

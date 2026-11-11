r"""Збір усіх чисел із results/raw/*.json у results/metrics.json і results/summary.md.

Жодне число не вписується руками — усе береться з виводів виконаних ноутбуків.
Скрипт переживає відсутність частини результатів: що виконано, те й потрапляє
у звіт.

Запуск:  PYTHONUTF8=1 ..\lab7\.venv\Scripts\python.exe scripts\collect_results.py
"""
import json
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parent.parent
RESULTS = LAB_ROOT / "results"
RAW = RESULTS / "raw"

TASKS = ["task1", "task2", "task3", "task4"]

# Базові числа лабораторної 7 (та сама задача, мережа навчена з нуля).
# Джерело: dl/lab7/results/raw/task4.json.
LAB7 = {
    "title": "Своя CNN з нуля (ЛР7)",
    "params": 1212513,
    "test_accuracy": 0.8424,
    "test_accuracy_adam": 0.8267,
    "train_time_sec": 1046.4,
    "own": (16, 20),
    "hard": (4, 10),
    "cropped": (2, 6),
}

STAGES = [
    ("stage_a", "A — екстракція ознак"),
    ("stage_b", "B — заморожена база + аугментація"),
    ("stage_c", "C — донавчання"),
]


def fmt(n):
    """Число з пробілом як роздільником тисяч."""
    return f"{n:,}".replace(",", " ")


def load(name):
    p = RAW / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|---" * len(head) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def dropout_table(d):
    rows = []
    best = d["best_dropout"]
    for r in d["dropout_runs"]:
        mark = " **← обрано**" if r["p"] == best else ""
        rows.append([
            f"`{r['p']}`{mark}",
            f"{r['best_val_accuracy']:.4f}",
            r["best_epoch"],
            f"{r['final_train_accuracy']:.4f}",
            f"{r['final_val_accuracy']:.4f}",
            f"{r['overfit_gap']:+.4f}",
            f"{r['min_val_loss']:.4f}",
        ])
    return table(["Dropout", "найкраща val acc", "епоха", "train acc (остання)",
                  "val acc (остання)", "розрив train−val", "min val loss"], rows)


def stages_table(d):
    """На етапі A вчиться та сама голова, що на етапі B, а «час» — це один прогін
    бази для кешування ознак (саме він і коштує, навчання голови — секунди)."""
    head_params = d["stage_b"]["trainable_params"]
    rows = []
    for key, title in STAGES:
        s = d.get(key) or {}
        if key == "stage_a":
            params = head_params
            epochs = len(d["dropout_runs"][0]["history"]["accuracy"])
            minutes = s.get("feature_extraction_sec", 0) / 60
            time_note = f"{minutes:.1f} (кеш ознак)"
        else:
            params = s["trainable_params"]
            epochs = s["epochs_done"]
            time_note = f"{s['train_time_sec'] / 60:.1f}"
        rows.append([
            title, fmt(params), epochs, time_note,
            f"{s['test_accuracy']:.4f}", f"{s['test_loss']:.4f}",
        ])
    return table(["Етап", "навчаних параметрів", "епох", "час, хв",
                  "test accuracy", "test loss"], rows)


def history_table(hist, title):
    keys = [k for k in ("accuracy", "loss", "val_accuracy", "val_loss") if k in hist]
    rows = [[i + 1] + [f"{hist[k][i]:.4f}" for k in keys]
            for i in range(len(hist[keys[0]]))]
    return f"**{title}**\n\n" + table(["Епоха"] + keys, rows)


def own_table(d, key, caption):
    rows = []
    for r in d[key]:
        mark = "✔" if r["correct"] else "✘"
        rows.append([f"`{r['file']}`", r["expected"], f"{r['prob_dog']:.3f}",
                     r["predicted"], mark])
    correct = sum(r["correct"] for r in d[key])
    head = f"**{caption}** — правильно **{correct} з {len(d[key])}**\n\n"
    return head + table(["Файл", "правильний клас", "p(dog)", "передбачено", ""], rows)


def model_section(task, d):
    alt = d.get("stage_a_alt")
    alt_line = ""
    if alt:
        alt_line = (f"\nДодатковий замір етапу A на вході {alt['input_size']}×"
                    f"{alt['input_size']}: test accuracy **{alt['test_accuracy']:.4f}** "
                    f"(проти {d['stage_a']['test_accuracy']:.4f} на "
                    f"{d['input_size'][0]}×{d['input_size'][1]}).\n")

    stage_c = d["stage_c"]
    parts = [
        f"## {d['base']} ({task})",
        "",
        table(["Показник", "Значення"], [
            ["Вхід", f"{d['input_size'][0]}×{d['input_size'][1]}"],
            ["Параметрів усього", fmt(d["params"]["total"])],
            ["У згортковій базі", fmt(d["params"]["base"])],
            ["Навчаних на етапі B", fmt(d["params"]["trainable_stage_b"])],
            ["Навчаних на етапі C", fmt(d["params"]["trainable_stage_c"])],
            ["Розморожено з шару", f"`{stage_c['unfreeze_from']}`"],
            ["Розморожено шарів", stage_c["unfrozen_layers"]],
            ["BatchNormalization заморожено", stage_c["frozen_batchnorm"]],
            ["Розмірність вектора ознак", d["feature_dim"]],
            ["Найкращий Dropout", f"`{d['best_dropout']}`"],
            ["Файл моделі", f"`{d['model']['file']}` "
                            f"({d['model']['size_bytes'] / 1e6:.1f} МБ)"],
        ]),
        "",
        "### Пункт 4: вплив Dropout на перенавчання",
        "",
        f"Графік: `{task}_dropout_grid.png`",
        "",
        dropout_table(d),
        "",
        "### Етапи перенесення навчання",
        "",
        stages_table(d),
        alt_line,
        f"Графіки: `{task}_history_frozen.png`, `{task}_history_finetune.png`",
        "",
        history_table(d["stage_b"]["history"], "Етап B — заморожена база + аугментація"),
        "",
        history_table(d["stage_c"]["history"], "Етап C — донавчання"),
        "",
        "### Оцінка на тестовому наборі",
        "",
        f"Матриця помилок (`{task}_confusion_matrix.png`): "
        f"{d['test']['confusion_matrix']}",
        "",
        "```",
        d["test"]["classification_report"].rstrip(),
        "```",
        "",
        "### Пункт 5: власні зображення",
        "",
        own_table(d, "own_images", "20 звичайних фото"),
        "",
        own_table(d, "hard_images", "10 складних фото"),
        "",
        own_table(d, "cropped_images", "6 обрізаних складних фото"),
        "",
    ]
    return "\n".join(parts)


def comparison_section(data):
    rows = []
    rows.append([
        LAB7["title"], "150×150", fmt(LAB7["params"]), "—", "—", "—",
        f"**{LAB7['test_accuracy']:.4f}**", f"{LAB7['train_time_sec'] / 60:.1f}",
    ])
    for d in data.values():
        rows.append([
            d["base"],
            f"{d['input_size'][0]}×{d['input_size'][1]}",
            fmt(d["params"]["total"]),
            f"`{d['best_dropout']}`",
            f"{d['stage_a']['test_accuracy']:.4f}",
            f"{d['stage_b']['test_accuracy']:.4f}",
            f"**{d['stage_c']['test_accuracy']:.4f}**",
            f"{(d['stage_b']['train_time_sec'] + d['stage_c']['train_time_sec']) / 60:.1f}",
        ])
    head = ["Мережа", "вхід", "параметрів", "Dropout", "A: test", "B: test",
            "C: test", "час B+C, хв"]

    kinds = [("own_images", "20 звичайних", LAB7["own"]),
             ("hard_images", "10 складних", LAB7["hard"]),
             ("cropped_images", "6 обрізаних", LAB7["cropped"])]
    own_rows = [[LAB7["title"]] + [f"{c}/{t}" for _, _, (c, t) in kinds]]
    for d in data.values():
        own_rows.append([d["base"]] + [
            f"{sum(r['correct'] for r in d[k])}/{len(d[k])}" for k, _, _ in kinds])

    return "\n".join([
        "## Пункт 5: порівняльний аналіз",
        "",
        "Графіки: `task5_comparison_accuracy.png`, `task5_comparison_params_vs_acc.png`",
        "",
        table(head, rows),
        "",
        "### Чи покращилось розпізнавання власних зображень?",
        "",
        table(["Мережа"] + [label for _, label, _ in kinds], own_rows),
        "",
    ])


def observations(data):
    lines = []
    if not data:
        return ""

    # Dropout: де розрив train-val найбільший і найменший.
    for d in data.values():
        runs = d["dropout_runs"]
        worst = max(runs, key=lambda r: r["overfit_gap"])
        tight = min(runs, key=lambda r: abs(r["overfit_gap"]))
        lines.append(
            f"- **{d['base']}**: найбільший розрив train−val при `p={worst['p']}` "
            f"({worst['overfit_gap']:+.4f}), найменший — при `p={tight['p']}` "
            f"({tight['overfit_gap']:+.4f}); за точністю на валідації виграв "
            f"`p={d['best_dropout']}`.")

    best = max(data.values(), key=lambda d: d["stage_c"]["test_accuracy"])
    worst_model = min(data.values(), key=lambda d: d["stage_c"]["test_accuracy"])
    lines.append(
        f"- Найвища точність на тесті — **{best['base']}** "
        f"({best['stage_c']['test_accuracy']:.4f}), найнижча — {worst_model['base']} "
        f"({worst_model['stage_c']['test_accuracy']:.4f}).")
    lines.append(
        f"- Мережа з нуля (ЛР7) дала {LAB7['test_accuracy']:.4f}; приріст від "
        f"перенесення навчання — **{best['stage_c']['test_accuracy'] - LAB7['test_accuracy']:+.4f}** "
        f"для найкращої моделі.")

    # Чи всі етапи дали приріст.
    for d in data.values():
        a, b, c = (d["stage_a"]["test_accuracy"], d["stage_b"]["test_accuracy"],
                   d["stage_c"]["test_accuracy"])
        lines.append(f"- {d['base']}: етап A {a:.4f} → B {b:.4f} → C {c:.4f} "
                     f"(донавчання дало {c - b:+.4f} до етапу B).")

    lightest = min(data.values(), key=lambda d: d["params"]["total"])
    lines.append(
        f"- Найлегша мережа — {lightest['base']} ({fmt(lightest['params']['total'])} "
        f"параметрів, {lightest['stage_c']['test_accuracy']:.4f} на тесті): "
        f"{(best['params']['total'] / lightest['params']['total']):.1f}× менша за "
        f"{best['base']} при різниці в точності "
        f"{lightest['stage_c']['test_accuracy'] - best['stage_c']['test_accuracy']:+.4f}.")

    hard_total = sum(len(d["hard_images"]) for d in data.values())
    hard_ok = sum(sum(r["correct"] for r in d["hard_images"]) for d in data.values())
    lines.append(
        f"- На складних зображеннях попередньо навчені мережі в сумі дали "
        f"{hard_ok} правильних з {hard_total}, тобто "
        f"{hard_ok / hard_total:.0%}; мережа з нуля в ЛР7 — "
        f"{LAB7['hard'][0]}/{LAB7['hard'][1]} ({LAB7['hard'][0] / LAB7['hard'][1]:.0%}).")

    return "## Фактичні спостереження\n\n" + "\n".join(lines) + "\n"


def run_conditions(data):
    d = next(iter(data.values()))
    env = d["environment"]
    rows = [
        ["Набір даних", "Kaggle Dogs vs Cats, 25 000 зображень"],
        ["Розподіл", f"train {fmt(d['samples']['train'])} / "
                     f"val {fmt(d['samples']['val'])} / test {fmt(d['samples']['test'])}"],
        ["На клас", f"{d['subset']['train_per_class']} / {d['subset']['val_per_class']}"
                    f" / {d['subset']['test_per_class']}"
                    f"{'' if d['subset']['full_dataset'] else ' (підмножина!)'}"],
        ["Класи", str(d["class_indices"])],
        ["Розмір входу", f"{d['input_size'][0]}×{d['input_size'][1]}"],
        ["Batch", d["batch_size"]],
        ["Сітка Dropout", ", ".join(f"`{p}`" for p in d["dropouts"])],
        ["TensorFlow", env["tensorflow"]],
        ["Keras", env["keras"]],
        ["Середовище", "Google Colab" if env["in_colab"] else "локально"],
        ["GPU", ", ".join(env["gpu"]) if env["gpu"] else "немає (CPU)"],
    ]
    return "## Умови прогону\n\n" + table(["Параметр", "Значення"], rows) + "\n\n" + \
        "Структура каталогів набору:\n\n```\n" + d["dir_tree"] + "\n```\n"


def files_section(data):
    lines = []
    for task in TASKS:
        if task not in data:
            continue
        for p in sorted(RESULTS.glob(f"{task}_*.png")):
            lines.append(f"- `{p.name}`")
    for p in sorted(RESULTS.glob("task5_*.png")):
        lines.append(f"- `{p.name}`")
    for p in sorted(RAW.glob("*.json")):
        lines.append(f"- `raw/{p.name}`")
    for p in sorted(RAW.glob("*.txt")):
        lines.append(f"- `raw/{p.name}`")
    return "## Файли\n\n" + "\n".join(lines) + "\n"


def main():
    data = {}
    for task in TASKS:
        d = load(f"{task}.json")
        if d:
            data[task] = d
        else:
            print(f"[ ] {task}.json ще немає — розділ пропущено")

    if not data:
        raise SystemExit("немає жодного results/raw/taskN.json — спочатку виконайте ноутбуки "
                         "в Colab і розпакуйте зіпи через scripts/unpack_results.py")

    compare = load("task5.json")

    parts = [
        "# Лабораторна 8 — результати",
        "",
        "Перенесення навчання (Transfer Learning) у Keras на наборі Kaggle Dogs vs Cats.",
        "Усі числа в цьому файлі зібрані скриптом `scripts/collect_results.py`",
        "з `results/raw/*.json`, які залишили виконані ноутбуки.",
        "",
        run_conditions(data),
        "",
    ]
    for task, d in data.items():
        parts.append(model_section(task, d))
    if len(data) > 1:
        parts.append(comparison_section(data))
    parts.append(observations(data))
    parts.append(files_section(data))

    summary = "\n".join(parts)
    (RESULTS / "summary.md").write_text(summary, encoding="utf-8")
    print(f"[+] results/summary.md — {len(summary.splitlines())} рядків")

    merged = {
        "lab7_baseline": {k: (list(v) if isinstance(v, tuple) else v)
                          for k, v in LAB7.items()},
        "models": data,
        "comparison": compare,
    }
    (RESULTS / "metrics.json").write_text(
        json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[+] results/metrics.json — {len(data)} мереж"
          f"{', + порівняння' if compare else ''}")


if __name__ == "__main__":
    main()

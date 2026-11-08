r"""Зводить results/raw/*.json у results/summary.md — таблиці для звіту.

Запускати після unpack_results.py. Пропущені завдання просто не потрапляють
у підсумок, тож скрипт можна ганяти й на половині результатів.

Запуск:  PYTHONUTF8=1 ..\..\lab7\.venv\Scripts\python.exe scripts\collect_results.py
"""
import json
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parent.parent
RAW = LAB_ROOT / "results" / "raw"
OUT = LAB_ROOT / "results" / "summary.md"

# Базові числа попередніх лабораторних — точка відліку для порівнянь.
LAB7 = {"test_accuracy": 0.8424, "params": 1_212_513,
        "own": (16, 20), "hard": (4, 10), "cropped": (2, 6)}


def load(task):
    p = RAW / f"{task}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def table(headers, rows):
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def pct(x):
    return f"{x:.4f}"


def section_task2(d, lines):
    lines += ["## Завдання 2 — коні-люди: роздільна здатність, аугментація, донавчання", ""]
    runs = d["runs"]
    rows = []
    for r in runs.values():
        if r.get("out_of_memory"):
            rows.append([r["title"], f"{r['size']}×{r['size']}",
                         f"{r['total_params']:,}", "—", "—", "—", "не влізла в пам'ять"])
            continue
        rows.append([
            r["title"], f"{r['size']}×{r['size']}", f"{r['total_params']:,}",
            r["epochs_run"], pct(r["final_val_accuracy"]), f"{r['overfit_gap']:+.3f}",
            f"{r['own_correct']}/{r['own_total']}",
        ])
    lines += [table(["Конфігурація", "Вхід", "Параметрів", "Епох",
                     "Val accuracy", "Розрив", "Власні"], rows), ""]

    def delta(a, b, label):
        ra, rb = runs.get(a), runs.get(b)
        if not ra or not rb or "final_val_accuracy" not in ra \
                or "final_val_accuracy" not in rb:
            lines.append(f"- **{label}** — порівняння неможливе, "
                         "одна з конфігурацій не завершилась.")
            return
        lines.append(
            f"- **{label}**: val {pct(ra['final_val_accuracy'])} → "
            f"{pct(rb['final_val_accuracy'])} "
            f"({rb['final_val_accuracy'] - ra['final_val_accuracy']:+.4f}), "
            f"розрив {ra['overfit_gap']:+.3f} → {rb['overfit_gap']:+.3f}, "
            f"власні зображення {ra['own_correct']} → {rb['own_correct']}")

    lines += ["### Відповіді на питання умови", ""]
    delta("base_150", "aug_150", "Пункт 3, аугментація")
    delta("base_150", "base_300", "Пункт 2, 150×150 → 300×300")
    delta("aug_150", "aug_ft_150", "Пункт 4, донавчання з mixed6")
    lines.append("")


def section_task3(d, lines):
    lines += ["## Завдання 3 — коти-собаки, скорочений набір 2000/500/500", ""]
    rows = [[r["title"], "так" if r["augment"] else "ні",
             "так" if r["fine_tuned"] else "ні",
             f"{r['params']['trainable']:,}", r["epochs_run"],
             pct(r["best_val_accuracy"]), pct(r["test_accuracy"]),
             f"{r['overfit_gap']:+.3f}", f"{r['train_time_sec'] / 60:.1f}"]
            for r in d["experiments"].values()]
    lines += [table(["Експеримент", "Аугм.", "Донавч.", "Навчаних", "Епох",
                     "Val", "Тест", "Розрив", "Хв"], rows), ""]

    best = d["experiments"][d["best"]]
    lines += [f"**Найкраща модель:** {best['title']} — тест {pct(best['test_accuracy'])}", ""]

    lines += ["### Власні зображення", ""]
    own = d["own_summary"]
    rows = [["ЛР7, своя CNN з нуля (25 000 зображень)", pct(LAB7["test_accuracy"]),
             f"{LAB7['own'][0]}/{LAB7['own'][1]}", f"{LAB7['hard'][0]}/{LAB7['hard'][1]}",
             f"{LAB7['cropped'][0]}/{LAB7['cropped'][1]}"],
            [f"ЛР10, {best['title']} (6000 зображень)", pct(best["test_accuracy"]),
             f"{own['cats_dogs'][0]}/{own['cats_dogs'][1]}",
             f"{own['cats_dogs_hard'][0]}/{own['cats_dogs_hard'][1]}",
             f"{own['cats_dogs_cropped'][0]}/{own['cats_dogs_cropped'][1]}"]]
    lines += [table(["Модель", "Тест", "Звичайні", "Складні", "Обрізані"], rows), ""]
    diff = best["test_accuracy"] - LAB7["test_accuracy"]
    lines += [f"Різниця з ЛР7: **{diff:+.4f}** на тестовому наборі — "
              f"{'вище' if diff > 0 else 'нижче'}, при навчальному наборі в 4.4 раза "
              f"меншому (4000 зображень проти 17500).", ""]
    if diff > 0:
        lines += ["Перенесення навчання з аугментацією перекриває брак даних: мережа "
                  "не вчить ознаки з нуля, а бере готові з ImageNet, тож їй вистачає "
                  "у рази меншої вибірки, щоб навчити лише класифікатор поверх них.", ""]


def section_task4(d, lines):
    lines += ["## Завдання 4 — Rock-Paper-Scissors (три класи)", ""]
    rows = [["Тестовий набір (згенерований)", pct(d["test_accuracy"]),
             f"{d['lecture_correct']}/{d['lecture_total']}"],
            ["Власні фотографії рук", "—", f"{d['own_correct']}/{d['own_total']}"]]
    lines += [table(["Набір", "Accuracy", "Вгадано"], rows), ""]
    lines += [f"- Епох: {d['epochs']}, параметрів: {d['total_params']:,}, "
              f"розрив train−val: {d['overfit_gap']:+.3f}",
              f"- Час навчання: {d['train_time_sec'] / 60:.1f} хв", ""]
    if d["own_total"]:
        drop = d["lecture_correct"] / d["lecture_total"] - d["own_correct"] / d["own_total"]
        if drop > 0.05:
            lines += [f"**Падіння якості на реальних фото: {drop:.0%}.** Набір RPS — це "
                      "згенеровані зображення рук на білому тлі, тож телефонне фото з "
                      "кімнатним тлом і тінями лежить поза розподілом, на якому мережу "
                      "вчили.", ""]
        else:
            lines += ["**Падіння якості на реальних фото немає.** Набір RPS — це "
                      "згенеровані зображення рук на рівному світлому тлі; власні знімки "
                      "зняті в тих самих умовах, тож вони лишаються в тому розподілі, на "
                      "якому мережу вчили.", ""]
        conf = [r["confidence"] for r in d.get("own_images", []) if "confidence" in r]
        if conf:
            weak = sum(1 for c in conf if c < 0.5)
            lines += [f"Упевненість на власних фото: від {min(conf):.2f} до "
                      f"{max(conf):.2f}, нижче 0.50 — {weak} з {len(conf)}. "
                      "Відповіді правильні, але у частині випадків із невеликим "
                      "відривом від решти класів.", ""]


SECTIONS = {"task2": section_task2, "task3": section_task3,
            "task4": section_task4}


def main():
    lines = ["# Лабораторна 10 — результати", "",
             "Згенеровано `scripts/collect_results.py` з `results/raw/*.json`.", "",
             "Завдання 1 і 5 здаються самими ноутбуками зі збереженими виводами "
             "(`Task1_transfer_learning.ipynb`, `Task5_sign_language.ipynb`): умова "
             "забороняє додавати клітинки, тож експортувати JSON із них нема звідки.",
             ""]

    found = []
    for task, section in SECTIONS.items():
        d = load(task)
        if d is None:
            continue
        found.append(task)
        section(d, lines)

    if not found:
        lines += ["_Результатів ще немає: виконайте ноутбуки в Colab і запустіть "
                  "`scripts/unpack_results.py`._", ""]
    else:
        lines += ["---", "", f"Зведено завдання: {', '.join(found)}.", ""]

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"{OUT} — {len(lines)} рядків, завдання: {found or 'немає'}")


if __name__ == "__main__":
    main()

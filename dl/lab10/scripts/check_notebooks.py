r"""Перевірка згенерованих ноутбуків перед заливанням у Colab.

Що перевіряється:
  * кожна кодова клітинка розбирається як Python (рядки з ! та % — магія
    IPython, їх замінюємо на pass зі збереженням відступу);
  * не лишилось незамінених токенів @@ІМ'Я@@;
  * Завдання 1 відрізняється від базового ноутбука виключно вмістом блоків
    START/END CODE HERE, а кількість клітинок не змінилась.

Запуск:  PYTHONUTF8=1 ..\..\lab7\.venv\Scripts\python.exe scripts\check_notebooks.py
"""
import ast
import re
import sys
from pathlib import Path

import nbformat

LAB_ROOT = Path(__file__).resolve().parent.parent
NB_DIR = LAB_ROOT / "notebooks"
BASE = LAB_ROOT / "base_notebooks" / "Lab_10_1_Assignment.ipynb"
START, END = "### START CODE HERE", "### END CODE HERE"


def strip_magic(src):
    """Замінює рядки магії IPython на pass, не ламаючи відступи."""
    out, in_continuation = [], False
    for line in src.splitlines():
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]
        continues = line.rstrip().endswith("\\")
        if in_continuation:
            # Продовження команди оболонки прибираємо цілком: власний відступ
            # такого рядка до Python-коду стосунку не має.
            in_continuation = continues
        elif stripped.startswith(("!", "%")):
            out.append(indent + "pass")
            in_continuation = continues
        else:
            out.append(line)
    return "\n".join(out)


def check_syntax():
    problems = []
    for path in sorted(NB_DIR.glob("*.ipynb")):
        nb = nbformat.read(path, as_version=4)
        joined = "\n".join(c.source for c in nb.cells)
        for token in sorted(set(re.findall(r"@@[A-Z_]+@@", joined))):
            problems.append(f"{path.name}: незамінений токен {token}")
        n_code = 0
        for i, cell in enumerate(nb.cells):
            if cell.cell_type != "code":
                continue
            n_code += 1
            try:
                ast.parse(strip_magic(cell.source))
            except SyntaxError as e:
                problems.append(f"{path.name} клітинка {i}: {e}")
        print(f"  {path.name:<44} {len(nb.cells):>3} клітинок, {n_code:>3} з кодом")
    return problems


def check_untouched(base_name, target_name):
    """Завдання 1 і 5 здаються з умовою «інші рядки не можна змінювати»."""
    problems = []
    target = NB_DIR / target_name
    if not target.exists():
        return [f"немає {target}"]

    base = nbformat.read(LAB_ROOT / "base_notebooks" / base_name, as_version=4)
    out = nbformat.read(target, as_version=4)

    if len(base.cells) != len(out.cells):
        return [f"кількість клітинок змінилась: {len(base.cells)} -> {len(out.cells)}"]

    changed = []
    for i, (b, o) in enumerate(zip(base.cells, out.cells)):
        if b.cell_type != o.cell_type:
            problems.append(f"клітинка {i}: змінився тип")
            continue
        if b.source == o.source:
            continue
        changed.append(i)
        if START not in b.source or END not in b.source:
            problems.append(f"клітинка {i}: змінена, хоча блоку START/END у ній немає")
            continue
        if b.source.split(START)[0] != o.source.split(START)[0]:
            problems.append(f"клітинка {i}: змінено текст ДО блоку")
        if b.source.split(END)[1] != o.source.split(END)[1]:
            problems.append(f"клітинка {i}: змінено текст ПІСЛЯ блоку")

    left = [i for i, c in enumerate(out.cells)
            if c.cell_type == "code" and re.search(r"=\s*None\s*$", c.source, re.M)]
    # `weights = None` у create_pre_trained_model — так в оригіналі, це не пропуск.
    left = [i for i in left if "weights = None" not in out.cells[i].source]
    if left:
        problems.append(f"{target_name}: незаповнені пропуски у клітинках {left}")

    print(f"  {target_name}: змінено клітинок {changed} (усі — лише між START/END)")
    return problems


def main():
    print("Синтаксис клітинок:")
    problems = check_syntax()
    print("\nЗавдання 1 і 5 проти оригіналів:")
    problems += check_untouched("Lab_10_1_Assignment.ipynb",
                                "Task1_transfer_learning.ipynb")
    problems += check_untouched("Lab_10_5_Assignment.ipynb",
                                "Task5_sign_language.ipynb")

    if problems:
        print("\nПРОБЛЕМИ:")
        for p in problems:
            print("  -", p)
        sys.exit(1)
    print("\nУсе гаразд.")


if __name__ == "__main__":
    main()

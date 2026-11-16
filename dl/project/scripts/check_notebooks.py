r"""Статична перевірка згенерованих ноутбуків.

Ловить те, що видно без запуску: зламаний JSON, синтаксичні помилки в
клітинках, чужі виводи, відсутні заголовки, використання імені раніше за його
визначення.

Запуск:  PYTHONUTF8=1 ..\..\lab7\.venv\Scripts\python.exe scripts\check_notebooks.py
"""
import ast
import builtins
import sys
from pathlib import Path

import nbformat

PROJECT_ROOT = Path(__file__).resolve().parent.parent
NB_DIR = PROJECT_ROOT / "notebooks"

# Імена, що з'являються лише під час виконання в Colab.
RUNTIME_NAMES = {"google", "files", "drive", "get_ipython"}


def defined_names(tree):
    """Імена, які клітинка вводить у простір імен."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
            target = node.target
            for sub in ast.walk(target):
                if isinstance(sub, ast.Name):
                    names.add(sub.id)
    return names


def used_names(tree):
    """Імена, які клітинка читає на верхньому рівні модуля.

    Тіла функцій пропускаються: вони виконуються пізніше, коли потрібне ім'я
    вже існує (саме так написаний `run()` і помічники в ноутбуках).
    """
    names, local = set(), set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            local.add(node.name)
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                names.add(sub.id)
            elif isinstance(sub, ast.arg):          # параметри lambda
                local.add(sub.arg)
            elif isinstance(sub, (ast.ListComp, ast.SetComp, ast.DictComp,
                                  ast.GeneratorExp)):
                for gen in sub.generators:
                    for t in ast.walk(gen.target):
                        if isinstance(t, ast.Name):
                            local.add(t.id)
    return names - local


def check(path):
    problems = []
    nb = nbformat.read(path, as_version=4)
    nbformat.validate(nb)

    if not any(c.cell_type == "markdown" and c.source.startswith("# ")
               for c in nb.cells):
        problems.append("немає заголовка першого рівня")

    known = set(dir(builtins)) | RUNTIME_NAMES
    seen_sources = {}
    for i, cell in enumerate(nb.cells):
        if cell.cell_type == "markdown":
            continue
        if cell.get("outputs"):
            problems.append(f"клітинка {i}: лишилися виводи")
        try:
            tree = ast.parse(cell.source)
        except SyntaxError as exc:
            problems.append(f"клітинка {i}: синтаксис — {exc}")
            continue
        if cell.source in seen_sources:
            problems.append(f"клітинка {i}: дублює клітинку {seen_sources[cell.source]}")
        seen_sources[cell.source] = i

        # Імена, визначені в цій же клітинці, теж доступні: Python виконує її
        # цілком, а не порядково відносно наступних клітинок.
        known |= defined_names(tree)
        for name in sorted(used_names(tree) - known):
            problems.append(f"клітинка {i}: ім'я {name!r} вживається до визначення")

    return problems


def main():
    paths = sorted(NB_DIR.glob("*.ipynb"))
    if not paths:
        print("ноутбуків немає — спершу scripts/make_notebooks.py")
        return 1
    ok = True
    for path in paths:
        problems = check(path)
        status = "ok" if not problems else f"{len(problems)} проблем"
        print(f"{path.name}: {status}")
        for p in problems:
            print(f"    {p}")
        ok &= not problems
    print("\nРЕЗУЛЬТАТ:", "усе гаразд" if ok else "є проблеми")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

"""Робить копії виконаних ноутбуків під показ із редактора.

notebooks/ лишається комплектом для здачі з оригінальними іменами (на них
спираються check_notebooks.py і verify_graded.py). notebooks/with_results/ —
ті самі файли з виводами, перейменовані за номером завдання.
"""
import shutil
from pathlib import Path

NB = Path(r"C:\uni_year_4\dl\lab10\notebooks")
OUT = NB / "with_results"

NAMES = {
    "Task1_transfer_learning.ipynb": "01_horses_humans_inception.ipynb",
    "Task2_horses_humans_experiments.ipynb": "02_resolution_augment_finetune.ipynb",
    "Task3_cats_dogs_small.ipynb": "03_cats_dogs_2000.ipynb",
    "Task4_rock_paper_scissors.ipynb": "04_rock_paper_scissors.ipynb",
    "Task5_sign_language.ipynb": "05_sign_language.ipynb",
}

OUT.mkdir(exist_ok=True)
for old in OUT.glob("*.ipynb"):
    old.unlink()

for src_name, dst_name in NAMES.items():
    src = NB / src_name
    if not src.exists():
        raise SystemExit(f"немає {src}")
    dst = OUT / dst_name
    shutil.copy2(src, dst)
    print(f"{dst_name:<38} {dst.stat().st_size / 1e6:>5.1f} МБ")

r"""Димовий прогін ноутбуків локально, щоб помилки не спливали вже в Colab.

Виконує справжні клітинки ноутбуків від першої до останньої, але підміняє
`Model.fit` і `Model.evaluate` так, щоб кожне навчання робило одну епоху на
кількох партіях. Перевіряється код — форми тензорів, препроцесія, зіставлення
імен, поділ вибірок, збирання таблиць, графіки, матриця помилок, Grad-CAM,
експорт, — а не якість навчання: її можна отримати лише повним прогоном на ГП.

Дані бере з синтетичного двійника (scripts/make_fake_dataset.py), тому
справжній набір на 2.4 ГБ для перевірки не потрібен.

Запуск:  PYTHONUTF8=1 ..\..\lab7\.venv\Scripts\python.exe scripts\smoke_notebooks.py [01 02 03 04]
"""
import os
import shutil
import sys
import warnings
from pathlib import Path

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
warnings.filterwarnings("ignore")

import matplotlib
import nbformat

matplotlib.use("Agg")              # без вікон
import tensorflow as tf           # noqa: E402

import make_fake_dataset          # noqa: E402

SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPTS_DIR.parent
NB_DIR = PROJECT_ROOT / "notebooks"

# Клітинки обчислюють корінь проєкту як Path.cwd().parent — у Colab це /content.
# Якщо запускати їх зі справжньої scripts/, вони писали б у справжню results/ і
# затирали б результати, привезені з Colab. Тому прогін іде в пісочниці:
# ставши у .smoke/scripts/, ноутбуки бачать коренем .smoke/.
SANDBOX = PROJECT_ROOT / ".smoke"
SANDBOX_SCRIPTS = SANDBOX / "scripts"

NOTEBOOKS = {
    "01": "01_dataset_eda.ipynb",
    "02": "02_baseline_cnn.ipynb",
    "03": "03_transfer_finetune.ipynb",
    "04": "04_evaluation.ipynb",
    "05": "05_long_tail.ipynb",
}

_real_fit = tf.keras.Model.fit
_real_evaluate = tf.keras.Model.evaluate
_real_predict = tf.keras.Model.predict
_real_checkpoint = tf.keras.callbacks.ModelCheckpoint


class NoCheckpoint(tf.keras.callbacks.Callback):
    """Заглушка замість ModelCheckpoint.

    У димовому прогоні двадцять з лишком моделей записуються двічі — у
    чекпоінти й у сховище прогонів, — а це понад три гігабайти на диску заради
    ваг після однієї епохи на двох партіях. Самі моделі лишаються (їх читає
    ноутбук 04), а проміжні чекпоінти не потрібні нікому.
    """

    def __init__(self, *args, **kwargs):
        super().__init__()


class EagerReduceLR(tf.keras.callbacks.ReduceLROnPlateau):
    """ReduceLROnPlateau, що пробує знизити швидкість навчання щоепохи.

    Справжній колбек чіпає оптимізатор лише після кількох епох без покращення,
    тож у димовому прогоні на одну епоху він не робить нічого — і несумісність
    із розкладом швидкості навчання спливає аж у Colab, посеред багатогодинної
    серії. Тут присвоєння робиться одразу, тому таке падіння ловиться локально.
    """

    def on_epoch_end(self, epoch, logs=None):
        self.model.optimizer.learning_rate = 1e-5


def tiny_fit(self, *args, **kwargs):
    kwargs["epochs"] = 1
    kwargs["steps_per_epoch"] = 2
    kwargs["validation_steps"] = 1
    kwargs["verbose"] = 0
    return _real_fit(self, *args, **kwargs)


def tiny_evaluate(self, *args, **kwargs):
    kwargs["steps"] = 1
    kwargs["verbose"] = 0
    return _real_evaluate(self, *args, **kwargs)


def quiet_predict(self, *args, **kwargs):
    kwargs["verbose"] = 0
    return _real_predict(self, *args, **kwargs)


def prepare_fixture(fresh):
    """Пісочниця із синтетичним архівом на місці локального Drive."""
    if fresh:
        shutil.rmtree(SANDBOX, ignore_errors=True)
    SANDBOX_SCRIPTS.mkdir(parents=True, exist_ok=True)

    # Генератор двійника рахує шляхи від свого __file__, тож переставляємо їх
    # на пісочницю, інакше архів ляже поруч зі справжніми даними.
    make_fake_dataset.DRIVE_DIR = SANDBOX / "data" / "drive"
    make_fake_dataset.BUILD_DIR = SANDBOX / "data" / "_fake_build"
    make_fake_dataset.ARCHIVE = make_fake_dataset.DRIVE_DIR / "archive (3).zip"
    if not make_fake_dataset.ARCHIVE.exists():
        make_fake_dataset.main()


def seed_my_images():
    """Кілька зображень у my_images/, щоб ноутбук 04 пройшов розділ 8.

    Беруться з тестової вибірки двійника: для перевірки коду цього досить, а
    справжні my_images/ лишаються недоторканими.
    """
    test_dir = SANDBOX / "data" / "dataset" / "test"
    target = SANDBOX / "my_images"
    if target.exists() or not test_dir.exists():
        return
    for class_dir in sorted(p for p in test_dir.iterdir() if p.is_dir())[:3]:
        files = sorted(class_dir.glob("*.jpg"))[:2]
        if not files:
            continue
        (target / class_dir.name).mkdir(parents=True, exist_ok=True)
        for src in files:
            shutil.copy(src, target / class_dir.name / src.name)


def run_notebook(key):
    path = NB_DIR / NOTEBOOKS[key]
    print(f"\n{'=' * 72}\n{path.name}\n{'=' * 72}")
    nb = nbformat.read(path, as_version=4)

    os.chdir(SANDBOX_SCRIPTS)

    ns = {"__name__": "__main__"}
    for i, cell in enumerate(nb.cells):
        if cell.cell_type != "code":
            continue
        # Магія IPython локально не потрібна: такі гілки в ноутбуках під IN_COLAB.
        source = "\n".join(line for line in cell.source.splitlines()
                           if not line.lstrip().startswith(("!", "%")))
        try:
            exec(compile(source, f"{path.name}:{i}", "exec"), ns)
            print(f"  [{i:>2}] ok")
        except Exception as exc:
            print(f"  [{i:>2}] ПОМИЛКА: {type(exc).__name__}: {exc}")
            import traceback

            traceback.print_exc(limit=6)
            return False
    return True


def main():
    args = [a for a in sys.argv[1:] if a != "--keep"]
    keys = args or list(NOTEBOOKS)
    prepare_fixture(fresh="--keep" not in sys.argv)

    tf.keras.Model.fit = tiny_fit
    tf.keras.Model.evaluate = tiny_evaluate
    tf.keras.Model.predict = quiet_predict
    tf.keras.callbacks.ModelCheckpoint = NoCheckpoint
    tf.keras.callbacks.ReduceLROnPlateau = EagerReduceLR

    ok = True
    for key in keys:
        ok &= run_notebook(key)
        shutil.rmtree(SANDBOX / "ckpt", ignore_errors=True)
        seed_my_images()
        if not ok:
            break
    print("\nРЕЗУЛЬТАТ:", "усе пройшло" if ok else "є помилки")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

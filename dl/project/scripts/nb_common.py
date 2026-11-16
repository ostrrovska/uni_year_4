r"""Клітинки, спільні для ноутбуків проєкту.

Кожен ноутбук має бути самодостатнім у Colab, тому код не імпортується, а
вставляється в клітинки. Щоб версії не розходилися, спільні клітинки лежать тут,
а `make_notebooks.py` підставляє в них значення через `@@ІМ'Я@@`.
"""

# --------------------------------------------------------------- середовище
BOOTSTRAP = r'''# Environment, paths, seed. Same prelude in every notebook of the project.
import json
import os
import shutil
import time
import zipfile
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import tensorflow as tf
from tensorflow import keras

try:
    import google.colab  # noqa: F401

    IN_COLAB = True
except ImportError:
    IN_COLAB = False

print('TensorFlow', tf.__version__, '| Keras', keras.__version__)
print('GPU:', tf.config.list_physical_devices('GPU'))
if IN_COLAB and not tf.config.list_physical_devices('GPU'):
    print('\n!! ГП НЕ УВІМКНЕНО. Середовище виконання -> Змінити тип -> ГП L4.')

PROJECT_ROOT = Path('/content') if IN_COLAB else Path.cwd().parent
RESULTS = PROJECT_ROOT / 'results'
(RESULTS / 'raw').mkdir(parents=True, exist_ok=True)

# Everything that must survive a Colab disconnect lives on Drive.
DRIVE_DIR = (Path('/content/drive/MyDrive/dl_final_project') if IN_COLAB
             else PROJECT_ROOT / 'data' / 'drive')


def mount_drive():
    """Mount Drive once; locally just ensure the stand-in folder exists."""
    if IN_COLAB and not Path('/content/drive/MyDrive').exists():
        from google.colab import drive

        drive.mount('/content/drive')
    DRIVE_DIR.mkdir(parents=True, exist_ok=True)
    return DRIVE_DIR


SEED = 42
keras.utils.set_random_seed(SEED)
plt.rcParams['figure.dpi'] = 110
print('Проєкт:', PROJECT_ROOT)
print('Drive :', DRIVE_DIR)'''


# ------------------------------------------------------- підготовлений набір
GET_DATA = r'''# The prepared dataset comes from notebook 01: one tree with all 50 classes,
# already cleaned, split and resized to 320 px. Both tracks (top-15 and all-50)
# read from the same tree, so their splits are identical and comparable.
mount_drive()
PREPARED = DRIVE_DIR / 'prepared'
DATA_DIR = Path('/content/dataset') if IN_COLAB else PROJECT_ROOT / 'data' / 'dataset'

if not (DATA_DIR / 'train').exists():
    src = PREPARED / 'dataset.zip'
    if not src.exists():
        raise FileNotFoundError(
            f'немає {src} — спочатку виконайте ноутбук 01_dataset_eda.ipynb')
    t0 = time.time()
    with zipfile.ZipFile(src) as z:
        z.extractall(DATA_DIR)
    print(f'набір розпаковано за {time.time() - t0:.0f} с')

with open(PREPARED / 'class_names.json', encoding='utf-8') as f:
    CLASSES = json.load(f)
ALL50 = CLASSES['all50']
TOP15 = CLASSES['top15']

for _split in ('train', 'val', 'test'):
    _n = sum(1 for _ in (DATA_DIR / _split).rglob('*.jpg'))
    print(f'{_split:<6} {_n:>6} зображень')
print(f'\nкласів у наборі: {len(ALL50)}; основний трек: {len(TOP15)}')
print(', '.join(TOP15))'''


# ------------------------------------------------------------ конвеєр даних
DATASETS = r'''# tf.data pipeline (Keras 3 way; the labs used the legacy ImageDataGenerator).
# `class_names` restricts the reader to the chosen track without copying files.
#
# Only val/test are cached in memory: the training set at 224x224 float32 would
# take several GB, and decoding 320 px JPEGs with AUTOTUNE is cheap enough.
AUTOTUNE = tf.data.AUTOTUNE

AUG_PRESETS = {
    'light': [
        keras.layers.RandomFlip('horizontal'),
        keras.layers.RandomRotation(0.05),
        keras.layers.RandomZoom(0.1),
    ],
    'strong': [
        keras.layers.RandomFlip('horizontal'),
        keras.layers.RandomRotation(0.15),
        keras.layers.RandomZoom(0.2),
        keras.layers.RandomTranslation(0.1, 0.1),
        keras.layers.RandomContrast(0.2),
    ],
}


def make_augment(kind):
    """Augmentation as model layers: runs on GPU and is inactive at inference.

    No vertical flip: a painting is never upside down, and mirroring already
    stretches what a brushstroke may look like.
    """
    if not kind:
        return None
    return keras.Sequential(AUG_PRESETS[kind], name=f'augment_{kind}')


def make_datasets(class_names, img_size=224, batch=32):
    def load(split, shuffle):
        return keras.utils.image_dataset_from_directory(
            DATA_DIR / split, labels='inferred', label_mode='int',
            class_names=class_names, image_size=(img_size, img_size),
            batch_size=batch, shuffle=shuffle, seed=SEED,
            interpolation='bilinear', verbose=False)

    train = load('train', True).prefetch(AUTOTUNE)
    val = load('val', False).cache().prefetch(AUTOTUNE)
    test = load('test', False).cache().prefetch(AUTOTUNE)
    return train, val, test


def class_weights_for(class_names):
    """Balanced weights: rare artists get a proportionally larger penalty."""
    counts = np.array([len(list((DATA_DIR / 'train' / c).glob('*.jpg')))
                       for c in class_names], dtype=float)
    weights = counts.sum() / (len(counts) * counts)
    return {i: float(w) for i, w in enumerate(weights)}


def count_steps(class_names, split='train'):
    return sum(len(list((DATA_DIR / split / c).glob('*.jpg'))) for c in class_names)


print('зображень у навчальній вибірці трека top-15:', count_steps(TOP15))'''


# ------------------------------------------------------------ стенд прогонів
HARNESS = r'''# One function for every experiment, so that between any two runs exactly one
# factor differs. Each finished run is written to Drive and skipped on re-run,
# so a Colab disconnect costs one experiment instead of the whole series.
RUNS_DIR = DRIVE_DIR / 'runs'
MODELS_DIR = DRIVE_DIR / 'models'
CKPT_DIR = PROJECT_ROOT / 'ckpt'
for _d in (RUNS_DIR, MODELS_DIR, CKPT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

FORCE_RERUN = False          # True -> ignore saved runs and train everything again
results = {}


class TimeHistory(keras.callbacks.Callback):
    """Wall-clock time of training; reported in the summary table."""

    def on_train_begin(self, logs=None):
        self._t0 = time.time()
        self.seconds = 0.0

    def on_train_end(self, logs=None):
        self.seconds = time.time() - self._t0


def make_callbacks(name, timer, patience=5, reduce_lr=True):
    # Checkpoints go to local disk: writing every improvement straight to Drive
    # is slow. The best model is copied to Drive once, after training.
    callbacks = [
        keras.callbacks.EarlyStopping(monitor='val_accuracy', mode='max',
                                      patience=patience, restore_best_weights=True,
                                      verbose=1),
        keras.callbacks.ModelCheckpoint(str(CKPT_DIR / f'{name}.keras'),
                                        monitor='val_accuracy', mode='max',
                                        save_best_only=True),
        keras.callbacks.CSVLogger(str(RESULTS / 'raw' / f'{name}_log.csv')),
        timer,
    ]
    # ReduceLROnPlateau and a LearningRateSchedule are mutually exclusive: the
    # callback assigns a new value to optimizer.learning_rate, and an optimizer
    # built with a schedule refuses that (TypeError, mid-training). A schedule
    # already governs the learning rate, so the callback is simply dropped.
    if reduce_lr:
        callbacks.insert(1, keras.callbacks.ReduceLROnPlateau(
            monitor='val_loss', factor=0.5, patience=2, min_lr=1e-6, verbose=1))
    return callbacks


def top_k_accuracy(model, ds, k=3):
    hits = total = 0
    for xb, yb in ds:
        probs = model.predict(xb, verbose=0)
        topk = np.argsort(probs, axis=1)[:, -k:]
        hits += int(np.sum(topk == np.asarray(yb)[:, None]))
        total += len(yb)
    return hits / max(total, 1)


def run(cfg, build_fn):
    """Train one configuration and record everything the report needs."""
    name = cfg['name']
    path = RUNS_DIR / f'{name}.json'
    if path.exists() and not FORCE_RERUN:
        results[name] = json.loads(path.read_text(encoding='utf-8'))
        print(f"[{name}] уже виконано ранiше (val {results[name]['best_val_accuracy']:.4f})"
              ' — пропускаю')
        return results[name]

    keras.backend.clear_session()
    keras.utils.set_random_seed(SEED)

    classes = cfg.get('classes', TOP15)
    train, val, test = make_datasets(classes, cfg.get('img_size', 224),
                                     cfg.get('batch', 32))
    model = build_fn(cfg, classes)
    weights = class_weights_for(classes) if cfg.get('class_weight') else None

    timer = TimeHistory()
    print(f"\n{'=' * 70}\n{name}: {cfg['title']}\n{'=' * 70}")
    history = model.fit(train, validation_data=val, epochs=cfg.get('epochs', 25),
                        class_weight=weights, verbose=2,
                        callbacks=make_callbacks(name, timer,
                                                 cfg.get('patience', 5),
                                                 reduce_lr=not cfg.get('schedule')))

    test_loss, test_acc = model.evaluate(test, verbose=0)
    record = {
        'name': name,
        'title': cfg['title'],
        'config': {k: v for k, v in cfg.items() if k != 'classes'},
        'n_classes': len(classes),
        'params': int(model.count_params()),
        'trainable_params': int(sum(np.prod(w.shape) for w in model.trainable_weights)),
        'epochs_run': len(history.history['loss']),
        'best_val_accuracy': float(max(history.history['val_accuracy'])),
        'final_train_accuracy': float(history.history['accuracy'][-1]),
        'test_accuracy': float(test_acc),
        'test_loss': float(test_loss),
        'test_top3_accuracy': float(top_k_accuracy(model, test, 3)),
        'seconds': float(timer.seconds),
        'history': {k: [float(x) for x in v] for k, v in history.history.items()},
    }
    record['overfit_gap'] = record['final_train_accuracy'] - record['best_val_accuracy']

    model.save(MODELS_DIR / f'{name}.keras')
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    results[name] = record
    print(f"\n[{name}] val {record['best_val_accuracy']:.4f} | "
          f"test {record['test_accuracy']:.4f} | top-3 {record['test_top3_accuracy']:.4f} | "
          f"{record['seconds'] / 60:.1f} хв")

    del model
    keras.backend.clear_session()
    return record


def load_previous_runs():
    """Pick up runs made in an earlier session (or in an earlier notebook)."""
    for f in sorted(RUNS_DIR.glob('*.json')):
        results.setdefault(f.stem, json.loads(f.read_text(encoding='utf-8')))
    print(f'відомо прогонів: {len(results)}')


load_previous_runs()'''


# ------------------------------------------------------------------ графіки
PLOTS = r'''# Learning curves. Solid red = training, dashed blue = validation;
# the distance between them is overfitting.
def plot_histories(names, fname, suptitle):
    names = [n for n in names if results.get(n, {}).get('history')]
    if not names:
        print('немає історій для графіків')
        return
    cols = min(3, len(names))
    rows = -(-len(names) // cols)
    fig, axes = plt.subplots(rows, cols, figsize=(5.2 * cols, 3.9 * rows),
                             squeeze=False)
    for ax, name in zip(axes.ravel(), names):
        rec = results[name]
        h = rec['history']
        epochs = range(1, len(h['accuracy']) + 1)
        # Маркери, а не самі лінії: прогін, зупинений після однієї епохи, інакше
        # не було б видно взагалі.
        ax.plot(epochs, h['accuracy'], color='crimson', marker='o', ms=3,
                label='навчальна')
        ax.plot(epochs, h['val_accuracy'], color='royalblue', ls='--',
                marker='s', ms=3, label='перевірочна')
        ax.axhline(rec['test_accuracy'], color='seagreen', ls=':', lw=1.2,
                   label='тестова')
        ax.set_title(f"{name}\n{rec['title']}", fontsize=9)
        ax.set_xlabel('епоха')
        ax.xaxis.set_major_locator(plt.MaxNLocator(integer=True))
        ax.set_ylabel('точність')
        ax.set_ylim(0, 1)
        ax.grid(alpha=0.3)
        ax.legend(fontsize=7)
    for ax in axes.ravel()[len(names):]:
        ax.axis('off')
    fig.suptitle(suptitle, fontsize=13)
    plt.tight_layout()
    plt.savefig(RESULTS / fname, dpi=110, bbox_inches='tight')
    plt.show()'''


# ------------------------------------------------------------------ таблиця
TABLE = r'''# Summary table of every run known so far. pandas is a deliberate departure
# from the labs' hand-built ASCII tables: these numbers go straight into the report.
def summary_frame(names=None):
    names = names or list(results)
    rows = []
    for name in names:
        r = results[name]
        rows.append({
            'експеримент': name,
            'опис': r['title'],
            'класів': r['n_classes'],
            'параметрів': r['params'],
            'навчаних': r['trainable_params'],
            'епох': r['epochs_run'],
            'val acc': round(r['best_val_accuracy'], 4),
            'test acc': round(r['test_accuracy'], 4),
            'test top-3': round(r['test_top3_accuracy'], 4),
            'розрив': round(r['overfit_gap'], 4),
            'хв': round(r['seconds'] / 60, 1),
        })
    df = pd.DataFrame(rows).sort_values('test acc', ascending=False)
    return df.reset_index(drop=True)'''


# ------------------------------------------------------------------- експорт
EXPORT = r'''# Export: numbers for the report plus a zip to drop into results/incoming/.
NB = '@@NB@@'
payload = {
    'notebook': NB,
    'tensorflow': tf.__version__,
    'gpu': [d.name for d in tf.config.list_physical_devices('GPU')],
    'runs': results,
}
out = RESULTS / 'raw' / f'{NB}.json'
out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
print('записано', out)

zip_path = PROJECT_ROOT / f'project_{NB}_results.zip'
with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
    for f in sorted(RESULTS.rglob('*')):
        if f.is_file() and f.suffix in ('.json', '.png', '.csv', '.md'):
            z.write(f, f.relative_to(RESULTS))
print('зіп:', zip_path, f'({zip_path.stat().st_size / 1e6:.1f} МБ)')

if IN_COLAB:
    from google.colab import files

    files.download(str(zip_path))'''

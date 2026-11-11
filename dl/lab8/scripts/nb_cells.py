"""Шаблони клітинок для ноутбуків лабораторної 8.

Усі шаблони — «сирі» рядки з токенами @@НАЗВА@@, які підставляє
make_notebooks.fill() з конфігурації конкретної мережі. Саме заміна токенів, а
не format()/f-рядки: у коді ноутбуків багато фігурних дужок.
"""

BOOTSTRAP = r'''# Середовище, шляхи, перевірка GPU (працює і локально, і в Colab)
import json
import math
import os
import time
import zipfile
from pathlib import Path

try:
    import google.colab  # noqa: F401
    IN_COLAB = True
except ImportError:
    IN_COLAB = False

LAB_ROOT = Path("/content") if IN_COLAB else Path.cwd().parent   # notebooks/ -> dl/lab8
DATA = LAB_ROOT / "data"
RESULTS = LAB_ROOT / "results"
MODELS = LAB_ROOT / "models"
for d in (DATA, RESULTS / "raw", MODELS):
    d.mkdir(parents=True, exist_ok=True)

# Власні тестові зображення взяті з лабораторної 7 (пункт 5 не вимагає нових).
MY_IMAGES = LAB_ROOT / "my_images"
if not IN_COLAB and not MY_IMAGES.is_dir():
    MY_IMAGES = LAB_ROOT.parent / "lab7" / "my_images"

import tensorflow as tf

gpus = tf.config.list_physical_devices("GPU")
print("IN_COLAB =", IN_COLAB)
print("LAB_ROOT =", LAB_ROOT)
print("TensorFlow", tf.__version__, "| Keras", tf.keras.__version__)
print("GPU:", gpus if gpus else "НЕМАЄ — у Colab увімкніть Runtime > Change runtime type > T4 GPU")'''


CONFIG = r'''# ---- Налаштування прогону ------------------------------------------------
# Єдиний розмір входу для всіх чотирьох мереж, щоб порівняння в пункті 5 було
# чесним: різний розмір входу інакше сплутує архітектуру з роздільністю.
INPUT_SIZE = 224
BATCH = 32

# Розмір набору на клас: None -> повний набір 8750/1875/1875 (70/15/15 від 12500).
# Якщо скінчилась квота GPU в Colab, поставте SUBSET = (2000, 500, 500).
SUBSET = None

# Пункт 4: сітка Dropout для дослідження перенавчання.
DROPOUTS = [0.0, 0.2, 0.3, 0.5, 0.7]
HEAD_EPOCHS = 30        # етап A — на кешованих ознаках, тому дешево
# Етапи B і C — найдорожчі: кожна епоха жене всі 17 500 зображень через базу.
# Перенесення навчання сходиться за кілька епох, тому їх небагато; EarlyStopping
# зазвичай зупиняє ще раніше.
EPOCHS_FROZEN = 8       # етап B — заморожена база + аугментація
EPOCHS_FINETUNE = 6     # етап C — донавчання верхніх шарів

# Звідки брати 25 000 зображень у Colab: "drive" — з MyDrive/dogs-vs-cats.zip
# (перевірений шлях з лабораторної 7), "kagglehub" — завантажити із Kaggle
# (потрібні API-токен і прийняті правила змагання).
DATA_SOURCE = "drive"

BASE_NAME = "@@TITLE@@"
SLUG = "@@SLUG@@"
TASK = "task@@TASK@@"
UNFREEZE_FROM = "@@UNFREEZE_FROM@@"
FEATURE_DIM = @@FEAT_DIM@@
ALT_SIZE = @@ALT_SIZE@@   # додатковий розмір входу лише для етапу A (None — немає)

print(f"{BASE_NAME}: вхід {INPUT_SIZE}x{INPUT_SIZE}, batch {BATCH}, "
      f"набір {'повний' if SUBSET is None else SUBSET}")'''


DRIVE_MOUNT = r'''# Google Drive: звідти беруться архіви, туди зберігаються навчені моделі.
if IN_COLAB:
    from google.colab import drive

    drive.mount("/content/drive")
    DRIVE_OUT = Path("/content/drive/MyDrive/dl_lab8")
    (DRIVE_OUT / "models").mkdir(parents=True, exist_ok=True)
    (DRIVE_OUT / "results").mkdir(parents=True, exist_ok=True)
    print("Результати й моделі дублюються у", DRIVE_OUT)
else:
    DRIVE_OUT = None'''


DATA_SOURCE_CELL = r'''# Пункт 1, крок 1: отримати 25 000 вихідних зображень (cat.N.jpg / dog.N.jpg).
RAW_TRAIN = Path("/content/train") if IN_COLAB else \
    LAB_ROOT.parent / "lab7" / "data" / "dogs_vs_cats_raw" / "train"


def have_raw(path):
    """Чи вже розпаковані всі 25 000 файлів (клітинку можна перезапускати)."""
    return path.is_dir() and len(list(path.glob("*.jpg"))) == 25000


MYDRIVE = Path("/content/drive/MyDrive")


def find_dataset_zip():
    """Шукає на Drive архів із набором.

    Підходить будь-який: і сам dogs-vs-cats.zip, і архів drive-download-*.zip,
    усередині якого він лежить. На Drive нічого розпаковувати не треба.
    """
    for pattern in ("dogs-vs-cats.zip", "drive-download-*.zip", "*dogs*cats*.zip"):
        hits = sorted(MYDRIVE.glob(pattern))
        if hits:
            print("Архів із набором:", hits[0])
            return hits[0]
    raise FileNotFoundError(
        f"у {MYDRIVE} немає ні dogs-vs-cats.zip, ні drive-download-*.zip")


def unpack_to_train(zip_path, workdir=Path("/content")):
    """Дістає 25 000 jpg з архіву будь-якої вкладеності.

    Kaggle пакує набір як train.zip -> train/cat.N.jpg, а Google Drive при
    завантаженні кількох файлів загортає це ще в один архів. Тому просто
    обходимо вкладені zip у ширину, доки не знайдемо той, що містить train/*.jpg.
    """
    queue, seen = [Path(zip_path)], set()
    while queue:
        current = queue.pop(0)
        with zipfile.ZipFile(current) as z:
            names = z.namelist()
            jpgs = [n for n in names if n.startswith("train/") and n.endswith(".jpg")]
            if jpgs:
                print(f"{current.name}: {len(jpgs)} jpg — розпаковую")
                z.extractall(workdir)
                return
            # test1.zip пропускаємо: у ньому зображення без міток.
            for n in names:
                if n.endswith(".zip") and "test" not in n.lower() and n not in seen:
                    seen.add(n)
                    print(f"{current.name} -> вкладений {n}")
                    z.extract(n, workdir)
                    queue.append(workdir / n)
    raise FileNotFoundError("в архіві не знайдено train/*.jpg")


if IN_COLAB and not have_raw(RAW_TRAIN):
    if DATA_SOURCE == "drive":
        source_zip = find_dataset_zip()
    elif DATA_SOURCE == "kagglehub":
        import kagglehub

        path = kagglehub.competition_download("dogs-vs-cats")
        print("Kaggle завантажив у", path)
        source_zip = next(Path(path).rglob("*.zip"))
    else:
        raise ValueError(f"невідоме DATA_SOURCE: {DATA_SOURCE}")
    unpack_to_train(source_zip)

print(RAW_TRAIN, "->", len(list(RAW_TRAIN.glob("*.jpg"))), "файлів")
assert have_raw(RAW_TRAIN), "очікувалось 25000 jpg — перевірте джерело даних"'''


SPLIT_CELL = r'''# Пункт 1, крок 2: той самий скрипт розділення, що в лабораторній 7
# (dl/lab7/scripts/prepare_dataset.py) — функції create_directory і copy_images
# відтворені тут дослівно, щоб ноутбук був самодостатнім у Colab.
import shutil

BASE_DIR = DATA / "cats_dogs"
train_dir, val_dir, test_dir = BASE_DIR / "train", BASE_DIR / "val", BASE_DIR / "test"


def create_directory(dir_name):
    """Чистий каталог split з підкаталогами класів (як у лекції)."""
    if os.path.exists(dir_name):
        shutil.rmtree(dir_name)
    os.makedirs(dir_name)
    os.makedirs(os.path.join(dir_name, "cats"))
    os.makedirs(os.path.join(dir_name, "dogs"))


def copy_images(start_index, end_index, source_dir, dest_dir):
    """Копіює cat.i.jpg / dog.i.jpg з діапазону індексів у відповідні підкаталоги."""
    for i in range(start_index, end_index):
        shutil.copy2(os.path.join(source_dir, f"cat.{i}.jpg"), os.path.join(dest_dir, "cats"))
        shutil.copy2(os.path.join(source_dir, f"dog.{i}.jpg"), os.path.join(dest_dir, "dogs"))


if SUBSET is None:
    nb_images, val_portion, test_portion = 12500, 0.15, 0.15
    n_train = int(nb_images * (1 - val_portion - test_portion))
    n_val = int(nb_images * (1 - test_portion)) - n_train
    n_test = nb_images - n_train - n_val
else:
    n_train, n_val, n_test = SUBSET

# Ідемпотентність: повторний запуск не перекопіює 25 000 файлів.
need_split = not all((train_dir / c).is_dir() for c in ("cats", "dogs")) or \
    len(list((train_dir / "cats").glob("*.jpg"))) != n_train

if need_split:
    t0 = time.time()
    for d in (train_dir, val_dir, test_dir):
        create_directory(d)
    copy_images(0, n_train, RAW_TRAIN, train_dir)
    copy_images(n_train, n_train + n_val, RAW_TRAIN, val_dir)
    copy_images(n_train + n_val, n_train + n_val + n_test, RAW_TRAIN, test_dir)
    print(f"Розподіл зроблено за {time.time() - t0:.0f} с")
else:
    print("Розподіл уже існує — копіювання пропущено")
print(f"На клас: train={n_train}, val={n_val}, test={n_test}")'''


TREE_CELL = r'''# Структура каталогів із кількістю файлів (як у лабораторній 7).
tree_lines = [str(BASE_DIR)]
for si, split in enumerate(("train", "val", "test")):
    s_last = si == 2
    tree_lines.append(f"{'└──' if s_last else '├──'} {split}/")
    for ci, cls in enumerate(("cats", "dogs")):
        c_last = ci == 1
        n = len(list((BASE_DIR / split / cls).glob("*.jpg")))
        tree_lines.append(f"{'    ' if s_last else '│   '}{'└──' if c_last else '├──'} {cls}/  {n} файлів")
dir_tree = "\n".join(tree_lines)
print(dir_tree)'''


GENERATORS = r'''# Пункт 2: у кожної попередньо навченої мережі своя препроцесія входу.
# rescale=1./255 з лабораторної 7 тут НЕ підходить і тихо псує точність.
from tensorflow.keras.applications.@@MODULE@@ import @@CTOR@@, preprocess_input
from tensorflow.keras.preprocessing.image import ImageDataGenerator

TARGET = (INPUT_SIZE, INPUT_SIZE)

# Аугментація — лише для етапів B і C (ще один засіб проти перенавчання).
aug_datagen = ImageDataGenerator(
    preprocessing_function=preprocess_input,
    rotation_range=40,
    width_shift_range=0.2,
    height_shift_range=0.2,
    shear_range=0.2,
    zoom_range=0.2,
    horizontal_flip=True,
    fill_mode="nearest",
)
plain_datagen = ImageDataGenerator(preprocessing_function=preprocess_input)


def flow(directory, datagen, shuffle, target=None):
    return datagen.flow_from_directory(
        str(directory), target_size=target or TARGET, batch_size=BATCH,
        class_mode="binary", shuffle=shuffle)


# shuffle=False там, де ознаки й мітки мусять збігатися порядком (етап A і тест).
train_static = flow(train_dir, plain_datagen, False)
val_static = flow(val_dir, plain_datagen, False)
test_static = flow(test_dir, plain_datagen, False)
train_aug = flow(train_dir, aug_datagen, True)
val_plain = flow(val_dir, plain_datagen, True)

nb_train, nb_val, nb_test = train_static.samples, val_static.samples, test_static.samples
print("Класи:", train_static.class_indices)
assert train_static.class_indices == {"cats": 0, "dogs": 1}, "порядок класів змінився"'''


SAMPLE_GRID = r'''# Приклади з набору після препроцесії. Значення вже не в [0, 1], тому для
# показу повертаємо їх у видимий діапазон.
import matplotlib.pyplot as plt
import numpy as np

batch_x, batch_y = next(train_static)
plt.figure(figsize=(12, 6))
for i in range(min(8, len(batch_x))):
    ax = plt.subplot(2, 4, i + 1)
    img = batch_x[i]
    img = (img - img.min()) / (img.max() - img.min() + 1e-9)
    ax.imshow(img)
    ax.set_title("dog" if batch_y[i] > 0.5 else "cat", fontsize=9)
    ax.axis("off")
plt.suptitle(f"{BASE_NAME}: приклади навчального набору після preprocess_input")
plt.tight_layout()
plt.savefig(RESULTS / f"{TASK}_dataset_sample.png", dpi=90, bbox_inches="tight")
plt.show()
train_static.reset()'''


FEATURES = r'''# ЕТАП A — перенесення навчання як екстракція ознак.
# Заморожена база з pooling="avg" один раз проганяє весь набір і віддає вектор
# ознак на зображення. Далі голову можна вчити скільки завгодно разів за секунди,
# що й дозволяє дослідити Dropout на сітці значень (пункт 4).
from tensorflow.keras import layers, models, optimizers


def build_base(size, pooling=None):
    """Згорткова частина без класифікатора ImageNet, усі шари заморожені."""
    base = @@CTOR@@(weights="imagenet", include_top=False, pooling=pooling,
                    input_shape=(size, size, 3))
    base.trainable = False
    return base


def extract_features(base, gen):
    """Ознаки й мітки в тому самому порядку (gen створений з shuffle=False)."""
    n = gen.samples
    gen.reset()
    feats = base.predict(gen, steps=math.ceil(n / BATCH), verbose=1)
    return feats[:n], gen.classes[:n].astype("float32")


base_feat = build_base(INPUT_SIZE, pooling="avg")
base_params = int(base_feat.count_params())
print(f"Згорткова частина {BASE_NAME}: {base_params:,} параметрів, усі заморожені")

t0 = time.time()
Xtr, ytr = extract_features(base_feat, train_static)
Xva, yva = extract_features(base_feat, val_static)
Xte, yte = extract_features(base_feat, test_static)
feature_sec = time.time() - t0
print(f"Ознаки: train {Xtr.shape}, val {Xva.shape}, test {Xte.shape} за {feature_sec:.0f} с")
assert Xtr.shape[1] == FEATURE_DIM, f"очікувалась розмірність {FEATURE_DIM}"'''


DROPOUT_GRID = r'''# Пункт 4: вплив Dropout на перенавчання.
# Голова однакова для всіх p, різниця лише в Dropout. Навчання без аугментації
# і на фіксованих ознаках — саме тут перенавчання видно найчистіше.
def build_head(p, dim):
    head = models.Sequential([
        layers.Input(shape=(dim,)),
        layers.Dense(256, activation="relu"),
        layers.Dropout(p),
        layers.Dense(1, activation="sigmoid"),
    ])
    head.compile(optimizer=optimizers.Adam(1e-4), loss="binary_crossentropy",
                 metrics=["accuracy"])
    return head


dropout_runs = []
for p in DROPOUTS:
    tf.keras.utils.set_random_seed(42)      # щоб різниця була саме від Dropout
    head = build_head(p, Xtr.shape[1])
    t0 = time.time()
    h = head.fit(Xtr, ytr, validation_data=(Xva, yva), epochs=HEAD_EPOCHS,
                 batch_size=64, verbose=0)
    sec = time.time() - t0
    best_epoch = int(np.argmax(h.history["val_accuracy"])) + 1
    best_val = float(max(h.history["val_accuracy"]))
    gap = float(h.history["accuracy"][-1] - h.history["val_accuracy"][-1])
    dropout_runs.append({
        "p": p,
        "best_val_accuracy": round(best_val, 4),
        "best_epoch": best_epoch,
        "final_train_accuracy": round(float(h.history["accuracy"][-1]), 4),
        "final_val_accuracy": round(float(h.history["val_accuracy"][-1]), 4),
        "final_val_loss": round(float(h.history["val_loss"][-1]), 4),
        "min_val_loss": round(float(min(h.history["val_loss"])), 4),
        "overfit_gap": round(gap, 4),
        "train_time_sec": round(sec, 1),
        "history": {k: [round(float(v), 4) for v in vals] for k, vals in h.history.items()},
    })
    print(f"p={p}: best val acc {best_val:.4f} (епоха {best_epoch}), "
          f"розрив train-val {gap:+.4f}, {sec:.0f} с")

BEST_DROPOUT = max(dropout_runs, key=lambda r: r["best_val_accuracy"])["p"]
print("\nНайкраще значення Dropout:", BEST_DROPOUT)'''


DROPOUT_PLOT = r'''# Чотири панелі: точність і втрати, окремо навчання й валідація.
# Чим більший просвіт між лівою і правою панеллю, тим сильніше перенавчання.
# sharey="row": у рядку спільна вісь, тому просвіт між навчанням і валідацією
# видно на око, а не лише в числах.
fig, axes = plt.subplots(2, 2, figsize=(14, 9), sharey="row")
colors = plt.cm.viridis(np.linspace(0, 0.9, len(dropout_runs)))

for run, color in zip(dropout_runs, colors):
    ep = range(1, len(run["history"]["accuracy"]) + 1)
    axes[0][0].plot(ep, run["history"]["accuracy"], color=color, label=f"p={run['p']}")
    axes[0][1].plot(ep, run["history"]["val_accuracy"], color=color, label=f"p={run['p']}")
    axes[1][0].plot(ep, run["history"]["loss"], color=color, label=f"p={run['p']}")
    axes[1][1].plot(ep, run["history"]["val_loss"], color=color, label=f"p={run['p']}")

titles = ["Точність на навчанні", "Точність на валідації",
          "Втрати на навчанні", "Втрати на валідації"]
for ax, title in zip(axes.ravel(), titles):
    ax.set_title(title)
    ax.set_xlabel("Епоха")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
plt.suptitle(f"{BASE_NAME}, етап A: вплив Dropout на перенавчання (пункт 4)")
plt.tight_layout()
plt.savefig(RESULTS / f"{TASK}_dropout_grid.png", dpi=110, bbox_inches="tight")
plt.show()'''


DROPOUT_TABLE = r'''# Та сама інформація таблицею — піде у звіт.
header = (f"{'p':>5} | {'best val acc':>12} | {'епоха':>6} | {'train acc':>9} | "
          f"{'val acc':>8} | {'розрив':>7} | {'min val loss':>12}")
print(header)
print("-" * len(header))
for r in dropout_runs:
    print(f"{r['p']:>5} | {r['best_val_accuracy']:>12.4f} | {r['best_epoch']:>6} | "
          f"{r['final_train_accuracy']:>9.4f} | {r['final_val_accuracy']:>8.4f} | "
          f"{r['overfit_gap']:>+7.4f} | {r['min_val_loss']:>12.4f}")'''


ALT_SIZE_CELL = r'''# Додатковий замір: той самий етап A, але на «рідному» для цієї мережі розмірі
# входу. Потрібен, щоб у звіті було видно, скільки дає саме розмір входу.
stage_a_alt = None
if ALT_SIZE:
    alt_gens = [flow(d, plain_datagen, False, target=(ALT_SIZE, ALT_SIZE))
                for d in (train_dir, val_dir, test_dir)]
    base_alt = build_base(ALT_SIZE, pooling="avg")
    Xtr_a, ytr_a = extract_features(base_alt, alt_gens[0])
    Xva_a, yva_a = extract_features(base_alt, alt_gens[1])
    Xte_a, yte_a = extract_features(base_alt, alt_gens[2])

    tf.keras.utils.set_random_seed(42)
    head_alt = build_head(BEST_DROPOUT, Xtr_a.shape[1])
    h_alt = head_alt.fit(Xtr_a, ytr_a, validation_data=(Xva_a, yva_a),
                         epochs=HEAD_EPOCHS, batch_size=64, verbose=0)
    loss_a, acc_a = head_alt.evaluate(Xte_a, yte_a, verbose=0)
    stage_a_alt = {
        "input_size": ALT_SIZE,
        "dropout": BEST_DROPOUT,
        "best_val_accuracy": round(float(max(h_alt.history["val_accuracy"])), 4),
        "test_accuracy": round(float(acc_a), 4),
        "test_loss": round(float(loss_a), 4),
    }
    print(f"Етап A на {ALT_SIZE}x{ALT_SIZE}: test accuracy {acc_a:.4f}")
    del Xtr_a, Xva_a, Xte_a, base_alt
else:
    print("Для цієї мережі додатковий розмір входу не задано.")'''


STAGE_A_TEST = r'''# Точність етапу A на тестовому наборі — з найкращим Dropout.
tf.keras.utils.set_random_seed(42)
head_best = build_head(BEST_DROPOUT, Xtr.shape[1])
hist_head = head_best.fit(Xtr, ytr, validation_data=(Xva, yva),
                          epochs=HEAD_EPOCHS, batch_size=64, verbose=0)
loss_a, acc_a = head_best.evaluate(Xte, yte, verbose=0)
stage_a_alt = None      # перезапишеться, якщо далі є клітинка з ALT_SIZE
stage_a = {
    "dropout": BEST_DROPOUT,
    "feature_extraction_sec": round(feature_sec, 1),
    "best_val_accuracy": round(float(max(hist_head.history["val_accuracy"])), 4),
    "test_accuracy": round(float(acc_a), 4),
    "test_loss": round(float(loss_a), 4),
}
print(f"Етап A ({BASE_NAME}, Dropout {BEST_DROPOUT}): test accuracy {acc_a:.4f}, loss {loss_a:.4f}")

# Ознаки більше не потрібні — звільняємо пам'ять перед етапами B і C.
del Xtr, Xva, Xte, base_feat'''


PLOT_HISTORY = r'''def plot_history(hist, title, out_png):
    """Точність і втрати, навчання проти валідації (контроль перенавчання)."""
    h = hist.history
    ep = range(1, len(h["accuracy"]) + 1)
    plt.figure(figsize=(12, 4))
    for i, (m, name) in enumerate([("accuracy", "Точність"), ("loss", "Втрати")]):
        plt.subplot(1, 2, i + 1)
        plt.plot(ep, h[m], "o-", label="Навчання")
        plt.plot(ep, h["val_" + m], "s-", label="Валідація")
        plt.title(f"{name} — {title}")
        plt.xlabel("Епоха")
        plt.legend()
        plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(RESULTS / out_png, dpi=110, bbox_inches="tight")
    plt.show()


def stage_record(hist, sec, model):
    return {
        "epochs_done": len(hist.history["accuracy"]),
        "train_time_sec": round(sec, 1),
        "trainable_params": int(sum(np.prod(w.shape) for w in model.trainable_weights)),
        "history": {k: [round(float(v), 4) for v in vals] for k, vals in hist.history.items()},
    }'''


STAGE_B = r'''# ЕТАП B — заморожена база + аугментація, навчання end-to-end.
from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint

base = build_base(INPUT_SIZE)        # без pooling: власна голова нижче

inputs = layers.Input(shape=(INPUT_SIZE, INPUT_SIZE, 3))
# training=False тримає BatchNormalization у режимі висновування — інакше
# ковзні середні ImageNet перезапишуться статистикою котів і собак.
x = base(inputs, training=False)
x = layers.GlobalAveragePooling2D()(x)
x = layers.Dense(256, activation="relu")(x)
x = layers.Dropout(BEST_DROPOUT)(x)
outputs = layers.Dense(1, activation="sigmoid")(x)
model = models.Model(inputs, outputs, name=f"{SLUG}_transfer")

model.compile(optimizer=optimizers.Adam(1e-4), loss="binary_crossentropy",
              metrics=["accuracy"])

summary_lines = []
model.summary(print_fn=lambda s: summary_lines.append(s))
(RESULTS / "raw" / f"{TASK}_model_summary.txt").write_text("\n".join(summary_lines),
                                                           encoding="utf-8")
total_params = int(model.count_params())
trainable_b = int(sum(np.prod(w.shape) for w in model.trainable_weights))
print(f"Усього параметрів: {total_params:,}, навчаних на етапі B: {trainable_b:,}")

ckpt = str(MODELS / f"lab8_{SLUG}_frozen.keras")
callbacks = [
    EarlyStopping(monitor="val_loss", patience=3, restore_best_weights=True),
    ModelCheckpoint(ckpt, monitor="val_loss", save_best_only=True),
]

t0 = time.time()
hist_frozen = model.fit(train_aug, epochs=EPOCHS_FROZEN, validation_data=val_plain,
                        callbacks=callbacks, verbose=1)
time_frozen = time.time() - t0
print(f"Етап B: {time_frozen / 60:.1f} хв")'''


STAGE_B_PLOT = r'''plot_history(hist_frozen, f"{BASE_NAME}, етап B (заморожена база + аугментація)",
             f"{TASK}_history_frozen.png")
loss_b, acc_b = model.evaluate(test_static, steps=math.ceil(nb_test / BATCH), verbose=0)
stage_b = stage_record(hist_frozen, time_frozen, model)
stage_b.update({"test_accuracy": round(float(acc_b), 4), "test_loss": round(float(loss_b), 4)})
print(f"Етап B: test accuracy {acc_b:.4f}, loss {loss_b:.4f}")'''


STAGE_C = r'''# ЕТАП C — донавчання (fine-tuning) верхніх шарів бази.
# Два правила, без яких донавчання руйнує мережу:
#   1) розморожуємо лише верхні шари, починаючи з UNFREEZE_FROM;
#   2) BatchNormalization лишається замороженим — його ковзні середні взяті з
#      ImageNet і при малому батчі перенавчаються у шум.
base.trainable = True
set_trainable = False
frozen_bn = 0
for layer in base.layers:
    if layer.name == UNFREEZE_FROM:
        set_trainable = True
    layer.trainable = set_trainable
    if isinstance(layer, layers.BatchNormalization):
        layer.trainable = False
        frozen_bn += 1

unfrozen = [l.name for l in base.layers if l.trainable]
print(f"Розморожено з шару {UNFREEZE_FROM}: {len(unfrozen)} шарів "
      f"(перший — {unfrozen[0]}, останній — {unfrozen[-1]})")
print(f"BatchNormalization лишено замороженими: {frozen_bn}")

# Швидкість навчання на два порядки менша, ніж на етапі B: великий крок зіпсував
# би вже готові ознаки ImageNet.
model.compile(optimizer=optimizers.Adam(1e-5), loss="binary_crossentropy",
              metrics=["accuracy"])
trainable_c = int(sum(np.prod(w.shape) for w in model.trainable_weights))
print(f"Навчаних параметрів на етапі C: {trainable_c:,} з {total_params:,}")

ckpt_ft = str(MODELS / f"lab8_{SLUG}_finetuned.keras")
t0 = time.time()
hist_finetune = model.fit(
    train_aug, epochs=EPOCHS_FINETUNE, validation_data=val_plain,
    callbacks=[EarlyStopping(monitor="val_loss", patience=3, restore_best_weights=True),
               ModelCheckpoint(ckpt_ft, monitor="val_loss", save_best_only=True)],
    verbose=1)
time_finetune = time.time() - t0
print(f"Етап C: {time_finetune / 60:.1f} хв")'''


STAGE_C_PLOT = r'''plot_history(hist_finetune, f"{BASE_NAME}, етап C (донавчання з {UNFREEZE_FROM})",
             f"{TASK}_history_finetune.png")
loss_c, acc_c = model.evaluate(test_static, steps=math.ceil(nb_test / BATCH), verbose=0)
stage_c = stage_record(hist_finetune, time_finetune, model)
stage_c.update({"test_accuracy": round(float(acc_c), 4), "test_loss": round(float(loss_c), 4),
                "unfreeze_from": UNFREEZE_FROM, "unfrozen_layers": len(unfrozen),
                "frozen_batchnorm": frozen_bn})
print(f"Етап C: test accuracy {acc_c:.4f}, loss {loss_c:.4f}")'''


EVALUATE = r'''# Оцінка найкращої моделі на тестовому наборі: 3750 зображень, яких мережа
# не бачила ні під час навчання, ні під час валідації.
from sklearn.metrics import classification_report, confusion_matrix

test_static.reset()
probs = model.predict(test_static, steps=math.ceil(nb_test / BATCH), verbose=1)[:nb_test].ravel()
y_true = test_static.classes[:nb_test]
y_pred = (probs > 0.5).astype(int)

cm = confusion_matrix(y_true, y_pred)
report = classification_report(y_true, y_pred, target_names=["cat", "dog"], digits=4)
(RESULTS / "raw" / f"{TASK}_classification_report.txt").write_text(report, encoding="utf-8")
print(report)

fig, ax = plt.subplots(figsize=(4.6, 4.2))
ax.imshow(cm, cmap="Blues")
ax.set_xticks([0, 1], ["cat", "dog"])
ax.set_yticks([0, 1], ["cat", "dog"])
ax.set_xlabel("Передбачено")
ax.set_ylabel("Насправді")
ax.set_title(f"{BASE_NAME}: матриця помилок")
for i in range(2):
    for j in range(2):
        ax.text(j, i, cm[i][j], ha="center", va="center",
                color="white" if cm[i][j] > cm.max() / 2 else "black")
plt.tight_layout()
plt.savefig(RESULTS / f"{TASK}_confusion_matrix.png", dpi=110, bbox_inches="tight")
plt.show()'''


PREDICT_HELPERS = r'''# Пункт 5: розпізнавання власних зображень, яких не було ні в навчальному, ні
# в валідаційному, ні в тестовому наборі. Беремо ті самі 36 зображень з
# Wikimedia Commons, що в лабораторній 7 — так порівняння «до/після перенесення
# навчання» відбувається на однакових даних (атрибуція: lab7/results/image_sources.md).
from tensorflow.keras.utils import img_to_array, load_img

if IN_COLAB and not MY_IMAGES.is_dir():
    with zipfile.ZipFile("/content/drive/MyDrive/dl_lab8/my_images.zip") as z:
        z.extractall("/content/my_images")
print("Власні зображення:", MY_IMAGES)


def expected_class(stem):
    """Правильна відповідь береться з імені файлу (crop_ — обрізана версія)."""
    s = stem[len("crop_"):] if stem.startswith("crop_") else stem
    return "cat" if s.startswith("cat") else "dog"


def predict_images(folder_name, title, out_png):
    """Передбачення з препроцесією саме цієї мережі + сітка зображень."""
    folder = MY_IMAGES / folder_name
    paths = sorted(p for p in folder.iterdir()
                   if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    cols = 5
    rows = (len(paths) + cols - 1) // cols
    plt.figure(figsize=(cols * 3.1, rows * 3.5))
    records = []
    for i, p in enumerate(paths):
        x = img_to_array(load_img(p, target_size=TARGET))
        x = preprocess_input(np.expand_dims(x, axis=0))
        prob = float(model.predict(x, verbose=0)[0][0])
        label = "dog" if prob > 0.5 else "cat"
        exp = expected_class(p.stem)
        ok = label == exp
        records.append({"file": p.name, "prob_dog": round(prob, 4), "predicted": label,
                        "expected": exp, "correct": ok})
        ax = plt.subplot(rows, cols, i + 1)
        ax.axis("off")
        ax.imshow(load_img(p))
        ax.set_title(f"{p.stem[:22]}\n{label}  p={prob:.3f}  {'+' if ok else '-'}",
                     fontsize=8, color="green" if ok else "red")
    correct = sum(r["correct"] for r in records)
    plt.suptitle(f"{title} — правильно {correct} з {len(records)}")
    plt.tight_layout()
    plt.savefig(RESULTS / out_png, dpi=110, bbox_inches="tight")
    plt.show()
    for r in records:
        print(r)
    print(f"\nПравильно: {correct} з {len(records)}")
    return records'''


PREDICT_RUN = r'''records_my = predict_images(
    "task4_cats_dogs", f"{BASE_NAME}: 20 власних зображень", f"{TASK}_predictions_my.png")'''


PREDICT_HARD = r'''# Ті 10 «складних» зображень, на яких мережа з нуля в лабораторній 7 дала лише
# 4 правильних відповіді з 10 — головний тест на користь перенесення навчання.
records_hard = predict_images(
    "task4_hard", f"{BASE_NAME}: складні зображення", f"{TASK}_predictions_hard.png")'''


PREDICT_CROPPED = r'''# Обрізані версії складних зображень (у лабораторній 7 — 2 правильних з 6).
records_cropped = predict_images(
    "task4_cropped", f"{BASE_NAME}: обрізані складні зображення",
    f"{TASK}_predictions_cropped.png")'''


SAVE_MODEL = r'''# Пункт 6: збереження навченої моделі. Файли .keras не комітяться в репозиторій
# (вони завеликі), тому основна копія лежить на Google Drive, а метадані —
# у models/README.md.
import hashlib

model_path = MODELS / f"lab8_{SLUG}_finetuned.keras"
model.save(model_path)
digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
size = model_path.stat().st_size
print(f"{model_path.name}: {size / 1e6:.1f} МБ, sha256 {digest[:16]}…")

if DRIVE_OUT:
    import shutil as _sh

    _sh.copy2(model_path, DRIVE_OUT / "models" / model_path.name)
    print("Копія на Drive:", DRIVE_OUT / "models" / model_path.name)'''


EXPORT = r'''# Усі числа ноутбука — в один JSON, який далі читає scripts/collect_results.py.
metrics = {
    "task": f"{TASK}_{SLUG}",
    "base": BASE_NAME,
    "input_size": [INPUT_SIZE, INPUT_SIZE],
    "batch_size": BATCH,
    "subset": {"train_per_class": n_train, "val_per_class": n_val,
               "test_per_class": n_test, "full_dataset": SUBSET is None},
    "samples": {"train": int(nb_train), "val": int(nb_val), "test": int(nb_test)},
    "class_indices": train_static.class_indices,
    "dir_tree": dir_tree,
    "feature_dim": int(FEATURE_DIM),
    "params": {"base": base_params, "total": total_params,
               "trainable_stage_b": trainable_b, "trainable_stage_c": trainable_c},
    "dropouts": DROPOUTS,
    "dropout_runs": dropout_runs,
    "best_dropout": BEST_DROPOUT,
    "stage_a": stage_a,
    "stage_a_alt": stage_a_alt,
    "stage_b": stage_b,
    "stage_c": stage_c,
    "test": {"accuracy": round(float(acc_c), 4), "loss": round(float(loss_c), 4),
             "confusion_matrix": cm.tolist(), "classification_report": report},
    "own_images": records_my,
    "hard_images": records_hard,
    "cropped_images": records_cropped,
    "model": {"file": model_path.name, "size_bytes": size, "sha256": digest},
    "environment": {
        "tensorflow": tf.__version__,
        "keras": tf.keras.__version__,
        "in_colab": IN_COLAB,
        "gpu": [d.name for d in gpus],
    },
}
out = RESULTS / "raw" / f"{TASK}.json"
out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
print("Збережено", out)'''


ZIP_DOWNLOAD = r'''# Зіп з усіма результатами цього ноутбука: покласти у dl/lab8/results/incoming/.
zip_name = f"lab8_{TASK}_results.zip"
zip_path = Path("/content") / zip_name if IN_COLAB else RESULTS / zip_name
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
    for p in sorted(RESULTS.rglob("*")):
        # suffix != ".zip" — щоб архів не спробував запакувати сам себе
        # (локально він створюється всередині results/).
        if p.is_file() and TASK in p.name and p.suffix != ".zip":
            z.write(p, p.relative_to(RESULTS))
print(zip_path, f"{zip_path.stat().st_size / 1e6:.1f} МБ")
with zipfile.ZipFile(zip_path) as z:
    print("\n".join(z.namelist()))

if DRIVE_OUT:
    import shutil as _sh

    _sh.copy2(zip_path, DRIVE_OUT / "results" / zip_name)
if IN_COLAB:
    from google.colab import files

    files.download(str(zip_path))'''

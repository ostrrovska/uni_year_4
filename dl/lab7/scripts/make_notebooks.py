"""Генерація ноутбуків лабораторної 7 (завдання 1, 2, 4 + базовий без валідації).

Кожен ноутбук працює і локально, і в Colab: прапорець IN_COLAB на початку,
google.colab використовується лише в гілці Colab.
"""
from pathlib import Path

import nbformat as nbf

LAB_ROOT = Path(__file__).resolve().parent.parent
NB_DIR = LAB_ROOT / "notebooks"

BOOTSTRAP = '''# Визначення середовища та базових шляхів (працює і локально, і в Colab)
import json
import os
import time
from pathlib import Path

try:
    import google.colab  # noqa: F401
    IN_COLAB = True
except ImportError:
    IN_COLAB = False

LAB_ROOT = Path("/content") if IN_COLAB else Path.cwd().parent   # notebooks/ -> dl/lab7
DATA = LAB_ROOT / "data"
MY_IMAGES = LAB_ROOT / "my_images"
RESULTS = LAB_ROOT / "results"
MODELS = LAB_ROOT / "models"
for d in (DATA, RESULTS / "raw", MODELS):
    d.mkdir(parents=True, exist_ok=True)
print("IN_COLAB =", IN_COLAB)
print("LAB_ROOT =", LAB_ROOT)'''

HORSE_DOWNLOAD = '''import urllib.request
import zipfile

URLS = {{
    "horse-or-human.zip": "https://storage.googleapis.com/learning-datasets/horse-or-human.zip",
{validation_url}}}
TRAIN_DIR = DATA / "horse-or-human"
VALID_DIR = DATA / "validation-horse-or-human"

for name, url in URLS.items():
    target = TRAIN_DIR if name == "horse-or-human.zip" else VALID_DIR
    zip_path = DATA / name
    if not (target / "horses").is_dir():
        if not zip_path.exists():
            print("Завантаження", name, "...")
            urllib.request.urlretrieve(url, zip_path)
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(target)
    print(target, "->", sorted(os.listdir(target)))'''

PREDICT_HELPERS = '''import matplotlib.pyplot as plt
import numpy as np
from tensorflow.keras.utils import img_to_array, load_img


def expected_class(stem):
    """Правильна відповідь береться з префікса імені файлу."""
    if stem.startswith("human"):
        return "human"
    if stem.startswith("horse"):
        return "horse"
    return None          # both_* — на зображенні одночасно людина і кінь


def own_image_paths(folder_name):
    """Локально — з my_images/<folder>, у Colab — через files.upload()."""
    if IN_COLAB:
        from google.colab import files
        target = Path("/content/my_images") / folder_name
        target.mkdir(parents=True, exist_ok=True)
        print("Оберіть власні зображення для завантаження:")
        for fn, data in files.upload().items():
            (target / fn).write_bytes(data)
    else:
        target = MY_IMAGES / folder_name
    return sorted(p for p in target.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})


def predict_images(model, paths, target_size, title, out_png):
    """Передбачення + сітка зображень; повертає рядки для таблиці у звіті."""
    cols = 4
    rows = (len(paths) + cols - 1) // cols
    plt.figure(figsize=(cols * 3.3, rows * 3.7))
    records = []
    for i, p in enumerate(paths):
        img = load_img(p, target_size=target_size)
        x = np.expand_dims(img_to_array(img) / 255.0, axis=0)
        prob = float(model.predict(x, verbose=0)[0][0])
        label = "human" if prob > 0.5 else "horse"
        exp = expected_class(p.stem)
        ok = None if exp is None else (label == exp)
        records.append({"file": p.name, "prob_human": round(prob, 4), "predicted": label,
                        "expected": exp, "correct": ok})
        ax = plt.subplot(rows, cols, i + 1)
        ax.axis("off")
        ax.imshow(load_img(p))
        mark = "" if ok is None else ("  +" if ok else "  -")
        ax.set_title(f"{p.stem[:24]}\\n{label}  p={prob:.3f}{mark}", fontsize=8)
    plt.suptitle(title)
    plt.tight_layout()
    plt.savefig(out_png, dpi=110, bbox_inches="tight")
    plt.show()
    for r in records:
        print(r)
    known = [r for r in records if r["correct"] is not None]
    print(f"\\nПравильно: {sum(r['correct'] for r in known)} з {len(known)} "
          f"(файли both_* не враховано)")
    return records'''


def md(text):
    return nbf.v4.new_markdown_cell(text)


def code(text):
    return nbf.v4.new_code_cell(text)


def summary_capture(var, out_name):
    return f'''summary_lines = []
{var}.summary(print_fn=lambda s: summary_lines.append(s))
(RESULTS / "raw" / "{out_name}").write_text("\\n".join(summary_lines), encoding="utf-8")
total_params = int({var}.count_params())
print("Усього параметрів:", total_params)'''


def history_plot(hist_var, title, out_png, with_val=True):
    val = '''    plt.plot(epochs_range, h["val_" + m], "s-", label="Валідація")
''' if with_val else ""
    return f'''acc_hist = {hist_var}.history
epochs_range = range(1, len(acc_hist["accuracy"]) + 1)
plt.figure(figsize=(12, 4))
for i, (m, name) in enumerate([("accuracy", "Точність"), ("loss", "Втрати")]):
    plt.subplot(1, 2, i + 1)
    h = acc_hist
    plt.plot(epochs_range, h[m], "o-", label="Навчання")
{val}    plt.title(name + " — {title}")
    plt.xlabel("Епоха")
    plt.legend()
    plt.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(RESULTS / "{out_png}", dpi=110, bbox_inches="tight")
plt.show()'''


# ---------------------------------------------------------------- завдання 0
def task0():
    nb = nbf.v4.new_notebook()
    nb.cells = [
        md("""# Лабораторна 7 — базовий ноутбук БЕЗ валідації (пункт 1)

Базовий приклад із лекції: класифікація **horses vs humans**, вхід 300×300, 5 пар Conv+MaxPooling,
`RMSprop(learning_rate=0.001)`, `steps_per_epoch=8`, `epochs=15`.

Цей ноутбук потрібен як **точка відліку**: ті самі власні зображення розпізнаються моделлю,
навченою без валідаційного набору, щоб потім порівняти з завданнями 1 і 2."""),
        md("Визначаємо, де виконується ноутбук, і створюємо шляхи до даних/результатів."),
        code(BOOTSTRAP),
        md("**Крок 1.** Завантаження навчального набору (як у базовому ноутбуці, без валідаційного)."),
        code(HORSE_DOWNLOAD.format(validation_url="")),
        md("**Крок 2.** Перевірка імен файлів і кількості зображень у каталогах."),
        code('''train_horse_dir = TRAIN_DIR / "horses"
train_human_dir = TRAIN_DIR / "humans"
train_horse_names = sorted(os.listdir(train_horse_dir))
train_human_names = sorted(os.listdir(train_human_dir))

print(train_horse_names[:10])
print(train_human_names[:10])
print("total training horse images:", len(train_horse_names))
print("total training human images:", len(train_human_names))'''),
        md("**Крок 3.** Перегляд кількох навчальних зображень (8 коней + 8 людей)."),
        code('''import matplotlib.image as mpimg
import matplotlib.pyplot as plt

nrows, ncols, pic_index = 4, 4, 8
fig = plt.gcf()
fig.set_size_inches(ncols * 4, nrows * 4)
next_horse_pix = [train_horse_dir / f for f in train_horse_names[pic_index - 8:pic_index]]
next_human_pix = [train_human_dir / f for f in train_human_names[pic_index - 8:pic_index]]
for i, img_path in enumerate(next_horse_pix + next_human_pix):
    sp = plt.subplot(nrows, ncols, i + 1)
    sp.axis("Off")
    plt.imshow(mpimg.imread(img_path))
plt.savefig(RESULTS / "task0_dataset_sample.png", dpi=90, bbox_inches="tight")
plt.show()'''),
        md("**Крок 4.** Модель із базового прикладу: 5 пар Conv2D+MaxPooling, Flatten, Dense(512), Dense(1, sigmoid)."),
        code('''import tensorflow as tf

model = tf.keras.models.Sequential([
    tf.keras.layers.Conv2D(16, (3, 3), activation="relu", input_shape=(300, 300, 3)),
    tf.keras.layers.MaxPooling2D(2, 2),
    tf.keras.layers.Conv2D(32, (3, 3), activation="relu"),
    tf.keras.layers.MaxPooling2D(2, 2),
    tf.keras.layers.Conv2D(64, (3, 3), activation="relu"),
    tf.keras.layers.MaxPooling2D(2, 2),
    tf.keras.layers.Conv2D(64, (3, 3), activation="relu"),
    tf.keras.layers.MaxPooling2D(2, 2),
    tf.keras.layers.Conv2D(64, (3, 3), activation="relu"),
    tf.keras.layers.MaxPooling2D(2, 2),
    tf.keras.layers.Flatten(),
    tf.keras.layers.Dense(512, activation="relu"),
    tf.keras.layers.Dense(1, activation="sigmoid"),   # 0 = horses, 1 = humans
])
model.summary()'''),
        md("Компіляція з параметрами базового прикладу: `binary_crossentropy`, `RMSprop(learning_rate=0.001)`."),
        code('''from tensorflow.keras.optimizers import RMSprop

model.compile(loss="binary_crossentropy",
              optimizer=RMSprop(learning_rate=0.001),
              metrics=["accuracy"])
''' + summary_capture("model", "task0_model_summary.txt")),
        md("**Крок 5.** Генератор навчальних даних: нормалізація `rescale=1/255`, `target_size=(300, 300)`, `batch_size=128`."),
        code('''from tensorflow.keras.preprocessing.image import ImageDataGenerator

train_datagen = ImageDataGenerator(rescale=1 / 255)
train_generator = train_datagen.flow_from_directory(
    str(TRAIN_DIR),
    target_size=(300, 300),
    batch_size=128,
    class_mode="binary")
print("Класи:", train_generator.class_indices)'''),
        md("**Крок 6.** Навчання 15 епох по 8 кроків, **без** валідаційного набору. Заміряємо час."),
        code('''start = time.time()
history = model.fit(train_generator, steps_per_epoch=8, epochs=15, verbose=2)
train_time = time.time() - start
print(f"Час навчання: {train_time:.1f} с")'''),
        md("Графіки навчання (валідаційних кривих немає — у базовому ноутбуці валідація відсутня)."),
        code(history_plot("history", "базовий ноутбук (без валідації)", "task0_history.png", with_val=False)),
        md("""**Крок 7 (пункт 1).** Розпізнавання власних зображень.

Клас 1 = *humans*, клас 0 = *horses*. Правильна відповідь береться з префікса імені файлу
(`human_*`, `horse_*`); файли `both_*` містять і людину, і коня — для них правильної відповіді немає."""),
        code(PREDICT_HELPERS),
        code('''paths = own_image_paths("task1_horses_humans")
print("Знайдено зображень:", len(paths))
records0 = predict_images(model, paths, (300, 300),
                          "Базова модель без валідації (300×300)",
                          RESULTS / "task0_predictions.png")'''),
        md("**Крок 8.** Збереження моделі та чисел для звіту."),
        code('''model.save(MODELS / "task0_base_300.keras")
metrics = {
    "task": "task0_base_no_validation",
    "input_size": [300, 300],
    "optimizer": "RMSprop(learning_rate=0.001)",
    "steps_per_epoch": 8,
    "epochs_planned": 15,
    "epochs_done": len(history.history["accuracy"]),
    "total_params": total_params,
    "train_time_sec": round(train_time, 1),
    "history": {k: [round(float(v), 4) for v in vals] for k, vals in history.history.items()},
    "train_samples": int(train_generator.samples),
    "class_indices": train_generator.class_indices,
    "own_images": records0,
}
(RESULTS / "raw" / "task0.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2),
                                            encoding="utf-8")
print("Збережено results/raw/task0.json")'''),
    ]
    return nb


# ------------------------------------------------------- завдання 1 та 2
def task_1_2(size, task_name, title_md, model_code, extra_md):
    nb = nbf.v4.new_notebook()
    nb.cells = [
        md(title_md),
        md("Визначаємо середовище і шляхи."),
        code(BOOTSTRAP),
        md("""**Пункти 2–3.** Завантажуємо **два** набори: навчальний (`./horse-or-human`) і
валідаційний (`./validation-horse-or-human`) — другий модель під час навчання не бачить."""),
        code(HORSE_DOWNLOAD.format(
            validation_url='    "validation-horse-or-human.zip": '
                           '"https://storage.googleapis.com/learning-datasets/validation-horse-or-human.zip",\n')),
        md("**Пункт 4.** Перевірка імен файлів у каталогах навчання і валідації."),
        code('''train_horse_dir = TRAIN_DIR / "horses"
train_human_dir = TRAIN_DIR / "humans"
validation_horse_dir = VALID_DIR / "horses"
validation_human_dir = VALID_DIR / "humans"

train_horse_names = sorted(os.listdir(train_horse_dir))
train_human_names = sorted(os.listdir(train_human_dir))
validation_horse_names = sorted(os.listdir(validation_horse_dir))
validation_human_names = sorted(os.listdir(validation_human_dir))

print("TRAIN horses:", train_horse_names[:5])
print("TRAIN humans:", train_human_names[:5])
print("VAL   horses:", validation_horse_names[:5])
print("VAL   humans:", validation_human_names[:5])
print("total training horse images:", len(train_horse_names))
print("total training human images:", len(train_human_names))
print("total validation horse images:", len(validation_horse_names))
print("total validation human images:", len(validation_human_names))'''),
        md("**Пункт 5.** Перегляд кількох навчальних зображень."),
        code(f'''import matplotlib.image as mpimg
import matplotlib.pyplot as plt

nrows, ncols, pic_index = 4, 4, 8
fig = plt.gcf()
fig.set_size_inches(ncols * 4, nrows * 4)
next_horse_pix = [train_horse_dir / f for f in train_horse_names[pic_index - 8:pic_index]]
next_human_pix = [train_human_dir / f for f in train_human_names[pic_index - 8:pic_index]]
for i, img_path in enumerate(next_horse_pix + next_human_pix):
    sp = plt.subplot(nrows, ncols, i + 1)
    sp.axis("Off")
    plt.imshow(mpimg.imread(img_path))
plt.savefig(RESULTS / "{task_name}_dataset_sample.png", dpi=90, bbox_inches="tight")
plt.show()'''),
        md(extra_md),
        code(model_code),
        md("**Пункт 8.** Компіляція з тими самими параметрами: `binary_crossentropy`, `RMSprop(learning_rate=0.001)`."),
        code('''from tensorflow.keras.optimizers import RMSprop

model.compile(loss="binary_crossentropy",
              optimizer=RMSprop(learning_rate=0.001),
              metrics=["accuracy"])
''' + summary_capture("model", f"{task_name}_model_summary.txt")),
        md(f"""**Пункт 9{'/16' if size == 150 else ''}.** Два генератори: навчальний і **валідаційний**.
Обидва нормалізують пікселі (`rescale=1/255`), але читають з різних каталогів,
`target_size=({size}, {size})`. У виводі має бути `Found 1027 images` і `Found 256 images` —
це доказ, що валідаційний генератор читає саме свій каталог."""),
        code(f'''from tensorflow.keras.preprocessing.image import ImageDataGenerator

train_datagen = ImageDataGenerator(rescale=1 / 255)
validation_datagen = ImageDataGenerator(rescale=1 / 255)

train_generator = train_datagen.flow_from_directory(
    str(TRAIN_DIR),
    target_size=({size}, {size}),
    batch_size=128,
    class_mode="binary")

validation_generator = validation_datagen.flow_from_directory(
    str(VALID_DIR),
    target_size=({size}, {size}),
    batch_size=32,
    class_mode="binary")

print("Класи train:", train_generator.class_indices)
print("Класи val:  ", validation_generator.class_indices)'''),
        md("""**Пункти 10–11.** Навчання з валідацією: додано `validation_data` і `validation_steps=8`.
Наприкінці кожної епохи, крім `loss/accuracy`, друкуються `val_loss/val_accuracy`."""),
        code('''start = time.time()
history = model.fit(
    train_generator,
    steps_per_epoch=8,
    epochs=15,
    verbose=2,
    validation_data=validation_generator,
    validation_steps=8)
train_time = time.time() - start
print(f"Час навчання: {train_time:.1f} с")'''),
        md("**Пункт 12.** Графіки історії навчання: точність і втрати на навчальному та валідаційному наборах."),
        code(history_plot("history", f"вхід {size}×{size}", f"{task_name}_history.png")),
        code('''acc, val_acc = history.history["accuracy"], history.history["val_accuracy"]
loss, val_loss = history.history["loss"], history.history["val_loss"]
print(f"Остання епоха: acc={acc[-1]:.4f}, val_acc={val_acc[-1]:.4f}, "
      f"loss={loss[-1]:.4f}, val_loss={val_loss[-1]:.4f}")
print(f"Найкраща val_accuracy: {max(val_acc):.4f} (епоха {val_acc.index(max(val_acc)) + 1})")
print(f"Розрив train-val на останній епосі: {acc[-1] - val_acc[-1]:+.4f}")'''),
        md(f"""**Пункт {"13" if size == 300 else "18"}.** Розпізнавання тих самих власних зображень,
що і в базовому ноутбуці. Клас 1 = *humans*, клас 0 = *horses*."""),
        code(PREDICT_HELPERS),
        code(f'''paths = own_image_paths("task1_horses_humans")
print("Знайдено зображень:", len(paths))
records = predict_images(model, paths, ({size}, {size}),
                         "Модель {size}×{size} з валідацією",
                         RESULTS / "{task_name}_predictions.png")'''),
        md("Збереження моделі та чисел для звіту."),
        code(f'''model.save(MODELS / "{task_name}_horses_humans_{size}.keras")
metrics = {{
    "task": "{task_name}",
    "input_size": [{size}, {size}],
    "optimizer": "RMSprop(learning_rate=0.001)",
    "steps_per_epoch": 8,
    "validation_steps": 8,
    "epochs_planned": 15,
    "epochs_done": len(history.history["accuracy"]),
    "total_params": total_params,
    "train_time_sec": round(train_time, 1),
    "history": {{k: [round(float(v), 4) for v in vals] for k, vals in history.history.items()}},
    "train_samples": int(train_generator.samples),
    "validation_samples": int(validation_generator.samples),
    "class_indices": train_generator.class_indices,
    "own_images": records,
}}
(RESULTS / "raw" / "{task_name}.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2),
                                                  encoding="utf-8")
print("Збережено results/raw/{task_name}.json")'''),
    ]
    return nb


MODEL_300 = '''import tensorflow as tf

model = tf.keras.models.Sequential([
    tf.keras.layers.Conv2D(16, (3, 3), activation="relu", input_shape=(300, 300, 3)),
    tf.keras.layers.MaxPooling2D(2, 2),
    tf.keras.layers.Conv2D(32, (3, 3), activation="relu"),
    tf.keras.layers.MaxPooling2D(2, 2),
    tf.keras.layers.Conv2D(64, (3, 3), activation="relu"),
    tf.keras.layers.MaxPooling2D(2, 2),
    tf.keras.layers.Conv2D(64, (3, 3), activation="relu"),
    tf.keras.layers.MaxPooling2D(2, 2),
    tf.keras.layers.Conv2D(64, (3, 3), activation="relu"),
    tf.keras.layers.MaxPooling2D(2, 2),
    tf.keras.layers.Flatten(),
    tf.keras.layers.Dense(512, activation="relu"),
    tf.keras.layers.Dense(1, activation="sigmoid"),   # 0 = horses, 1 = humans
])
model.summary()'''

MODEL_150 = '''import tensorflow as tf

model = tf.keras.models.Sequential([
    # Вхід 150×150 замість 300×300
    tf.keras.layers.Conv2D(16, (3, 3), activation="relu", input_shape=(150, 150, 3)),
    tf.keras.layers.MaxPooling2D(2, 2),
    tf.keras.layers.Conv2D(32, (3, 3), activation="relu"),
    tf.keras.layers.MaxPooling2D(2, 2),
    tf.keras.layers.Conv2D(64, (3, 3), activation="relu"),
    tf.keras.layers.MaxPooling2D(2, 2),
    # четверта і п'ята пари Conv+MaxPooling вилучені (пункт 14)
    tf.keras.layers.Flatten(),
    tf.keras.layers.Dense(512, activation="relu"),
    tf.keras.layers.Dense(1, activation="sigmoid"),   # 0 = horses, 1 = humans
])
model.summary()'''


# ---------------------------------------------------------------- завдання 4
def task4():
    nb = nbf.v4.new_notebook()
    nb.cells = [
        md("""# Лабораторна 7. Завдання 4 — Dogs vs Cats (пункти 21–26)

Набір Kaggle *Dogs vs Cats*: `train.zip` містить 25 000 фото з мітками в імені файлу
(`cat.0.jpg … cat.12499.jpg`, `dog.0.jpg … dog.12499.jpg`).
`flow_from_directory` вимагає структуру «папка = клас», тому спершу власний скрипт
розкладає набір на **train / val / test** з підпапками `cats/` і `dogs/`."""),
        md("Середовище і шляхи."),
        code(BOOTSTRAP),
        md("""**Пункт 21, крок 1.** Вихідні дані.

Локально: 25 000 jpg уже розпаковані скриптом `scripts/extract_data.py` у `data/dogs_vs_cats_raw/train`.
У Colab: монтуємо Google Drive і розпаковуємо `dogs-vs-cats.zip` → `train.zip` → `/content/train`
(архів 812 МБ завантажувати через браузер недоцільно)."""),
        code('''if IN_COLAB:
    import zipfile
    from google.colab import drive

    drive.mount("/content/drive")
    ZIP_PATH = "/content/drive/MyDrive/dogs-vs-cats.zip"   # змініть, якщо файл в іншій папці
    with zipfile.ZipFile(ZIP_PATH) as z:
        z.extract("train.zip", "/content")
    with zipfile.ZipFile("/content/train.zip") as z:
        z.extractall("/content")
    RAW_TRAIN = Path("/content/train")
else:
    RAW_TRAIN = DATA / "dogs_vs_cats_raw" / "train"

files = sorted(os.listdir(RAW_TRAIN))
print(RAW_TRAIN, "->", len(files), "файлів")
print(files[:3], "...", files[-3:])'''),
        md("""**Пункт 21, крок 2.** Скрипт розділення на train / val / test (той самий код, що в
`scripts/prepare_dataset.py`): `create_directory` створює чисту структуру, `copy_images` копіює
файли за діапазоном індексів.

`PER_CLASS_*` задають розмір набору. Повний набір — 8750 / 1875 / 1875 на клас (70/15/15),
на цьому комп'ютері одна епоха триває ≈4.9 хв (замір у `results/raw/timing_probe.json`),
тому прогін зроблено на **повному наборі**; `PER_CLASS_*` дозволяють узяти підмножину."""),
        code('''import shutil

BASE_DIR = DATA / "cats_dogs"
train_dir, val_dir, test_dir = BASE_DIR / "train", BASE_DIR / "val", BASE_DIR / "test"

# Розмір набору: None -> повний набір (70/15/15 від 12500 на клас).
# Замір на цьому CPU: 0.47 с/крок -> ~4.9 хв на епоху при 546 кроках, тобто повний
# набір прийнятний (results/raw/timing_probe.json). Для швидкого прогону можна
# поставити, наприклад, 2000 / 500 / 500.
PER_CLASS_TRAIN = None
PER_CLASS_VAL = None
PER_CLASS_TEST = None


def create_directory(dir_name):
    if os.path.exists(dir_name):
        shutil.rmtree(dir_name)
    os.makedirs(dir_name)
    os.makedirs(os.path.join(dir_name, "cats"))
    os.makedirs(os.path.join(dir_name, "dogs"))


def copy_images(start_index, end_index, source_dir, dest_dir):
    for i in range(start_index, end_index):
        shutil.copy2(os.path.join(source_dir, f"cat.{i}.jpg"), os.path.join(dest_dir, "cats"))
        shutil.copy2(os.path.join(source_dir, f"dog.{i}.jpg"), os.path.join(dest_dir, "dogs"))


if PER_CLASS_TRAIN is None:
    nb_images, val_portion, test_portion = 12500, 0.15, 0.15
    n_train = int(nb_images * (1 - val_portion - test_portion))
    n_val = int(nb_images * (1 - test_portion)) - n_train
    n_test = nb_images - n_train - n_val
else:
    n_train, n_val, n_test = PER_CLASS_TRAIN, PER_CLASS_VAL, PER_CLASS_TEST

need_split = not all((train_dir / c).is_dir() for c in ("cats", "dogs")) or \\
    len(list((train_dir / "cats").glob("*.jpg"))) != n_train

if need_split:
    for d in (train_dir, val_dir, test_dir):
        create_directory(d)
    copy_images(0, n_train, RAW_TRAIN, train_dir)
    copy_images(n_train, n_train + n_val, RAW_TRAIN, val_dir)
    copy_images(n_train + n_val, n_train + n_val + n_test, RAW_TRAIN, test_dir)
print(f"На клас: train={n_train}, val={n_val}, test={n_test}")'''),
        md("**Пункт 21, результат №5.** Структура каталогів із кількістю файлів."),
        code('''tree_lines = [str(BASE_DIR)]
for si, split in enumerate(("train", "val", "test")):
    s_last = si == 2
    tree_lines.append(f"{'└──' if s_last else '├──'} {split}/")
    for ci, cls in enumerate(("cats", "dogs")):
        c_last = ci == 1
        n = len(list((BASE_DIR / split / cls).glob("*.jpg")))
        tree_lines.append(f"{'    ' if s_last else '│   '}{'└──' if c_last else '├──'} {cls}/  {n} файлів")
tree = "\\n".join(tree_lines)
print(tree)
(RESULTS / "dir_tree.txt").write_text(tree, encoding="utf-8")'''),
        md("Приклади зображень із навчального набору."),
        code('''import matplotlib.pyplot as plt
from tensorflow.keras.utils import load_img

fig, axes = plt.subplots(2, 6, figsize=(15, 5))
for row, cls in enumerate(("cats", "dogs")):
    names = sorted(os.listdir(train_dir / cls))[:6]
    for ax, n in zip(axes[row], names):
        ax.imshow(load_img(train_dir / cls / n))
        ax.set_title(n, fontsize=8)
        ax.axis("off")
plt.tight_layout()
plt.savefig(RESULTS / "task4_dataset_sample.png", dpi=90, bbox_inches="tight")
plt.show()'''),
        md("""**Пункт 22.** Генератори `ImageDataGenerator(rescale=1/255)`, усі зображення → 150×150.
Для тестового генератора `shuffle=False`, щоб порядок передбачень збігався з мітками."""),
        code('''import tensorflow as tf
from tensorflow.keras.preprocessing.image import ImageDataGenerator

img_width, img_height = 150, 150
input_shape = (img_width, img_height, 3)
batch_size = 32
epochs = 15

datagen = ImageDataGenerator(rescale=1. / 255)
train_generator = datagen.flow_from_directory(str(train_dir), target_size=(img_width, img_height),
                                              batch_size=batch_size, class_mode="binary")
val_generator = datagen.flow_from_directory(str(val_dir), target_size=(img_width, img_height),
                                            batch_size=batch_size, class_mode="binary")
test_generator = datagen.flow_from_directory(str(test_dir), target_size=(img_width, img_height),
                                             batch_size=batch_size, class_mode="binary", shuffle=False)
print("Класи:", train_generator.class_indices)
nb_train, nb_val, nb_test = train_generator.samples, val_generator.samples, test_generator.samples'''),
        md("""**Пункт 23.** Архітектура з лекції:
3 × (Conv2D + MaxPooling) → Flatten → Dense(64, relu) → Dropout(0.5) → Dense(1, sigmoid).
Функцію винесено окремо, щоб створити дві однакові моделі для порівняння оптимізаторів."""),
        code('''from tensorflow.keras.layers import Activation, Conv2D, Dense, Dropout, Flatten, MaxPooling2D
from tensorflow.keras.models import Sequential


def build_cnn():
    model = Sequential()
    model.add(Conv2D(32, (3, 3), input_shape=input_shape))
    model.add(Activation("relu"))
    model.add(MaxPooling2D(pool_size=(2, 2)))
    model.add(Conv2D(32, (3, 3)))
    model.add(Activation("relu"))
    model.add(MaxPooling2D(pool_size=(2, 2)))
    model.add(Conv2D(64, (3, 3)))
    model.add(Activation("relu"))
    model.add(MaxPooling2D(pool_size=(2, 2)))
    model.add(Flatten())
    model.add(Dense(64))
    model.add(Activation("relu"))
    model.add(Dropout(0.5))
    model.add(Dense(1))
    model.add(Activation("sigmoid"))
    return model


cnn = build_cnn()
cnn.summary()
''' + summary_capture("cnn", "task4_model_summary.txt")),
        md("""**Пункт 24.** Запобігання перенавчанню: `EarlyStopping` зупиняє навчання, якщо `val_loss`
не покращується 3 епохи поспіль, і повертає найкращі ваги; `ModelCheckpoint` зберігає найкращу модель."""),
        code('''from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint


def make_callbacks(name):
    return [EarlyStopping(monitor="val_loss", patience=3, restore_best_weights=True),
            ModelCheckpoint(str(MODELS / f"{name}.keras"), monitor="val_loss", save_best_only=True)]


def plot_history(h, title, out_png):
    plt.figure(figsize=(12, 4))
    for i, (m, name) in enumerate([("accuracy", "Точність"), ("loss", "Втрати")]):
        plt.subplot(1, 2, i + 1)
        plt.plot(range(1, len(h.history[m]) + 1), h.history[m], "o-", label="Навчання")
        plt.plot(range(1, len(h.history[m]) + 1), h.history["val_" + m], "s-", label="Валідація")
        plt.title(f"{name} — {title}")
        plt.xlabel("Епоха")
        plt.legend()
        plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(RESULTS / out_png, dpi=110, bbox_inches="tight")
    plt.show()'''),
        md("**Навчання A: оптимізатор Adam** (як у лекції)."),
        code('''model_adam = build_cnn()
model_adam.compile(loss="binary_crossentropy", optimizer="adam", metrics=["accuracy"])

t0 = time.time()
history_adam = model_adam.fit(train_generator,
                              steps_per_epoch=nb_train // batch_size,
                              epochs=epochs,
                              validation_data=val_generator,
                              validation_steps=nb_val // batch_size,
                              callbacks=make_callbacks("cats_dogs_adam"),
                              verbose=2)
time_adam = time.time() - t0
print(f"Час навчання (Adam): {time_adam / 60:.1f} хв")
plot_history(history_adam, "Adam", "task4_history_adam.png")'''),
        md("**Навчання B: `RMSprop(learning_rate=0.001)`** (пункт 24 — чи покращиться якість)."),
        code('''from tensorflow.keras.optimizers import RMSprop

model_rms = build_cnn()
model_rms.compile(loss="binary_crossentropy", optimizer=RMSprop(learning_rate=0.001),
                  metrics=["accuracy"])

t0 = time.time()
history_rms = model_rms.fit(train_generator,
                            steps_per_epoch=nb_train // batch_size,
                            epochs=epochs,
                            validation_data=val_generator,
                            validation_steps=nb_val // batch_size,
                            callbacks=make_callbacks("cats_dogs_rmsprop"),
                            verbose=2)
time_rms = time.time() - t0
print(f"Час навчання (RMSprop): {time_rms / 60:.1f} хв")
plot_history(history_rms, "RMSprop lr=0.001", "task4_history_rmsprop.png")'''),
        md("""**Пункт 24.** Оцінка на тестовому наборі — ці зображення модель не бачила ні під час
навчання, ні під час вибору ваг. Кращу модель зберігаємо і використовуємо далі."""),
        code('''test_generator.reset()
loss_adam, acc_adam = model_adam.evaluate(test_generator, verbose=0)
test_generator.reset()
loss_rms, acc_rms = model_rms.evaluate(test_generator, verbose=0)
print(f"Test accuracy  Adam: {acc_adam * 100:.2f}%   RMSprop(0.001): {acc_rms * 100:.2f}%")
print(f"Test loss      Adam: {loss_adam:.4f}   RMSprop(0.001): {loss_rms:.4f}")

best_name = "Adam" if acc_adam >= acc_rms else "RMSprop(0.001)"
model = model_adam if acc_adam >= acc_rms else model_rms
model.save(MODELS / "cats_dogs_best.keras")
print("Далі використовуємо:", best_name)'''),
        md("Матриця помилок і звіт по класах на тестовому наборі."),
        code('''import numpy as np
from sklearn.metrics import ConfusionMatrixDisplay, classification_report, confusion_matrix

test_generator.reset()
y_prob = model.predict(test_generator, verbose=0).ravel()
y_pred = (y_prob > 0.5).astype(int)
y_true = test_generator.classes

cm = confusion_matrix(y_true, y_pred)
report = classification_report(y_true, y_pred, target_names=["cats", "dogs"])
print(cm)
print(report)
(RESULTS / "raw" / "task4_classification_report.txt").write_text(
    f"Найкраща модель: {best_name}\\n\\n{cm}\\n\\n{report}", encoding="utf-8")

ConfusionMatrixDisplay(cm, display_labels=["cats", "dogs"]).plot(cmap="Blues", colorbar=False)
plt.title(f"Матриця помилок на тесті — {best_name}")
plt.savefig(RESULTS / "task4_confusion_matrix.png", dpi=110, bbox_inches="tight")
plt.show()'''),
        md("""**Пункт 23 (друга частина).** Розпізнавання власних зображень: по 10 котів і собак.
Правильна відповідь береться з префікса імені файлу (`cat_*`, `dog_*`). Клас 1 = *dogs*."""),
        code('''from tensorflow.keras.utils import img_to_array, load_img


def own_image_paths(folder_name):
    """Локально — з my_images/<folder>, у Colab — через files.upload()."""
    if IN_COLAB:
        from google.colab import files
        target = Path("/content/my_images") / folder_name
        target.mkdir(parents=True, exist_ok=True)
        print("Оберіть власні зображення:")
        for fn, data in files.upload().items():
            (target / fn).write_bytes(data)
    else:
        target = MY_IMAGES / folder_name
    return sorted(p for p in target.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})


def predict_images(model, paths, title, out_png):
    cols = 5
    rows = (len(paths) + cols - 1) // cols
    plt.figure(figsize=(cols * 3.2, rows * 3.6))
    records = []
    for i, p in enumerate(paths):
        img = load_img(p, target_size=(img_width, img_height))
        x = np.expand_dims(img_to_array(img) / 255.0, axis=0)
        prob = float(model.predict(x, verbose=0)[0][0])
        label = "dog" if prob > 0.5 else "cat"
        # для обрізаних файлів клас береться з імені оригіналу (crop_cat_... -> cat)
        exp = "cat" if p.stem.replace("crop_", "").startswith("cat") else "dog"
        ok = label == exp
        records.append({"file": p.name, "prob_dog": round(prob, 4), "predicted": label,
                        "expected": exp, "correct": ok})
        ax = plt.subplot(rows, cols, i + 1)
        ax.axis("off")
        ax.imshow(load_img(p))
        ax.set_title(f"{p.stem[:20]}\\n{label}  p={prob:.3f}  {'+' if ok else '-'}", fontsize=8)
    plt.suptitle(title)
    plt.tight_layout()
    plt.savefig(RESULTS / out_png, dpi=110, bbox_inches="tight")
    plt.show()
    for r in records:
        print(r)
    print(f"\\nПравильно: {sum(r['correct'] for r in records)} з {len(records)}")
    return records


paths_my = own_image_paths("task4_cats_dogs")
records_my = predict_images(model, paths_my, f"Власні зображення — {best_name}",
                            "task4_predictions_my.png")'''),
        md("""**Пункт 25.** Складні зображення: тварина мала відносно кадру, фон строкатий
(дерево, трава, каміння, сніг, людина поруч). Шукаємо ті, які модель розпізнає **неправильно**."""),
        code('''paths_hard = own_image_paths("task4_hard")
records_hard = predict_images(model, paths_hard, f"Складні зображення (до обрізання) — {best_name}",
                              "task4_predictions_hard.png")
wrong = [r for r in records_hard if not r["correct"]]
print("\\nРозпізнано неправильно:", len(wrong), "з", len(records_hard))
for r in wrong:
    print("  ", r["file"], r["expected"], "->", r["predicted"], f"p_dog={r['prob_dog']}")'''),
        md("""**Пункт 26.** Обрізання неправильно розпізнаних зображень так, щоб тварина була в центрі
без зайвого фону, і повторне розпізнавання. Рамки підібрані вручну за переглядом зображень
(`scripts/crop_boxes.json`); якщо рамки немає — береться центральний кроп 55 % кадру."""),
        code('''from PIL import Image

CROPPED_DIR = MY_IMAGES / "task4_cropped"
CROPPED_DIR.mkdir(parents=True, exist_ok=True)

boxes_file = LAB_ROOT / "scripts" / "crop_boxes.json"
CROP_BOXES = json.loads(boxes_file.read_text(encoding="utf-8")) if boxes_file.exists() else {}


def crop_box_for(path):
    """Рамка (left, top, right, bottom) у пікселях оригіналу."""
    if path.name in CROP_BOXES:
        return tuple(CROP_BOXES[path.name])
    w, h = Image.open(path).size          # запасний варіант: центральні 55 %
    cw, ch = int(w * 0.55), int(h * 0.55)
    return ((w - cw) // 2, (h - ch) // 2, (w + cw) // 2, (h + ch) // 2)


cropped_paths = []
for r in wrong:
    src = next(p for p in paths_hard if p.name == r["file"])
    box = crop_box_for(src)
    dst = CROPPED_DIR / ("crop_" + src.name)
    Image.open(src).convert("RGB").crop(box).save(dst)
    cropped_paths.append(dst)
    print(f"{src.name}: {Image.open(src).size} -> рамка {box}")

if cropped_paths:
    records_crop = predict_images(model, cropped_paths, f"Після обрізання — {best_name}",
                                  "task4_predictions_cropped.png")
else:
    records_crop = []
    print("Неправильно розпізнаних складних зображень немає — обрізати нічого.")'''),
        md("Збереження всіх чисел завдання 4 для звіту."),
        code('''metrics = {
    "task": "task4_dogs_vs_cats",
    "subset": {"train_per_class": n_train, "val_per_class": n_val, "test_per_class": n_test,
               "full_dataset": PER_CLASS_TRAIN is None},
    "input_size": [img_width, img_height],
    "batch_size": batch_size,
    "epochs_planned": epochs,
    "samples": {"train": int(nb_train), "val": int(nb_val), "test": int(nb_test)},
    "class_indices": train_generator.class_indices,
    "total_params": total_params,
    "adam": {
        "epochs_done": len(history_adam.history["accuracy"]),
        "train_time_sec": round(time_adam, 1),
        "history": {k: [round(float(v), 4) for v in vals] for k, vals in history_adam.history.items()},
        "test_accuracy": round(float(acc_adam), 4), "test_loss": round(float(loss_adam), 4),
    },
    "rmsprop": {
        "epochs_done": len(history_rms.history["accuracy"]),
        "train_time_sec": round(time_rms, 1),
        "history": {k: [round(float(v), 4) for v in vals] for k, vals in history_rms.history.items()},
        "test_accuracy": round(float(acc_rms), 4), "test_loss": round(float(loss_rms), 4),
    },
    "best_model": best_name,
    "confusion_matrix": cm.tolist(),
    "own_images": records_my,
    "hard_images": records_hard,
    "cropped_images": records_crop,
}
(RESULTS / "raw" / "task4.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2),
                                            encoding="utf-8")
print("Збережено results/raw/task4.json")'''),
    ]
    return nb


def main():
    NB_DIR.mkdir(parents=True, exist_ok=True)
    notebooks = {
        "Task0_base_no_validation.ipynb": task0(),
        "Task1_validation_300.ipynb": task_1_2(
            300, "task1",
            """# Лабораторна 7. Завдання 1 — автоматична валідація (пункти 1–13)

Набір **Horses vs Humans**: до базового ноутбука додано другий, **валідаційний** набір даних
і другий генератор, а в `model.fit` — параметри `validation_data` і `validation_steps`.
Модель і параметри навчання не змінювалися: вхід 300×300, `RMSprop(learning_rate=0.001)`,
`steps_per_epoch=8`, `epochs=15`.""",
            MODEL_300,
            """**Пункти 6–7.** Модель та її опис — **без змін** порівняно з базовим ноутбуком.
У `summary()` має бути послідовність 298 → 149 → 147 → 73 → 71 → 35 → 33 → 16 → 14 → 7,
Flatten = 7·7·64 = **3136**."""),
        "Task2_resize_150.ipynb": task_1_2(
            150, "task2",
            """# Лабораторна 7. Завдання 2 — стиснення зображень до 150×150 (пункти 14–19)

Той самий ноутбук, що в завданні 1, але вхід моделі — 150×150, а четверта і п'ята пари
Conv+MaxPooling вилучені. Генератори теж віддають 150×150. Усе інше (оптимізатор, кроки,
епохи, валідація) незмінне — щоб порівняння із завданням 1 було чесним.""",
            MODEL_150,
            """**Пункти 14–15.** Модель зі зміненим входом 150×150 і без 4-ї та 5-ї пар Conv+MaxPooling.
У `summary()` перший шар має дати 148×148, останній — 17×17, а входів у Dense стане менше,
ніж у завданні 1."""),
        "Task4_dogs_vs_cats.ipynb": task4(),
    }
    for name, nb in notebooks.items():
        nb.metadata["kernelspec"] = {"display_name": "Python 3", "language": "python", "name": "python3"}
        nb.metadata["language_info"] = {"name": "python", "version": "3.12"}
        path = NB_DIR / name
        nbf.write(nb, path)
        print(f"{path.name}: {len(nb.cells)} клітинок")


if __name__ == "__main__":
    main()

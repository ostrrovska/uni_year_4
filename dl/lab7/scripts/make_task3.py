"""Завдання 3: заповнення базового ноутбука Lab_7_3_HappyOrSad_base.ipynb.

Змінюються ЛИШЕ блоки між `START CODE HERE` і `END CODE HERE`, плюс єдиний дозволений
виняток поза блоками — текст повідомлення callback українською.
Скрипт перевіряє, що решта клітинок збігається з базовою версією.
"""
import os
import shutil
from pathlib import Path

import nbformat as nbf

LAB_ROOT = Path(__file__).resolve().parent.parent
BASE_NB = Path(os.environ["USERPROFILE"]) / "Downloads" / "Lab7" / "Lab_7_3_HappyOrSad_base.ipynb"
OUT_NB = LAB_ROOT / "notebooks" / "Task3_happy_or_sad.ipynb"

EN_MSG = 'print("\\nReached 99.9% accuracy so cancelling training!")'
UA_MSG = 'print("\\nДосягнуто 99,9% точності, тому скасовуємо навчання!")'

BLOCK_LOAD = '''# Завантаження архіву data.zip: локально — з data/happy_sad.zip, у Colab — files.upload()
import os
import shutil
from pathlib import Path

try:
    import google.colab  # noqa: F401
    IN_COLAB = True
except ImportError:
    IN_COLAB = False

if not os.path.exists("./data.zip"):
    if IN_COLAB:
        from google.colab import files
        print("Оберіть файл data.zip із набором Happy or Sad:")
        files.upload()
    else:
        # notebooks/ -> dl/lab7/data/happy_sad.zip (розпакований з архіву лабораторної)
        shutil.copy2(Path.cwd().parent / "data" / "happy_sad.zip", "./data.zip")
print("data.zip на місці:", os.path.exists("./data.zip"))'''

BLOCK_UNZIP = '''import zipfile

local_zip = "./data.zip"
zip_ref = zipfile.ZipFile(local_zip, "r")
zip_ref.extractall("./")      # усередині архіву вже є папка data/ -> ./data/happy, ./data/sad
zip_ref.close()

print(sorted(os.listdir("./data")))
print("happy:", len(os.listdir("./data/happy")), "| sad:", len(os.listdir("./data/sad")))'''

BLOCK_GENERATOR = '''    # Генератор зображень з нормалізацією пікселів у діапазон [0, 1]
    train_datagen = ImageDataGenerator(rescale=1. / 255)

    # Зображення 150x150, пакет по 10, бінарні мітки (happy=0, sad=1)
    train_generator = train_datagen.flow_from_directory(directory="./data/",
                                                        target_size=(150, 150),
                                                        batch_size=10,
                                                        class_mode="binary")'''

BLOCK_MODEL = '''    # Три пари Conv2D + MaxPooling, далі повнозв'язні шари
    model = tf.keras.models.Sequential([
        tf.keras.layers.Conv2D(16, (3, 3), activation="relu", input_shape=(150, 150, 3)),
        tf.keras.layers.MaxPooling2D(2, 2),
        tf.keras.layers.Conv2D(32, (3, 3), activation="relu"),
        tf.keras.layers.MaxPooling2D(2, 2),
        tf.keras.layers.Conv2D(64, (3, 3), activation="relu"),
        tf.keras.layers.MaxPooling2D(2, 2),
        tf.keras.layers.Flatten(),
        tf.keras.layers.Dense(512, activation="relu"),
        tf.keras.layers.Dense(1, activation="sigmoid"),
    ])

    # Один вихідний нейрон із sigmoid -> binary crossentropy
    model.compile(loss=losses.BinaryCrossentropy(),
                  optimizer=optimizers.RMSprop(learning_rate=0.001),
                  metrics=["accuracy"])

    # Навчання має досягти 99.9% менш ніж за 15 епох; callback зупиняє раніше
    history = model.fit(x=train_generator,
                        epochs=15,
                        callbacks=[callbacks]
                       )

    # Збереження чисел для звіту (у межах дозволеного блоку)
    import json
    from pathlib import Path

    results_dir = (Path("/content") if IN_COLAB else Path.cwd().parent) / "results" / "raw"
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "task3.json").write_text(json.dumps({
        "task": "task3_happy_or_sad",
        "epochs_planned": 15,
        "epochs_done": len(history.history["accuracy"]),
        "target_accuracy": 0.999,
        "reached_accuracy": round(float(history.history["accuracy"][-1]), 4),
        "history": {k: [round(float(v), 4) for v in vals] for k, vals in history.history.items()},
        "total_params": int(model.count_params()),
        "samples": int(train_generator.samples),
        "class_indices": train_generator.class_indices,
    }, ensure_ascii=False, indent=2), encoding="utf-8")'''


def fill_block(source, body):
    """Замінює вміст між START CODE HERE і END CODE HERE, не чіпаючи решту клітинки."""
    lines = source.split("\n")
    start = next(i for i, ln in enumerate(lines) if "START CODE HERE" in ln)
    end = next(i for i, ln in enumerate(lines) if "END CODE HERE" in ln)
    return "\n".join(lines[:start + 1] + [body] + lines[end:])


def main():
    base = nbf.read(BASE_NB, as_version=4)
    out = nbf.read(BASE_NB, as_version=4)

    blocks = [BLOCK_LOAD, BLOCK_UNZIP, BLOCK_GENERATOR, BLOCK_MODEL]
    filled = 0
    for cell in out.cells:
        if cell.cell_type != "code":
            continue
        if "START CODE HERE" in cell.source:
            cell.source = fill_block(cell.source, blocks[filled])
            filled += 1
        elif EN_MSG in cell.source:
            cell.source = cell.source.replace(EN_MSG, UA_MSG)
    assert filled == len(blocks), f"заповнено {filled} блоків із {len(blocks)}"

    # перевірка: поза блоками змінено лише повідомлення callback
    changed = []
    for b, o in zip(base.cells, out.cells):
        if b.source != o.source and "START CODE HERE" not in b.source:
            changed.append(o.source[:60].replace("\n", " "))
    assert len(changed) == 1 and "Досягнуто" in out.cells[12].source, changed
    print("Поза блоками змінено клітинок:", len(changed), "->", changed[0])

    OUT_NB.parent.mkdir(parents=True, exist_ok=True)
    nbf.write(out, OUT_NB)
    print(f"{OUT_NB.name}: {len(out.cells)} клітинок, заповнено блоків: {filled}")

    # набір ноутбук розпаковує сам у ./data/happy і ./data/sad (блок 2)


if __name__ == "__main__":
    main()

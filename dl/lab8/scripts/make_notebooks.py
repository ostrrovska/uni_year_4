"""Генерація ноутбуків лабораторної 8 (перенесення навчання).

Чотири ноутбуки по одній попередньо навченій мережі (VGG16, InceptionV3,
ResNet50, MobileNetV2) + п'ятий, порівняльний. Усі розраховані на Google Colab
з GPU (прапорець IN_COLAB), але запускаються й локально на CPU.

Самі клітинки лежать у nb_cells.py; тут — конфігурація мереж і складання
ноутбуків із цих клітинок.
"""
from pathlib import Path

import nbformat as nbf

import nb_cells as C

LAB_ROOT = Path(__file__).resolve().parent.parent
NB_DIR = LAB_ROOT / "notebooks"


def md(text):
    return nbf.v4.new_markdown_cell(text)


def code(text):
    return nbf.v4.new_code_cell(text)


def fill(template, cfg):
    """Підстановка @@ТОКЕН@@ значеннями з конфігурації мережі."""
    out = template
    for key, value in cfg.items():
        out = out.replace(f"@@{key.upper()}@@", str(value))
    return out


# ------------------------------------------------------------------ конфігурації
# unfreeze_from — шар, з якого починається розморожування на етапі C.
# feat_dim — розмірність вектора ознак після pooling="avg" (перевірка форм).
# alt_size — додатковий розмір входу, що заміряється лише на етапі A (None — немає).
CONFIGS = [
    {
        "task": 1, "slug": "vgg16", "title": "VGG16", "module": "vgg16", "ctor": "VGG16",
        "unfreeze_from": "block5_conv1", "feat_dim": 512, "alt_size": 150,
        "notebook": "Task1_vgg16.ipynb",
        "about": "Класична VGG16: 13 згорткових шарів у 5 блоках, 14.7 млн параметрів у "
                 "згортковій частині. Саме її розглянуто в лекції, тому вона тут базова.",
        "preprocess_note": "`vgg16.preprocess_input` переводить RGB → BGR і віднімає середнє "
                           "ImageNet по каналах (без ділення на 255).",
        "unfreeze_note": "`block5_conv1` — початок останнього згорткового блоку: "
                         "розморожуються три згортки блоку 5, перші чотири блоки "
                         "лишаються замороженими.",
        "alt_note": "Додатково етап A заміряється на вході 150×150 — тому самому, що в "
                    "лабораторній 7, щоб порівняння з мережею «з нуля» було на рівних.",
    },
    {
        "task": 2, "slug": "inception_v3", "title": "InceptionV3", "module": "inception_v3",
        "ctor": "InceptionV3", "unfreeze_from": "mixed8", "feat_dim": 2048, "alt_size": 299,
        "notebook": "Task2_inception_v3.ipynb",
        "about": "InceptionV3 будується з inception-модулів: паралельні згортки 1×1, 3×3, 5×5 "
                 "і pooling в одному блоці, плюс факторизація великих згорток. "
                 "21.8 млн параметрів.",
        "preprocess_note": "`inception_v3.preprocess_input` масштабує пікселі у діапазон "
                           "`[-1, 1]` (`x/127.5 - 1`).",
        "unfreeze_note": "`mixed8` — передостанній inception-блок; розморожуються "
                         "`mixed8`…`mixed10`.",
        "alt_note": "Додатково етап A заміряється на вході 299×299 — «рідному» для "
                    "InceptionV3, бо саме на ньому мережу навчали на ImageNet.",
    },
    {
        "task": 3, "slug": "resnet50", "title": "ResNet50", "module": "resnet50",
        "ctor": "ResNet50", "unfreeze_from": "conv5_block1_1_conv", "feat_dim": 2048,
        "alt_size": None, "notebook": "Task3_resnet50.ipynb",
        "about": "ResNet50 — 50 шарів із залишковими (residual) з'єднаннями, які дозволяють "
                 "навчати глибокі мережі без згасання градієнта. 23.6 млн параметрів і "
                 "багато шарів BatchNormalization, через що донавчання вимагає обережності.",
        "preprocess_note": "`resnet50.preprocess_input` працює у стилі Caffe: RGB → BGR "
                           "і віднімання середнього ImageNet.",
        "unfreeze_note": "`conv5_block1_1_conv` — перша згортка п'ятої стадії; "
                         "розморожується вся стадія conv5 (три residual-блоки).",
        "alt_note": "",
    },
    {
        "task": 4, "slug": "mobilenet_v2", "title": "MobileNetV2", "module": "mobilenet_v2",
        "ctor": "MobileNetV2", "unfreeze_from": "block_14_expand", "feat_dim": 1280,
        "alt_size": None, "notebook": "Task4_mobilenet_v2.ipynb",
        "about": "MobileNetV2 — навмисне легка мережа: depthwise separable згортки та "
                 "inverted residual блоки, лише 2.3 млн параметрів. Узята як контраст до "
                 "трьох важких мереж у порівняльному аналізі (пункт 5).",
        "preprocess_note": "`mobilenet_v2.preprocess_input` масштабує пікселі у `[-1, 1]`.",
        "unfreeze_note": "`block_14_expand` — початок 14-го inverted residual блоку; "
                         "розморожуються блоки 14–16 і фінальна згортка.",
        "alt_note": "",
    },
]

# Базові числа лабораторної 7 (мережа, навчена з нуля на тому самому розподілі).
# Джерело: dl/lab7/results/raw/task4.json.
LAB7 = {
    "params": 1212513,
    "adam": {"test_accuracy": 0.8267, "epochs": 12, "train_time_sec": 810.0},
    "rmsprop": {"test_accuracy": 0.8424, "epochs": 15, "train_time_sec": 1046.4},
    "own_correct": 16, "own_total": 20,
    "hard_correct": 4, "hard_total": 10,
    "cropped_correct": 2, "cropped_total": 6,
}


# ------------------------------------------------------------------ ноутбук мережі
def model_notebook(cfg):
    """Один ноутбук: етапи A (екстракція ознак + Dropout), B (аугментація), C (донавчання)."""
    nb = nbf.v4.new_notebook()
    cells = [
        md(f"""# Лабораторна 8. Завдання {cfg['task']} — перенесення навчання з **{cfg['title']}**

Курс «Глибокі нейронні мережі». Набір Kaggle *Dogs vs Cats*, 25 000 зображень.

{cfg['about']}

**Що робить цей ноутбук** — три етапи перенесення навчання, від найдешевшого до найдорожчого:

| Етап | Що заморожено | Що вчиться | Навіщо |
|---|---|---|---|
| **A** | уся згорткова база | лише голова на кешованих ознаках | швидко, тому саме тут досліджується **Dropout** (пункт 4) |
| **B** | уся згорткова база | голова, але end-to-end з аугментацією | аугментація як другий засіб проти перенавчання |
| **C** | база до `{cfg['unfreeze_from']}` | верхні згорткові шари + голова | **донавчання**, найвища точність |

Покриті пункти завдання: **1** (підготовка даних), **2** (завантаження мережі
й перенесення навчання), **3** (навчання), **4** (оцінка якості й Dropout),
**5** (власні зображення), **6** (збереження моделі)."""),
        md("Середовище, шляхи й перевірка GPU. Якщо список GPU порожній — "
           "Runtime → Change runtime type → T4 GPU, і перезапустити клітинку."),
        code(C.BOOTSTRAP),
        md("Налаштування прогону. Єдине, що тут варто змінювати — `SUBSET` "
           "(якщо скінчилась квота GPU) і `DATA_SOURCE`."),
        code(fill(C.CONFIG, cfg)),
        md("Монтування Google Drive: звідти беруться архіви, туди складаються "
           "навчені моделі й копії результатів."),
        code(C.DRIVE_MOUNT),
        md("""**Пункт 1.** Вихідні дані: `train.zip` з Kaggle *Dogs vs Cats* — 25 000 фото
з мітками в імені файлу (`cat.0.jpg … cat.12499.jpg`, `dog.0.jpg … dog.12499.jpg`).

У Colab архів береться з Google Drive (`DATA_SOURCE = "drive"`) або з Kaggle через
`kagglehub` (`DATA_SOURCE = "kagglehub"`). Локально використовуються вже розпаковані
файли з лабораторної 7."""),
        code(C.DATA_SOURCE_CELL),
        md("""**Пункт 1.** Розділення на train / val / test тим самим скриптом, що в
лабораторній 7 (`dl/lab7/scripts/prepare_dataset.py`): `flow_from_directory` вимагає
структуру «папка = клас», тому `create_directory` створює чисту структуру, а
`copy_images` копіює файли за діапазоном індексів.

Розподіл 70/15/15 від 12 500 на клас — **8750 / 1875 / 1875**, разом 25 000 зображень.
Діапазони індексів не перетинаються, тож тестові зображення мережа не бачить ніколи."""),
        code(C.SPLIT_CELL),
        md("Структура каталогів із кількістю файлів."),
        code(C.TREE_CELL),
        md(f"""**Пункт 2.** Генератори даних.

Найважливіша відмінність від лабораторної 7: **у кожної попередньо навченої мережі
своя препроцесія входу**. {cfg['preprocess_note']} Якщо підставити звичне
`rescale=1./255`, мережа отримає розподіл, на якому її не вчили, і точність тихо
просяде на кілька відсотків — без жодної помилки в коді.

Аугментація застосовується лише до навчального набору на етапах B і C."""),
        code(fill(C.GENERATORS, cfg)),
        md("Приклади зображень після препроцесії."),
        code(C.SAMPLE_GRID),
        md(f"""## Етап A — згорткова база як екстрактор ознак

Ідея перенесення навчання: згорткова частина, навчена на ImageNet (1.4 млн
зображень, 1000 класів), уже вміє виділяти кути, текстури, частини об'єктів. Для
котів і собак ці ознаки годяться майже без змін — лишається навчити класифікатор
поверх них.

Тому базу заморожуємо, один раз проганяємо через неї весь набір і зберігаємо
вектори ознак ({cfg['feat_dim']} чисел на зображення). Після цього навчання голови
коштує секунди — і можна дозволити собі перебрати сітку значень Dropout."""),
        code(fill(C.FEATURES, cfg)),
        md("""**Пункт 4.** Дослідження Dropout.

Голова всюди однакова — `Dense(256, relu) → Dropout(p) → Dense(1, sigmoid)`, різниця
лише в `p`. Зерно випадковості фіксоване, аугментації немає, ознаки одні й ті самі,
тому вся різниця в результатах — від Dropout.

`overfit_gap` — різниця між точністю на навчанні й на валідації в останню епоху:
пряма числова міра перенавчання."""),
        code(C.DROPOUT_GRID),
        md("Графіки навчання й валідації для кожного `p` (пункт 4: слідкувати за "
           "перенавчанням за графіками точності та помилки)."),
        code(C.DROPOUT_PLOT),
        md("Те саме таблицею."),
        code(C.DROPOUT_TABLE),
        md("Точність етапу A на тестовому наборі з найкращим значенням Dropout."),
        code(C.STAGE_A_TEST),
    ]

    if cfg["alt_size"]:
        cells += [md(f"**Додатково.** {cfg['alt_note']}"), code(C.ALT_SIZE_CELL)]

    cells += [
        md("""## Етап B — заморожена база + аугментація

Тепер та сама заморожена база, але навчання йде end-to-end: кожна епоха бачить
аугментовані зображення, тому голова не може запам'ятати конкретні картинки.
Платою є швидкість — ознаки більше не кешуються й база працює щоепохи."""),
        code(C.PLOT_HISTORY),
        code(C.STAGE_B),
        md("Графіки етапу B і точність на тесті."),
        code(C.STAGE_B_PLOT),
        md(f"""## Етап C — донавчання (fine-tuning)

{cfg['unfreeze_note']}

Два правила, без яких донавчання псує мережу:

1. **Розморожувати лише верхні шари.** Нижні шари тримають універсальні ознаки
   (кути, текстури) — їх немає сенсу переучувати на двох класах.
2. **Швидкість навчання на два порядки менша** (1e-5 проти 1e-4). Великий крок
   градієнта зруйнував би готові ваги ImageNet ще до того, як голова встигне
   підлаштуватися.

Додатково `BatchNormalization` лишається замороженим: його ковзні середні взяті з
ImageNet, і при батчі 32 вони перенавчаються в шум."""),
        code(C.STAGE_C),
        md("Графіки етапу C і точність на тесті."),
        code(C.STAGE_C_PLOT),
        md("**Пункт 4.** Оцінка якості: матриця помилок і класифікаційний звіт на "
           "тестовому наборі."),
        code(C.EVALUATE),
        md(f"""**Пункт 5.** Розпізнавання власних зображень.

Беремо ті самі зображення з Wikimedia Commons, що й у лабораторній 7 — так
порівняння «до / після перенесення навчання» відбувається на однакових даних:

- `task4_cats_dogs` — 20 звичайних фото, мережа з нуля вгадала **{LAB7['own_correct']} з {LAB7['own_total']}**;
- `task4_hard` — 10 складних (тварина дрібна, у траві, напівсхована), мережа з нуля — **{LAB7['hard_correct']} з {LAB7['hard_total']}**;
- `task4_cropped` — 6 обрізаних версій складних, мережа з нуля — **{LAB7['cropped_correct']} з {LAB7['cropped_total']}**.

Зверніть увагу: до власних зображень застосовується та сама `preprocess_input`,
що й до навчального набору."""),
        code(C.PREDICT_HELPERS),
        code(C.PREDICT_RUN),
        md("Складні зображення — головний тест на користь перенесення навчання."),
        code(C.PREDICT_HARD),
        md("Обрізані версії складних зображень."),
        code(C.PREDICT_CROPPED),
        md("**Пункт 6.** Збереження навченої моделі."),
        code(C.SAVE_MODEL),
        md("Усі числа ноутбука — в один JSON для звіту."),
        code(C.EXPORT),
        md("""Зіп з результатами. Після завантаження покласти його у
`dl/lab8/results/incoming/`, а сам ноутбук зберегти через
**File → Download → Download .ipynb** у `dl/lab8/notebooks/`."""),
        code(C.ZIP_DOWNLOAD),
    ]

    nb.cells = cells
    return nb


# ------------------------------------------------------------------ порівняння
COMPARE_BOOTSTRAP = r'''import json
import zipfile
from pathlib import Path

try:
    import google.colab  # noqa: F401
    IN_COLAB = True
except ImportError:
    IN_COLAB = False

LAB_ROOT = Path("/content") if IN_COLAB else Path.cwd().parent
RESULTS = LAB_ROOT / "results"
RAW = RESULTS / "raw"
RAW.mkdir(parents=True, exist_ok=True)

TASKS = ["task1", "task2", "task3", "task4"]

# У Colab JSON-и беруться з Drive (їх туди складають ноутбуки 1-4);
# локально вони вже лежать у results/raw/ після scripts/unpack_results.py.
if IN_COLAB:
    from google.colab import drive

    drive.mount("/content/drive")
    for name in TASKS:
        src = Path(f"/content/drive/MyDrive/dl_lab8/results/lab8_{name}_results.zip")
        if src.exists():
            with zipfile.ZipFile(src) as z:
                z.extractall(RESULTS)

data = {}
for name in TASKS:
    p = RAW / f"{name}.json"
    if p.exists():
        data[name] = json.loads(p.read_text(encoding="utf-8"))
    else:
        print("НЕМАЄ", p, "— спочатку виконайте відповідний ноутбук")
print("Завантажено:", [d["base"] for d in data.values()])'''

COMPARE_LAB7 = r'''# Базові числа лабораторної 7: та сама задача, той самий розподіл 17500/3750/3750,
# але мережа навчена з нуля. Джерело — dl/lab7/results/raw/task4.json.
LAB7 = {
    "base": "Своя CNN з нуля (ЛР7)",
    "params": 1212513,
    "test_accuracy": 0.8424,          # RMSprop(0.001), найкраща з двох у ЛР7
    "test_accuracy_adam": 0.8267,
    "train_time_sec": 1046.4,
    "own": (16, 20),
    "hard": (4, 10),
    "cropped": (2, 6),
}
print(f"{LAB7['base']}: test accuracy {LAB7['test_accuracy']:.4f}, "
      f"{LAB7['params']:,} параметрів")'''

COMPARE_TABLE = r'''# Пункт 5: зведена таблиця по всіх мережах.
rows = []
for name, d in data.items():
    rows.append({
        "Мережа": d["base"],
        "Параметрів": d["params"]["total"],
        "Навчаних (C)": d["params"]["trainable_stage_c"],
        "Dropout": d["best_dropout"],
        "A: test": d["stage_a"]["test_accuracy"],
        "B: test": d["stage_b"]["test_accuracy"],
        "C: test": d["stage_c"]["test_accuracy"],
        "Час B+C, хв": round((d["stage_b"]["train_time_sec"]
                              + d["stage_c"]["train_time_sec"]) / 60, 1),
        "Модель, МБ": round(d["model"]["size_bytes"] / 1e6, 1),
    })

cols = list(rows[0].keys())
widths = {c: max(len(c), *(len(f"{r[c]:,}" if isinstance(r[c], int) else str(r[c]))
                           for r in rows)) for c in cols}
print(" | ".join(c.ljust(widths[c]) for c in cols))
print("-+-".join("-" * widths[c] for c in cols))
for r in rows:
    print(" | ".join((f"{r[c]:,}" if isinstance(r[c], int) else str(r[c])).ljust(widths[c])
                     for c in cols))

best = max(rows, key=lambda r: r["C: test"])
print(f"\nНайвища точність: {best['Мережа']} — {best['C: test']:.4f}")
print(f"ЛР7 (з нуля):     {LAB7['test_accuracy']:.4f}")
print(f"Приріст:          {best['C: test'] - LAB7['test_accuracy']:+.4f}")'''

COMPARE_BARS = r'''import matplotlib.pyplot as plt
import numpy as np

names = [d["base"] for d in data.values()]
stage_a = [d["stage_a"]["test_accuracy"] for d in data.values()]
stage_b = [d["stage_b"]["test_accuracy"] for d in data.values()]
stage_c = [d["stage_c"]["test_accuracy"] for d in data.values()]

x = np.arange(len(names))
w = 0.26
fig, ax = plt.subplots(figsize=(11, 5.5))
ax.bar(x - w, stage_a, w, label="Етап A (ознаки)")
ax.bar(x, stage_b, w, label="Етап B (аугментація)")
ax.bar(x + w, stage_c, w, label="Етап C (донавчання)")
ax.axhline(LAB7["test_accuracy"], color="crimson", linestyle="--",
           label=f"ЛР7, мережа з нуля ({LAB7['test_accuracy']:.4f})")

for xi, vals in zip(x, zip(stage_a, stage_b, stage_c)):
    for dx, v in zip((-w, 0, w), vals):
        ax.text(xi + dx, v + 0.004, f"{v:.3f}", ha="center", fontsize=7.5)

ax.set_xticks(x, names)
ax.set_ylabel("Точність на тестовому наборі")
ax.set_ylim(0.8, 1.01)
ax.set_title("Пункт 5: порівняння попередньо навчених мереж за етапами перенесення навчання")
ax.legend(loc="lower right", fontsize=9)
ax.grid(axis="y", alpha=0.3)
plt.tight_layout()
plt.savefig(RESULTS / "task5_comparison_accuracy.png", dpi=110, bbox_inches="tight")
plt.show()'''

COMPARE_SCATTER = r'''# Чи варта точність своєї ціни: параметри проти точності.
fig, ax = plt.subplots(figsize=(8.5, 6))
for d in data.values():
    px = d["params"]["total"] / 1e6
    py = d["stage_c"]["test_accuracy"]
    ax.scatter(px, py, s=120)
    ax.annotate(f"{d['base']}\n{px:.1f} млн", (px, py),
                textcoords="offset points", xytext=(8, -4), fontsize=9)
ax.scatter(LAB7["params"] / 1e6, LAB7["test_accuracy"], s=120, color="crimson", marker="X")
ax.annotate(f"ЛР7, з нуля\n{LAB7['params'] / 1e6:.1f} млн",
            (LAB7["params"] / 1e6, LAB7["test_accuracy"]),
            textcoords="offset points", xytext=(8, -4), fontsize=9, color="crimson")
ax.set_xlabel("Параметрів, млн")
ax.set_ylabel("Точність на тестовому наборі (етап C)")
ax.set_title("Ціна точності: розмір мережі проти якості")
ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(RESULTS / "task5_comparison_params_vs_acc.png", dpi=110, bbox_inches="tight")
plt.show()'''

COMPARE_OWN = r'''# Пункт 5: чи покращилось розпізнавання власних зображень?
kinds = [("own_images", "20 звичайних", LAB7["own"]),
         ("hard_images", "10 складних", LAB7["hard"]),
         ("cropped_images", "6 обрізаних", LAB7["cropped"])]

print(f"{'Мережа':<28} | " + " | ".join(f"{label:>14}" for _, label, _ in kinds))
print("-" * 80)
print(f"{LAB7['base']:<28} | " + " | ".join(
    f"{c}/{t:<13}" for _, _, (c, t) in kinds))
own_rows = []
for d in data.values():
    cells = []
    row = {"base": d["base"]}
    for key, _, _ in kinds:
        recs = d[key]
        correct = sum(r["correct"] for r in recs)
        row[key] = [correct, len(recs)]
        cells.append(f"{correct}/{len(recs):<13}")
    own_rows.append(row)
    print(f"{d['base']:<28} | " + " | ".join(cells))'''

COMPARE_EXPORT = r'''metrics = {
    "task": "task5_comparison",
    "lab7_baseline": LAB7,
    "models": [
        {
            "base": d["base"],
            "input_size": d["input_size"],
            "params_total": d["params"]["total"],
            "params_trainable_stage_c": d["params"]["trainable_stage_c"],
            "best_dropout": d["best_dropout"],
            "dropout_runs": [{k: r[k] for k in
                              ("p", "best_val_accuracy", "overfit_gap", "final_train_accuracy",
                               "final_val_accuracy")} for r in d["dropout_runs"]],
            "stage_a_test_accuracy": d["stage_a"]["test_accuracy"],
            "stage_a_alt": d["stage_a_alt"],
            "stage_b_test_accuracy": d["stage_b"]["test_accuracy"],
            "stage_c_test_accuracy": d["stage_c"]["test_accuracy"],
            "train_time_sec": d["stage_b"]["train_time_sec"] + d["stage_c"]["train_time_sec"],
            "model_size_bytes": d["model"]["size_bytes"],
            "model_sha256": d["model"]["sha256"],
            "model_file": d["model"]["file"],
        }
        for d in data.values()
    ],
    "own_images_summary": own_rows,
}
out = RAW / "task5.json"
out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
print("Збережено", out)

zip_name = "lab8_task5_results.zip"
zip_path = Path("/content") / zip_name if IN_COLAB else RESULTS / zip_name
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
    for p in sorted(RESULTS.rglob("*")):
        if p.is_file() and "task5" in p.name:
            z.write(p, p.relative_to(RESULTS))
print(zip_path)
if IN_COLAB:
    from google.colab import files

    files.download(str(zip_path))'''


def comparison_notebook():
    """П'ятий ноутбук: нічого не навчає, лише зводить результати чотирьох інших."""
    nb = nbf.v4.new_notebook()
    nb.cells = [
        md("""# Лабораторна 8. Завдання 5 — порівняльний аналіз

Цей ноутбук **нічого не навчає**. Він читає `results/raw/task1…task4.json`, які
залишили ноутбуки чотирьох мереж, і зводить їх у таблиці та графіки для звіту.

Виконувати **після** всіх чотирьох ноутбуків.

Відповідає на два питання пункту 5:

1. Яка з попередньо навчених мереж краща — і якою ціною?
2. **Чи покращилось розпізнавання після застосування перенесення навчання?**
   Порівняння з мережею, навченою з нуля в лабораторній 7, на тому самому
   розподілі даних і на тих самих власних зображеннях."""),
        md("Збір JSON-ів чотирьох мереж."),
        code(COMPARE_BOOTSTRAP),
        md("Базові числа лабораторної 7 — точка відліку."),
        code(COMPARE_LAB7),
        md("**Пункт 5.** Зведена таблиця."),
        code(COMPARE_TABLE),
        md("Точність за етапами, з лінією результату мережі «з нуля»."),
        code(COMPARE_BARS),
        md("Скільки коштує точність: параметри проти якості. Тут видно, чи виправдані "
           "важкі мережі порівняно з MobileNetV2."),
        code(COMPARE_SCATTER),
        md("**Пункт 5.** Власні зображення, яких не було в жодному з наборів."),
        code(COMPARE_OWN),
        md("Експорт зведених чисел."),
        code(COMPARE_EXPORT),
    ]
    return nb


def main():
    NB_DIR.mkdir(parents=True, exist_ok=True)
    notebooks = {cfg["notebook"]: model_notebook(cfg) for cfg in CONFIGS}
    notebooks["Task5_comparison.ipynb"] = comparison_notebook()

    for name, nb in notebooks.items():
        nb.metadata["kernelspec"] = {"display_name": "Python 3", "language": "python",
                                     "name": "python3"}
        nb.metadata["language_info"] = {"name": "python", "version": "3.12"}
        path = NB_DIR / name
        nbf.write(nb, path)
        code_cells = sum(1 for c in nb.cells if c.cell_type == "code")
        print(f"{path.name}: {len(nb.cells)} клітинок ({code_cells} з кодом)")


if __name__ == "__main__":
    main()

# Лабораторна 7 — Підготовка власного набору зображень в Keras

Курс «Глибокі нейронні мережі». Чотири завдання, пункти 1–26: генератори `ImageDataGenerator`,
валідація під час навчання, вплив розміру зображення, власний набір Dogs vs Cats.

## Структура

```
dl/lab7/
  notebooks/   виконані ноутбуки з виводами (саме вони здаються)
  scripts/     підготовка даних, завантаження зображень, запуск і збір результатів
  data/        розпаковані набори даних                     (у .gitignore)
  models/      навчені моделі .keras                        (у .gitignore)
  my_images/   власні тестові зображення (з Wikimedia Commons)
  results/     summary.md, metrics.json, environment.md, графіки, джерела зображень
```

| Ноутбук | Пункти | Що робить |
|---|---|---|
| `Task0_base_no_validation.ipynb` | 1 | базовий приклад **без** валідації — точка відліку для порівняння |
| `Task1_validation_300.ipynb` | 2–13 | + валідаційний набір і другий генератор, вхід 300×300 |
| `Task2_resize_150.ipynb` | 14–19 | вхід 150×150, без 4-ї та 5-ї пар Conv+Pool |
| `Task3_happy_or_sad.ipynb` | 20 | базовий ноутбук Happy or Sad, заповнені лише блоки `START/END CODE HERE` |
| `Task4_dogs_vs_cats.ipynb` | 21–26 | власний розподіл набору, навчання, тест, власні та обрізані зображення |

## Запуск локально

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install tensorflow matplotlib numpy pillow scikit-learn scipy `
    jupyter nbconvert papermill ipykernel

# розпакування наборів: Happy or Sad і Dogs vs Cats з архіву в Downloads,
# Horses vs Humans — завантажується за посиланнями з базового ноутбука
.\.venv\Scripts\python.exe scripts\extract_data.py

# за потреби — переcтворити розподіл Dogs vs Cats (повний або підмножина)
.\.venv\Scripts\python.exe scripts\prepare_dataset.py                      # 8750/1875/1875 на клас
.\.venv\Scripts\python.exe scripts\prepare_dataset.py --train-n 2000 --val-n 500 --test-n 500

# виконання ноутбуків headless (виводи зберігаються в самі ноутбуки)
.\scripts\run_notebooks.ps1
.\scripts\run_notebooks.ps1 -Notebooks Task3_happy_or_sad     # окремий ноутбук

# збір усіх чисел у results/
.\.venv\Scripts\python.exe scripts\write_environment.py
.\.venv\Scripts\python.exe scripts\collect_results.py
```

Навчання йде на CPU: TensorFlow ≥ 2.11 не підтримує GPU на Windows (деталі й заміри —
`results/environment.md`).

## Запуск у Google Colab

Ноутбуки працюють без змін: на початку визначається прапорець `IN_COLAB`, і все, що стосується
Colab (`files.upload()`, `drive.mount`), виконується лише там.

- **Завдання 1, 2** — набори завантажуються з тих самих URL, що в базовому ноутбуці;
  власні зображення вибираються через `files.upload()`.
- **Завдання 3** — попросить завантажити `data.zip` (із `HappyVsSad` в архіві лабораторної).
- **Завдання 4** — монтує Google Drive і читає `dogs-vs-cats.zip` зі шляху `ZIP_PATH`
  (змініть його на свій), бо 812 МБ через браузер вантажити недоцільно.

## Допоміжні скрипти

| Скрипт | Призначення |
|---|---|
| `extract_data.py` | розпакування наборів даних з архіву + завантаження Horses vs Humans |
| `prepare_dataset.py` | розділення Dogs vs Cats на train/val/test (пункт 21) |
| `make_notebooks.py`, `make_task3.py` | генерація ноутбуків (завдання 3 — патч базового, лише блоки) |
| `fetch_images.py`, `browse_candidates.py`, `images_manifest.json` | підбір власних зображень з Commons |
| `contact_sheet.py`, `grid_overlay.py` | перегляд зображень і підбір рамок обрізання (пункт 26) |
| `crop_boxes.json` | рамки обрізання складних зображень |
| `timing_probe.py` | замір швидкості CPU, щоб обрати розмір набору |
| `run_notebooks.ps1` | послідовне виконання ноутбуків |
| `write_environment.py`, `collect_results.py` | формування `results/environment.md` і `results/summary.md` |

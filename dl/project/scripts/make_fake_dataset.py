r"""Синтетичний двійник архіву Kaggle для димового прогону.

Відтворює структуру й пастки справжнього набору на крихітних зображеннях, щоб
ноутбук 01 можна було виконати локально за секунди:

  * вкладеність images/images/<Художник>/ і пласка тека resized/resized/
  * 50 класів із різною кількістю робіт (дисбаланс)
  * ім'я теки в розкладеній формі Unicode проти форми NFC в artists.csv
  * один биий файл, одна точна копія, одна візуальна копія

Архів кладеться туди, де ноутбуки локально шукають Drive:
  project/data/drive/archive (3).zip

Запуск:  PYTHONUTF8=1 ..\..\lab7\.venv\Scripts\python.exe scripts\make_fake_dataset.py
"""
import csv
import io
import shutil
import unicodedata
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DRIVE_DIR = PROJECT_ROOT / "data" / "drive"
BUILD_DIR = PROJECT_ROOT / "data" / "_fake_build"
ARCHIVE = DRIVE_DIR / "archive (3).zip"

# Перший художник навмисно з умляутом: у теці він зберігається в розкладеній
# формі (u + комбінований діакритичний знак), у CSV — у звичайній.
ARTISTS = ["Albrecht Durer"] + [f"Artist {i:02d}" for i in range(1, 50)]
ARTISTS[0] = "Albrecht Dürer"          # NFC, як у artists.csv

GENRES = ["Impressionism", "Baroque", "Cubism", "Expressionism", "Realism"]
NATIONALITIES = ["Dutch", "French", "Spanish", "Italian", "German"]


def count_for(index):
    """Спадний розподіл: від 26 робіт у найчисленнішого до 8 у найрідкіснішого."""
    return max(26 - index // 3, 8)


def make_image(rng, size=64):
    """Шум, а не градієнт: інакше середні хеші різних картин збігаються."""
    array = rng.integers(0, 256, size=(size, size, 3), dtype=np.uint8)
    return Image.fromarray(array, mode="RGB")


def main():
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    images_root = BUILD_DIR / "images" / "images"
    resized_root = BUILD_DIR / "resized" / "resized"
    images_root.mkdir(parents=True)
    resized_root.mkdir(parents=True)

    rng = np.random.default_rng(0)
    rows = []
    for index, artist in enumerate(ARTISTS):
        folder_name = artist.replace(" ", "_")
        if index == 0:
            # Пастка: тека в розкладеній формі, CSV — у складеній.
            folder_name = unicodedata.normalize("NFD", folder_name)
        folder = images_root / folder_name
        folder.mkdir()

        n = count_for(index)
        for k in range(1, n + 1):
            make_image(rng).save(folder / f"{artist.replace(' ', '_')}_{k}.jpg",
                                 "JPEG", quality=92)

        rows.append({
            "id": index,
            "name": artist,
            "years": f"{1800 + index} - {1870 + index}",
            "genre": GENRES[index % len(GENRES)],
            "nationality": NATIONALITIES[index % len(NATIONALITIES)],
            "bio": f"Short bio of {artist}.",
            "wikipedia": f"http://en.wikipedia.org/wiki/{artist.replace(' ', '_')}",
            "paintings": n,
        })

    # Пастки очищення, усі в першому класі.
    first = next(images_root.iterdir())
    files = sorted(first.glob("*.jpg"))
    (first / "corrupt_file.jpg").write_bytes(b"not an image at all")
    shutil.copy(files[0], first / "exact_copy.jpg")

    # Візуальний дублікат має сенс лише на зображенні з низькими частотами:
    # шум після зменшення дає інший середній хеш, а справжня картина — той самий.
    y, x = np.mgrid[0:64, 0:64]
    pattern = np.stack([(x * 4) % 256, (y * 4) % 256, ((x + y) * 2) % 256],
                       axis=-1).astype(np.uint8)
    smooth = Image.fromarray(pattern, mode="RGB")
    smooth.save(first / "pattern_original.jpg", "JPEG", quality=92)
    smooth.resize((48, 48), Image.BILINEAR).save(first / "visual_copy.jpg",
                                                 "JPEG", quality=70)

    # Головна пастка справжнього архіву: ТОЙ САМИЙ художник у другій теці з
    # іншим записом імені. Без об'єднання це два класи на одну людину.
    # Тут друге написання — з precomposed "ü" проти розкладеного в першій теці;
    # імена файлів навмисно збігаються з іменами в першій, щоб перевірити ще й
    # розв'язання конфлікту назв при копіюванні.
    # Обидві назви — справжній mojibake зі справжнього архіву Kaggle: байти
    # UTF-8 умляута (CC 88) один раз прочитані як однобайтова кодова сторінка
    # ("Du" + U+2560 + U+00EA + "rer"), і те саме, зроблене двічі. Нормалізацією
    # Unicode це не лікується — зіставлення мусить витягти їх за схожістю.
    for suffix, n in (("╠ê", 5), ("Γòá├¬", 4)):
        extra = images_root / f"Albrecht_Du{suffix}rer"
        extra.mkdir()
        for k in range(1, n + 1):
            make_image(rng).save(extra / f"Albrecht_Dürer_{k}.jpg", "JPEG", quality=92)

    # Ще дві пастки: тека зовсім без зображень і клас, у якому їх менше трьох —
    # такий неможливо поділити на три вибірки. Обох немає в artists.csv, тож
    # заразом перевіряється і звіт про незіставлені теки.
    (images_root / "Empty_Folder").mkdir()
    tiny = images_root / "Tiny_Artist"
    tiny.mkdir()
    for k in (1, 2):
        make_image(rng).save(tiny / f"Tiny_Artist_{k}.jpg", "JPEG", quality=92)

    # Пласка тека resized — вона не має стати текою класів.
    for k in range(5):
        make_image(rng, 32).save(resized_root / f"resized_{k}.jpg", "JPEG")

    with open(BUILD_DIR / "artists.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    DRIVE_DIR.mkdir(parents=True, exist_ok=True)
    if ARCHIVE.exists():
        ARCHIVE.unlink()
    with zipfile.ZipFile(ARCHIVE, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(BUILD_DIR.rglob("*")):
            # Порожні теки треба записувати окремим записом: інакше вони просто
            # не потраплять в архів, і пастка з порожнім класом не відтвориться.
            if path.is_file() or (path.is_dir() and not any(path.iterdir())):
                z.write(path, path.relative_to(BUILD_DIR))

    total = sum(1 for _ in images_root.rglob("*.jpg"))
    print(f"{ARCHIVE}  ({ARCHIVE.stat().st_size / 1e6:.1f} МБ)")
    print(f"класів: {len(ARTISTS)}, зображень: {total} "
          f"(з них 1 битий, 1 точна копія, 1 візуальна копія)")


if __name__ == "__main__":
    main()

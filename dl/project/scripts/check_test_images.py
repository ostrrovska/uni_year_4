r"""Контактний аркуш зовнішніх тестових зображень — для перевірки очима.

`fetch_test_images.py` бере, що віддає Wikimedia Commons, і цьому не можна
довіряти наосліп: пошук за іменем художника легко повертає фото музейної зали,
вуличний мурал чи поштову марку. Цей скрипт малює всі зібрані файли одним
аркушем, щоб хибні було видно за секунду.

Що робити з негодящим файлом: видалити його з `my_images/<Художник>/`, покласти
натомість свій (будь-яке ім'я, розширення .jpg) і перезапустити
`fetch_test_images.py` — він добере бракуюче й перепакує архів.

Запуск:  PYTHONUTF8=1 ..\..\lab7\.venv\Scripts\python.exe scripts\check_test_images.py
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt          # noqa: E402
from pathlib import Path                 # noqa: E402

from PIL import Image                    # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MY_IMAGES = PROJECT_ROOT / "my_images"
OUT = PROJECT_ROOT / "results" / "my_images_contact_sheet.png"


def main():
    paths = sorted(MY_IMAGES.rglob("*.jpg"))
    if not paths:
        print(f"у {MY_IMAGES} немає зображень — спершу scripts/fetch_test_images.py")
        return

    by_artist = {}
    for path in paths:
        by_artist.setdefault(path.parent.name, []).append(path)

    cols = max(len(v) for v in by_artist.values())
    rows = len(by_artist)
    fig, axes = plt.subplots(rows, cols, figsize=(3.0 * cols, 3.4 * rows),
                             squeeze=False)
    for row, (artist, files) in enumerate(sorted(by_artist.items())):
        for col in range(cols):
            ax = axes[row][col]
            ax.axis("off")
            if col >= len(files):
                continue
            with Image.open(files[col]) as im:
                ax.imshow(im.convert("RGB"))
            ax.set_title(f"{artist.replace('_', ' ')}\n{files[col].name}", fontsize=7)
    fig.suptitle("Зовнішні тестові зображення — перевірте, чи всі це справді "
                 "картини цих художників", fontsize=12)
    plt.tight_layout()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(OUT, dpi=80, bbox_inches="tight")

    print(f"{len(paths)} зображень у {len(by_artist)} художників")
    for artist, files in sorted(by_artist.items()):
        mark = "" if len(files) >= 2 else "   <- менше двох"
        print(f"  {artist.replace('_', ' '):<28} {len(files)}{mark}")
    print(f"\nаркуш: {OUT}")


if __name__ == "__main__":
    main()

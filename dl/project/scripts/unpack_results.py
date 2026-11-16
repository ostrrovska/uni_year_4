r"""Розбір зіпів, привезених із Colab.

Кожен ноутбук наприкінці віддає `project_nbNN_results.zip`. Покладіть їх у
`results/incoming/` і запустіть цей скрипт — він розкладе вміст у `results/`
(графіки) і `results/raw/` (JSON, CSV), не чіпаючи нічого іншого.

Запуск:  PYTHONUTF8=1 ..\..\lab7\.venv\Scripts\python.exe scripts\unpack_results.py
"""
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS = PROJECT_ROOT / "results"
INCOMING = RESULTS / "incoming"

ALLOWED = {".json", ".png", ".csv", ".md"}


def main():
    INCOMING.mkdir(parents=True, exist_ok=True)
    archives = sorted(INCOMING.glob("*.zip"))
    if not archives:
        print(f"у {INCOMING} немає зіпів")
        return

    for archive in archives:
        extracted = 0
        with zipfile.ZipFile(archive) as z:
            for member in z.infolist():
                name = member.filename
                # Архіви робимо самі, але розпаковуємо акуратно: ніяких
                # абсолютних шляхів і виходів з теки результатів.
                if member.is_dir() or name.startswith(("/", "\\")) or ".." in name:
                    continue
                if Path(name).suffix.lower() not in ALLOWED:
                    continue
                target = RESULTS / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(z.read(member))
                extracted += 1
        print(f"{archive.name}: {extracted} файлів")

    print(f"\nрозкладено в {RESULTS}")
    print("далі: scripts/collect_results.py")


if __name__ == "__main__":
    main()

"""Розпакування наборів даних для лабораторної 7 (локальний запуск).

Horses vs Humans качається з тих самих URL, що в базовому ноутбуці;
Happy or Sad і Dogs vs Cats беруться з локального архіву в Downloads.
"""
import argparse
import os
import shutil
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

ARCHIVE = Path(os.environ["USERPROFILE"]) / "Downloads" / "drive-download-20261030T075600Z-1-001.zip"
HORSE_URLS = {
    "horse-or-human.zip": "https://storage.googleapis.com/learning-datasets/horse-or-human.zip",
    "validation-horse-or-human.zip": "https://storage.googleapis.com/learning-datasets/validation-horse-or-human.zip",
}
UA = "Lab7DatasetFetcher/1.0 (university lab)"


def log(msg):
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def happy_sad(archive: Path, data: Path):
    """HappyVsSad/data.zip -> data/happy_sad.zip (для ноутбука) + data/happy_sad/{happy,sad}."""
    dst_zip = data / "happy_sad.zip"
    if not dst_zip.exists():
        with zipfile.ZipFile(archive) as z, z.open("HappyVsSad/data.zip") as src:
            with open(dst_zip, "wb") as out:
                shutil.copyfileobj(src, out)
        log(f"скопійовано {dst_zip.name} ({dst_zip.stat().st_size/1048576:.1f} МБ)")

    out_dir = data / "happy_sad"
    if (out_dir / "happy").is_dir() and (out_dir / "sad").is_dir():
        log("happy_sad вже розпаковано")
    else:
        with tempfile.TemporaryDirectory(dir=data) as tmp:
            with zipfile.ZipFile(dst_zip) as z:
                z.extractall(tmp)
            if out_dir.exists():
                shutil.rmtree(out_dir)
            shutil.move(str(Path(tmp) / "data"), str(out_dir))
    for cls in ("happy", "sad"):
        log(f"  happy_sad/{cls}: {len(list((out_dir/cls).glob('*.png')))} PNG")


def horses(data: Path):
    """Завантаження і розпакування навчального та валідаційного наборів Horses vs Humans."""
    targets = {
        "horse-or-human.zip": data / "horse-or-human",
        "validation-horse-or-human.zip": data / "validation-horse-or-human",
    }
    for name, url in HORSE_URLS.items():
        zip_path = data / name
        if not zip_path.exists():
            log(f"качаю {name} ...")
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r, open(zip_path, "wb") as out:
                shutil.copyfileobj(r, out)
            log(f"  готово: {zip_path.stat().st_size/1048576:.1f} МБ")
        out_dir = targets[name]
        if not (out_dir / "horses").is_dir():
            with zipfile.ZipFile(zip_path) as z:
                z.extractall(out_dir)
        n_h = len(list((out_dir / "horses").glob("*.png")))
        n_p = len(list((out_dir / "humans").glob("*.png")))
        log(f"  {out_dir.name}: horses={n_h}, humans={n_p}")


def dogs_cats(archive: Path, data: Path):
    """drive-download.zip -> dogs-vs-cats.zip -> train.zip -> data/dogs_vs_cats_raw/train (25000 jpg)."""
    raw = data / "dogs_vs_cats_raw" / "train"
    raw.mkdir(parents=True, exist_ok=True)
    have = len(list(raw.glob("*.jpg")))
    if have == 25000:
        log("dogs_vs_cats_raw вже має 25000 jpg")
        return
    log(f"у raw зараз {have} jpg, розпаковую")

    train_zip = data / "train.zip"
    if not train_zip.exists():
        log("витягую train.zip з вкладених архівів (один послідовний прохід, ~1-2 хв)")
        with zipfile.ZipFile(archive) as outer, outer.open("dogs-vs-cats.zip") as dz:
            with zipfile.ZipFile(dz) as inner, inner.open("train.zip") as tz:
                with open(train_zip, "wb") as out:
                    shutil.copyfileobj(tz, out, length=1 << 20)
        log(f"  train.zip: {train_zip.stat().st_size/1048576:.1f} МБ")

    with zipfile.ZipFile(train_zip) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".jpg")]
        log(f"  розпаковую {len(names)} jpg -> {raw}")
        for i, name in enumerate(names, 1):
            target = raw / Path(name).name
            if not target.exists():
                with z.open(name) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
            if i % 5000 == 0:
                log(f"    {i}/{len(names)}")
    train_zip.unlink()
    cats = len(list(raw.glob("cat.*.jpg")))
    dogs = len(list(raw.glob("dog.*.jpg")))
    log(f"  raw: cats={cats}, dogs={dogs}, усього={cats+dogs}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", type=Path, default=ARCHIVE)
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    ap.add_argument("--only", choices=["happy", "horses", "dogs"], default=None)
    a = ap.parse_args()

    data = a.root / "data"
    data.mkdir(parents=True, exist_ok=True)
    log(f"архів: {a.archive}")
    log(f"data:  {data}")
    if a.only in (None, "happy"):
        happy_sad(a.archive, data)
    if a.only in (None, "horses"):
        horses(data)
    if a.only in (None, "dogs"):
        dogs_cats(a.archive, data)
    free = shutil.disk_usage(data).free / 2**30
    log(f"вільно на диску: {free:.1f} ГБ")


if __name__ == "__main__":
    main()

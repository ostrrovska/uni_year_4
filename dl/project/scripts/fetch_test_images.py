r"""Збір зовнішніх тестових картин із Wikimedia Commons.

Це той «набір тестових зображень, яких модель раніше не бачила», якого вимагає
умова, у найсильнішій формі: не відкладена частина того самого набору, а роботи
тих самих художників з іншого джерела — інша зйомка, інший баланс кольору,
інше кадрування.

Список художників береться з `results/raw/nb01.json` (тобто з реального прогону
ноутбука 01), тож спершу треба розпакувати зіп із Colab. Можна й задати вручну:

    python scripts/fetch_test_images.py --artists "Vincent van Gogh,Edgar Degas"

Результат:
    my_images/<Тека_художника>/*.jpg   — по дві картини на художника
    my_images.zip                       — залити в MyDrive/dl_final_project/
    results/image_sources.md            — перелік джерел для Додатка А звіту
"""
import argparse
import json
import time
import unicodedata
import urllib.parse
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MY_IMAGES = PROJECT_ROOT / "my_images"
RESULTS = PROJECT_ROOT / "results"
NB01_JSON = RESULTS / "raw" / "nb01.json"

API = "https://commons.wikimedia.org/w/api.php"
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"

# Для художників XX століття Wikimedia Commons не має жодної картини: їхні
# роботи ще під авторським правом, тож пошук віддає тільки фото музейних зал і
# вуличні мурали. Для них беремо конкретні, поіменно вказані файли з англійської
# Вікіпедії — ранні роботи, що вже перейшли в суспільне надбання, або
# низькороздільні репродукції, які Вікіпедія тримає на умовах fair use.
#
# Нового питання це не створює: сам набір Kaggle уже містить сотні робіт цих
# художників на тих самих умовах, а зображення використовуються локально, для
# перевірки класифікатора в навчальній роботі, і нікуди не публікуються.
CURATED = {
    "Pablo Picasso": ["File:Les Demoiselles d'Avignon.jpg",
                      "File:Old guitarist chicago.jpg"],
    "Rene Magritte": ["File:Magritte TheSonOfMan.jpg",
                      "File:MagrittePipe.jpg"],
}
# Узагальнена назва клієнта: нічого особистого в заголовок не потрапляє.
USER_AGENT = "ArtworkClassifierCoursework/1.0 (educational use; Python urllib)"
MAX_SIDE = 1024


def api_get(params):
    url = f"{API}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


# Пошук за «<художник> painting» віддає будь-який файл, де згадано ім'я: вуличні
# мурали з обличчям Пікассо, фото музейних вітрин, поштові марки. Для набору,
# на якому перевіряється класифікатор, це отрута — тому назви з такими словами
# відсіюються, а шукаємо передусім у категорії «Paintings by <художник>».
BAD_WORDS = (
    "stamp", "mural", "graffiti", "street art", "museum", "exhibition",
    "gallery", "plaque", "statue", "monument", "sculpture", "building",
    "poster", "book", "cover", "grave", "tomb", "house", "bust", "medal",
    "banknote", "coin", "replica", "reproduction", "signature", "photograph",
    "portrait of the artist by", "memorial", "sign", "facade",
)


def _collect(data, limit=None):
    found = []
    for page in data.get("query", {}).get("pages", []):
        info = (page.get("imageinfo") or [{}])[0]
        url = info.get("thumburl") or info.get("url")
        title = page.get("title", "")
        if not url or not url.lower().split("?")[0].endswith((".jpg", ".jpeg")):
            continue
        if any(word in title.lower() for word in BAD_WORDS):
            continue
        meta = info.get("extmetadata", {})
        found.append({
            "title": title,
            "url": url,
            "page": info.get("descriptionurl", ""),
            "licence": meta.get("LicenseShortName", {}).get("value", "?"),
            "credit": meta.get("Artist", {}).get("value", "?"),
        })
    return found[:limit] if limit else found


def search_paintings(artist, limit):
    """Спершу категорія «Paintings by <художник>», і лише потім вільний пошук."""
    common = {"action": "query", "format": "json", "formatversion": "2",
              "prop": "imageinfo", "iiprop": "url|extmetadata",
              "iiurlwidth": str(MAX_SIDE)}

    for category in (f"Category:Paintings by {artist}",
                     f"Category:Paintings by {artist} by year"):
        try:
            found = _collect(api_get({
                **common, "generator": "categorymembers", "gcmtitle": category,
                "gcmtype": "file", "gcmlimit": str(limit * 6)}))
        except Exception:
            found = []
        if len(found) >= limit:
            return found

    return _collect(api_get({
        **common, "generator": "search", "gsrsearch": f'{artist} painting',
        "gsrnamespace": "6", "gsrlimit": str(limit * 8)}))


def curated_paintings(artist, limit):
    """Поіменно вказані файли з англійської Вікіпедії."""
    found = []
    for file_title in CURATED.get(artist, [])[:limit]:
        url = f"{WIKIPEDIA_API}?" + urllib.parse.urlencode({
            "action": "query", "format": "json", "formatversion": "2",
            "titles": file_title, "prop": "imageinfo",
            "iiprop": "url|extmetadata", "iiurlwidth": str(MAX_SIDE)})
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
        page = (data.get("query", {}).get("pages") or [{}])[0]
        info = (page.get("imageinfo") or [{}])[0]
        source = info.get("thumburl") or info.get("url")
        if not source:
            continue
        meta = info.get("extmetadata", {})
        found.append({
            "title": file_title,
            "url": source,
            "page": info.get("descriptionurl", ""),
            "licence": meta.get("LicenseShortName", {}).get("value", "?"),
            "credit": meta.get("Artist", {}).get("value", "?"),
        })
        time.sleep(1.0)          # Вікіпедія віддає 429 на швидкі серії запитів
    return found


def download(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def save_image(raw, path):
    with Image.open(BytesIO(raw)) as im:
        im = im.convert("RGB")
        scale = MAX_SIDE / max(im.size)
        if scale < 1:
            im = im.resize((round(im.width * scale), round(im.height * scale)),
                           Image.LANCZOS)
        im.save(path, "JPEG", quality=90)


def artists_from_nb01():
    if not NB01_JSON.exists():
        raise SystemExit(
            f"немає {NB01_JSON}\n"
            "спершу розпакуйте зіп ноутбука 01 (scripts/unpack_results.py) "
            "або передайте список через --artists")
    payload = json.loads(NB01_JSON.read_text(encoding="utf-8"))
    display = {row.get("class_dir", row.get("class")): row["artist"]
               for row in payload["class_counts"]}
    # Теки в nb01.json записані у формі NFC — саме так вони лежать у наборі.
    return [(folder, display.get(folder, folder.replace("_", " ")))
            for folder in payload["top15"]]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--artists", help="список через кому замість nb01.json")
    parser.add_argument("--per-artist", type=int, default=2)
    args = parser.parse_args()

    if args.artists:
        names = [n.strip() for n in args.artists.split(",") if n.strip()]
        targets = [(unicodedata.normalize("NFC", n.replace(" ", "_")), n) for n in names]
    else:
        targets = artists_from_nb01()

    sources, failures = [], []
    for folder_name, display_name in targets:
        folder = MY_IMAGES / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        existing = len(list(folder.glob("*.jpg")))
        if existing >= args.per_artist:
            print(f"{display_name}: вже є {existing} — пропускаю")
            continue

        try:
            # Поіменний список має перевагу: для художників, чиї роботи ще під
            # авторським правом, пошук по Commons дає лише сторонні фото.
            candidates = (curated_paintings(display_name, args.per_artist)
                          or search_paintings(display_name, args.per_artist))
        except Exception as exc:
            failures.append((display_name, f"пошук: {exc}"))
            continue

        saved = 0
        for candidate in candidates:
            if saved >= args.per_artist - existing:
                break
            path = folder / f"{folder_name}_ext_{existing + saved + 1}.jpg"
            try:
                save_image(download(candidate["url"]), path)
            except Exception as exc:
                failures.append((candidate["title"], str(exc)))
                continue
            sources.append({"artist": display_name, "file": str(
                path.relative_to(PROJECT_ROOT)), **candidate})
            saved += 1
            time.sleep(0.4)          # не гамселити API
        print(f"{display_name}: завантажено {saved}")
        if not saved:
            failures.append((display_name, "нічого не завантажено"))

    RESULTS.mkdir(parents=True, exist_ok=True)
    lines = ["# Джерела зовнішніх тестових зображень", "",
             "Усі файли — з Wikimedia Commons, завантажені "
             "`scripts/fetch_test_images.py`. Жодного з них немає в наборі "
             "Kaggle: він зібраний з artchallenge.ru.", "",
             "| Художник | Файл | Сторінка на Commons | Ліцензія |", "|---|---|---|---|"]
    for s in sources:
        lines.append(f"| {s['artist']} | `{s['file']}` | {s['page']} | {s['licence']} |")
    if failures:
        lines += ["", "## Не завантажено", ""]
        lines += [f"- {name}: {reason}" for name, reason in failures]
    (RESULTS / "image_sources.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    archive = PROJECT_ROOT / "my_images.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(MY_IMAGES.rglob("*.jpg")):
            z.write(path, path.relative_to(MY_IMAGES))
    total = sum(1 for _ in MY_IMAGES.rglob("*.jpg"))

    print(f"\nзображень у my_images/: {total}")
    print(f"архів: {archive} — залийте його в MyDrive/dl_final_project/")
    print(f"джерела: {RESULTS / 'image_sources.md'}")
    if failures:
        print(f"не вдалося: {len(failures)} — перегляньте image_sources.md")


if __name__ == "__main__":
    main()

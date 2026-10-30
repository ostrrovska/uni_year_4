"""Завантаження власних тестових зображень з Wikimedia Commons (вільні ліцензії).

Для кожного пункту маніфесту робиться ОДИН запит до API (generator=search або
generator=categorymembers разом з prop=imageinfo), кандидати кешуються, вибраний
файл завантажується, джерело (URL + автор + ліцензія) пишеться у results/image_sources.md.

Маніфест: {"out": шлях, "search"|"category"|"title": ..., "pick": індекс кандидата, "note": опис}
"""
import argparse
import json
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parent.parent
API = "https://commons.wikimedia.org/w/api.php"
UA = "Lab7ImageFetcher/1.0 (university DL lab; https://github.com/ostrrovska)"
OK_MIME = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".jpg"}
THROTTLE = 1.5          # пауза між запитами до API, с
CACHE = LAB_ROOT / "results" / "raw" / "candidates_cache.json"
_last_call = [0.0]


def api(params):
    """Запит до API з тротлінгом і backoff на 429/5xx."""
    params = dict(params, format="json", formatversion=2)
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    for attempt in range(5):
        wait = THROTTLE - (time.time() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                _last_call[0] = time.time()
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            _last_call[0] = time.time()
            if e.code in (429, 500, 502, 503) and attempt < 4:
                pause = (attempt + 1) * 15
                print("    HTTP " + str(e.code) + ", пауза " + str(pause) + " с", flush=True)
                time.sleep(pause)
                continue
            raise
        except Exception as e:
            _last_call[0] = time.time()
            if attempt < 4:
                print("    повтор (" + str(e) + ")", flush=True)
                time.sleep(5)
                continue
            raise


def strip_html(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()


def candidates(entry, cache, force_query=False):
    """Список кандидатів одним запитом; результат кешується за ключем запиту."""
    key = entry.get("title") or entry.get("category") or entry.get("search")
    if not force_query and key in cache:
        return cache[key]

    common = {"prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 800}
    if entry.get("title"):
        params = dict({"action": "query", "titles": entry["title"]}, **common)
    elif entry.get("category"):
        params = dict({"action": "query", "generator": "categorymembers",
                       "gcmtitle": entry["category"], "gcmtype": "file", "gcmlimit": 30}, **common)
    else:
        params = dict({"action": "query", "generator": "search",
                       "gsrsearch": entry["search"] + " filetype:bitmap",
                       "gsrnamespace": 6, "gsrlimit": 20}, **common)
    data = api(params)
    out = []
    for page in data.get("query", {}).get("pages", []):
        ii = (page.get("imageinfo") or [None])[0]
        if not ii or ii.get("mime") not in OK_MIME:
            continue
        w, h = ii.get("width", 0), max(ii.get("height", 1), 1)
        if w < 400 or not (0.4 <= w / h <= 2.6):
            continue
        meta = ii.get("extmetadata", {})
        out.append({
            "title": page["title"], "mime": ii["mime"],
            "width": ii.get("thumbwidth") or w, "height": ii.get("thumbheight") or h,
            "thumburl": ii.get("thumburl") or ii["url"], "url": ii["url"],
            "descriptionurl": ii.get("descriptionurl", ""),
            "author": strip_html(meta.get("Artist", {}).get("value", "")),
            "license": strip_html(meta.get("LicenseShortName", {}).get("value", "")),
        })
    cache[key] = out
    return out


def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as out:
        shutil.copyfileobj(r, out)
    return dest.stat().st_size


def write_sources(sources, sources_json):
    sources_json.write_text(json.dumps(sources, ensure_ascii=False, indent=2), encoding="utf-8")
    md = ["# Джерела власних тестових зображень", "",
          "Усі зображення — з Wikimedia Commons (вільні ліцензії). "
          "Фото реальних відомих людей не використовуються.", ""]
    for folder in sorted({v["folder"] for v in sources.values()}):
        md += ["## " + folder, "",
               "| Файл | Що на зображенні | Ліцензія | Автор | Сторінка файлу |",
               "|---|---|---|---|---|"]
        for name in sorted(sources):
            v = sources[name]
            if v["folder"] == folder:
                md.append("| `" + name + "` | " + v["note"] + " | " + v["license"] + " | "
                          + v["author"][:60] + " | " + v["description_url"] + " |")
        md.append("")
    (LAB_ROOT / "results" / "image_sources.md").write_text("\n".join(md), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path, default=LAB_ROOT / "scripts" / "images_manifest.json")
    ap.add_argument("--only", default=None, help="фільтр за префіксом out")
    ap.add_argument("--force", action="store_true", help="перезавантажити наявні файли")
    ap.add_argument("--requery", action="store_true", help="не брати кандидатів з кешу")
    ap.add_argument("--list", action="store_true", help="лише показати кандидатів")
    a = ap.parse_args()

    manifest = json.loads(a.manifest.read_text(encoding="utf-8"))
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    sources_json = LAB_ROOT / "results" / "raw" / "image_sources.json"
    sources = json.loads(sources_json.read_text(encoding="utf-8")) if sources_json.exists() else {}
    used = {v.get("commons_title") for v in sources.values()}

    try:
        for entry in manifest:
            out_rel = entry["out"]
            if a.only and not out_rel.startswith(a.only):
                continue
            base = LAB_ROOT / "my_images" / out_rel
            base.parent.mkdir(parents=True, exist_ok=True)
            existing = list(base.parent.glob(base.stem + ".*"))
            if existing and not (a.force or a.list):
                print("= " + out_rel + ": вже є (" + existing[0].name + ")")
                continue

            cands = candidates(entry, cache, force_query=a.requery)
            query = entry.get("search") or entry.get("category") or entry.get("title")
            if a.list:
                print("\n--- " + out_rel + "  (" + query + ")")
                for i, c in enumerate(cands[:12]):
                    print("  [{}] {}  {}x{}  {}".format(i, c["title"][:95], c["width"],
                                                        c["height"], c["license"]))
                continue
            if not cands:
                print("! " + out_rel + ": кандидатів не знайдено (" + query + ")")
                continue

            pool = [c for c in cands if c["title"] not in used] or cands
            cand = pool[min(entry.get("pick", 0), len(pool) - 1)]
            dest = base.with_suffix(OK_MIME[cand["mime"]])
            for p in existing:
                if p != dest:
                    p.unlink()
            try:
                size = download(cand["thumburl"], dest)
            except Exception as e:
                print("! " + out_rel + ": помилка завантаження " + str(e))
                continue
            used.add(cand["title"])
            sources[dest.name] = {
                "folder": str(Path(out_rel).parent).replace("\\", "/"),
                "note": entry.get("note", ""),
                "commons_title": cand["title"],
                "description_url": cand["descriptionurl"],
                "download_url": cand["thumburl"].split("?")[0],
                "author": cand["author"],
                "license": cand["license"],
                "width": cand["width"], "height": cand["height"],
            }
            print("+ {}  {:.0f} КБ  [{}]  {}".format(dest.name, size / 1024,
                                                     cand["license"], cand["title"][:70]))
    finally:
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
        if not a.list:
            write_sources(sources, sources_json)
            print("\nДжерел записано: " + str(len(sources)))


if __name__ == "__main__":
    main()

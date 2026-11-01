"""Перегляд і вибір кандидатів із кешу Commons.

  browse: завантажує кандидатів категорії у тимчасову папку і збирає контактний аркуш
  assign: копіює вибраний кадр у my_images/... під фінальним іменем і дописує джерело
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_images import CACHE, LAB_ROOT, candidates, download, write_sources  # noqa: E402

SOURCES_JSON = LAB_ROOT / "results" / "raw" / "image_sources.json"


def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:40]


def load_cache():
    return json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}


def get_candidates(key, cache):
    entry = {"category": key} if key.startswith("Category:") else {"search": key}
    return candidates(entry, cache)


def cmd_browse(a):
    cache = load_cache()
    cands = get_candidates(a.key, cache)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    out_dir = Path(a.scratch) / slug(a.key)
    out_dir.mkdir(parents=True, exist_ok=True)
    picked = cands[a.start:a.start + a.count]
    for i, c in enumerate(picked, start=a.start):
        dest = out_dir / f"{i:02d}.jpg"
        if not dest.exists():
            try:
                download(c["thumburl"], dest)
            except Exception as e:
                print(f"  ! {i}: {e}")
                continue
        print(f"  [{i}] {c['title'][:80]}")
    sheet = Path(a.scratch) / f"sheet_{slug(a.key)}.png"
    import subprocess
    subprocess.run([sys.executable, str(Path(__file__).parent / "contact_sheet.py"),
                    str(out_dir), str(sheet), "5"], check=False)
    print(f"аркуш: {sheet}  (усього кандидатів у кеші: {len(cands)})")


def cmd_assign(a):
    cache = load_cache()
    cands = get_candidates(a.key, cache)
    cand = cands[a.idx]
    base = LAB_ROOT / "my_images" / a.out
    base.parent.mkdir(parents=True, exist_ok=True)
    dest = base.with_suffix(".jpg")
    src = Path(a.scratch) / slug(a.key) / f"{a.idx:02d}.jpg"
    for p in base.parent.glob(base.stem + ".*"):
        p.unlink()
    if src.exists():
        shutil.copy2(src, dest)
    else:
        download(cand["thumburl"], dest)

    sources = json.loads(SOURCES_JSON.read_text(encoding="utf-8")) if SOURCES_JSON.exists() else {}
    for name in [n for n, v in sources.items() if v["folder"] == str(Path(a.out).parent).replace("\\", "/")
                 and Path(n).stem == base.stem]:
        sources.pop(name)
    sources[dest.name] = {
        "folder": str(Path(a.out).parent).replace("\\", "/"),
        "note": a.note,
        "commons_title": cand["title"],
        "description_url": cand["descriptionurl"],
        "download_url": cand["thumburl"].split("?")[0],
        "author": cand["author"],
        "license": cand["license"],
        "width": cand["width"], "height": cand["height"],
    }
    write_sources(sources, SOURCES_JSON)
    print(f"+ {dest.relative_to(LAB_ROOT)}  <- [{a.idx}] {cand['title'][:70]}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    default_scratch = str(Path.home() / "AppData/Local/Temp/claude/lab7_cands")

    b = sub.add_parser("browse")
    b.add_argument("key")
    b.add_argument("--start", type=int, default=0)
    b.add_argument("--count", type=int, default=15)
    b.add_argument("--scratch", default=default_scratch)
    b.set_defaults(func=cmd_browse)

    s = sub.add_parser("assign")
    s.add_argument("key")
    s.add_argument("idx", type=int)
    s.add_argument("out")
    s.add_argument("note")
    s.add_argument("--scratch", default=default_scratch)
    s.set_defaults(func=cmd_assign)

    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()

"""Сітка з координатами поверх зображення — щоб вручну підібрати рамку обрізання."""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

src_dir, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
out_dir.mkdir(parents=True, exist_ok=True)
for p in sorted(src_dir.iterdir()):
    if p.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
        continue
    im = Image.open(p).convert("RGB")
    w, h = im.size
    scale = 640 / max(w, h)
    small = im.resize((int(w * scale), int(h * scale)))
    d = ImageDraw.Draw(small)
    for frac in range(1, 10):
        x = int(small.width * frac / 10)
        y = int(small.height * frac / 10)
        d.line([(x, 0), (x, small.height)], fill=(255, 0, 0), width=1)
        d.line([(0, y), (small.width, y)], fill=(255, 0, 0), width=1)
        d.text((x + 2, 2), str(int(w * frac / 10)), fill=(255, 255, 0))
        d.text((2, y + 2), str(int(h * frac / 10)), fill=(255, 255, 0))
    d.text((2, small.height - 12), f"{p.name}  {w}x{h}", fill=(0, 255, 255))
    small.save(out_dir / p.name)
    print(f"{p.name}  {w}x{h}")

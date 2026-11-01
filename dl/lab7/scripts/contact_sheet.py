"""Контактний аркуш із підписами — для швидкої візуальної перевірки папки зображень."""
import sys
from pathlib import Path
from PIL import Image, ImageDraw

folder = Path(sys.argv[1])
out = Path(sys.argv[2])
cols = int(sys.argv[3]) if len(sys.argv) > 3 else 5
cell, label_h = 240, 18

files = sorted(p for p in folder.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
rows = (len(files) + cols - 1) // cols
sheet = Image.new("RGB", (cols * cell, rows * (cell + label_h)), "white")
draw = ImageDraw.Draw(sheet)
for i, p in enumerate(files):
    x, y = (i % cols) * cell, (i // cols) * (cell + label_h)
    try:
        im = Image.open(p).convert("RGB")
    except Exception as e:
        draw.text((x + 4, y + 4), "ERR " + str(e)[:30], fill="red")
        continue
    im.thumbnail((cell - 6, cell - 6))
    sheet.paste(im, (x + (cell - im.width) // 2, y + (cell - im.height) // 2))
    draw.text((x + 3, y + cell + 3), f"{i}:{p.stem[:30]}", fill="black")
sheet.save(out)
print(f"{out}  {len(files)} файлів, {sheet.width}x{sheet.height}")

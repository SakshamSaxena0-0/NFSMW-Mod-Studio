import math
import os

from PIL import Image, ImageDraw

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'app', 'assets', 'icon.ico')
S = 512
img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle([16, 16, S - 16, S - 16], radius=110, fill=(21, 24, 32, 255))
cx, cy, r = S // 2, S // 2 + 40, 175
d.arc([cx - r, cy - r, cx + r, cy + r], start=150, end=390, fill=(70, 76, 92, 255), width=34)
d.arc([cx - r, cy - r, cx + r, cy + r], start=150, end=330, fill=(255, 122, 0, 255), width=34)
for i in range(9):
    a = math.radians(150 + i * 30)
    x1, y1 = cx + (r - 52) * math.cos(a), cy + (r - 52) * math.sin(a)
    x2, y2 = cx + (r - 80) * math.cos(a), cy + (r - 80) * math.sin(a)
    d.line([x1, y1, x2, y2], fill=(232, 234, 240, 255), width=10)
a = math.radians(310)
d.line([cx, cy, cx + (r - 40) * math.cos(a), cy + (r - 40) * math.sin(a)], fill=(255, 122, 0, 255), width=22)
d.ellipse([cx - 32, cy - 32, cx + 32, cy + 32], fill=(232, 234, 240, 255))
os.makedirs(os.path.dirname(OUT), exist_ok=True)
img.save(OUT, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
img.resize((256, 256), Image.LANCZOS).save(OUT.replace('.ico', '.png'))
print('wrote', os.path.abspath(OUT))

"""Draw packaging/icon.ico (original artwork: a simple scythe on a dark tile)."""
from pathlib import Path

from PIL import Image, ImageDraw

S = 512
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((16, 16, S - 16, S - 16), radius=96, fill=(28, 24, 34, 255),
                    outline=(120, 200, 190, 255), width=14)
# Handle
d.line((150, 430, 330, 110), fill=(205, 190, 160, 255), width=30)
# Blade: an arc-shaped crescent
blade = Image.new("L", (S, S), 0)
b = ImageDraw.Draw(blade)
b.ellipse((40, 40, 420, 330), fill=255)
b.ellipse((70, 110, 450, 400), fill=0)
blade = blade.crop((0, 0, 340, S)).resize((340, S))
mask = Image.new("L", (S, S), 0)
mask.paste(blade, (0, 0))
d2 = Image.new("RGBA", (S, S), (130, 225, 215, 255))
img.paste(d2, (0, 0), mask)
# Glow dot where blade meets handle
d.ellipse((300, 85, 360, 145), fill=(240, 120, 60, 255))
out = Path(__file__).with_name("icon.ico")
img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
img.resize((256, 256), Image.LANCZOS).save(Path(__file__).with_name("icon_preview.png"))
print("wrote", out)

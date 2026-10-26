"""Convert the supplied 云琥 ICO into Android and web artwork without redrawing it.

Use the bundled Pillow environment. The original highest-resolution frame is
preserved for web/native display; launcher sizes are resampled from that frame.
"""
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
source = Image.open(ROOT / "图标.ico")
frame = source.ico.getimage(max(source.ico.sizes(), key=lambda size: size[0] * size[1])).convert("RGBA")
res = ROOT / "android/app/src/main/res"
for target in (ROOT / "web/static/brand-icon.png", res / "drawable-nodpi/brand_icon.png"):
    target.parent.mkdir(parents=True, exist_ok=True)
    frame.save(target)
for density, pixels in (("mdpi", 48), ("hdpi", 72), ("xhdpi", 96), ("xxhdpi", 144), ("xxxhdpi", 192)):
    folder = res / ("mipmap-" + density)
    folder.mkdir(parents=True, exist_ok=True)
    frame.resize((pixels, pixels), Image.Resampling.LANCZOS).save(folder / "ic_launcher.png")

# Android status icons use an alpha-only silhouette. Derive it from the supplied
# colored cloud, omitting the small caption so it remains legible at 24 dp.
cloud = frame.crop((0, 0, frame.width, int(frame.height * .82)))
alpha = Image.new("L", cloud.size)
alpha.putdata([255 if min(red, green, blue) < 180 and red - blue > 40 else 0
               for red, green, blue, opacity in cloud.getdata()])
silhouette = Image.new("RGBA", cloud.size, (255, 255, 255, 0))
silhouette.putalpha(alpha)
notification = Image.new("RGBA", (72, 72), (0, 0, 0, 0))
notification.alpha_composite(silhouette.resize((64, 53), Image.Resampling.LANCZOS), (4, 9))
notification.save(res / "drawable-nodpi/brand_notification.png")
print("Converted original ICO frame", frame.size, "to 5 density icons, 2 display images and a status silhouette")

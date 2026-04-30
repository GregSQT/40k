from PIL import Image, ImageFilter, ImageEnhance, ImageOps
import sys
import os

BASE_PATH = "frontend/public/icons"


def process_icon(unit_name):
    input_path = os.path.join(BASE_PATH, f"{unit_name}P2.png")
    output_path = os.path.join(BASE_PATH, f"{unit_name}P3.png")

    if not os.path.exists(input_path):
        print(f"❌ Input file not found: {input_path}")
        return

    img = Image.open(input_path).convert("RGBA")
    alpha = img.getchannel("A")

    # 1. Lissage léger pour écraser les micro-détails
    rgb = img.convert("RGB")
    rgb = rgb.filter(ImageFilter.MedianFilter(size=3))
    rgb = rgb.filter(ImageFilter.SMOOTH_MORE)

    # 2. Réduction forte des nuances = look plus icon / moins illustratif
    rgb = rgb.quantize(colors=24, method=Image.Quantize.MEDIANCUT).convert("RGB")

    # 3. Remonter contraste et saturation après quantization
    rgb = ImageEnhance.Contrast(rgb).enhance(1.25)
    rgb = ImageEnhance.Color(rgb).enhance(1.12)

    # 4. Nettoyage alpha
    alpha = alpha.point(lambda a: 0 if a < 35 else 255 if a > 220 else a)

    # 5. Recomposition RGBA
    out = Image.merge("RGBA", (*rgb.split(), alpha))

    # 6. Netteté finale modérée
    out = out.filter(ImageFilter.UnsharpMask(radius=0.8, percent=120, threshold=3))

    out.save(output_path)
    print(f"✅ Saved: {output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python icon_pipeline.py Intercessor")
    else:
        process_icon(sys.argv[1])
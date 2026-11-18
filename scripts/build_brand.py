"""Наш логотип из простых фигур: легко поменять цвета и пересобрать ICO/SVG.

Рисуем с увеличением и уменьшаем с LANCZOS — границы остаются плавными даже
на маленьком значке панели задач. Никаких платных шрифтов или внешних картинок.
"""

from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
C_POINTS = [
    (181, 54),
    (85, 54),
    (54, 85),
    (54, 171),
    (85, 202),
    (181, 202),
    (181, 164),
    (103, 164),
    (92, 153),
    (92, 103),
    (103, 92),
    (181, 92),
]
PLAY = [(135, 104), (181, 128), (135, 152)]


def render(size):
    scale = size * 4 / 256
    image = Image.new("RGBA", (size * 4, size * 4), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, size * 4 - 1, size * 4 - 1), radius=56 * scale, fill="#121316")
    draw.rounded_rectangle(
        (scale, scale, size * 4 - scale, size * 4 - scale),
        radius=55 * scale,
        outline="#303139",
        width=max(1, round(scale)),
    )
    draw.polygon([(x * scale, y * scale) for x, y in C_POINTS], fill="#f7f7f9")
    draw.polygon([(x * scale, y * scale) for x, y in PLAY], fill="#f04452")
    return image.resize((size, size), Image.Resampling.LANCZOS)


def main():
    ASSETS.mkdir(exist_ok=True)
    render(1024).save(ASSETS / "logo.png")
    render(256).save(ASSETS / "app.ico", sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])
    white = " ".join(f"{x},{y}" for x, y in C_POINTS)
    red = " ".join(f"{x},{y}" for x, y in PLAY)
    (ASSETS / "logo.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">'
        f'<title>CLIP TRIBUNE</title><rect x="1" y="1" width="254" height="254" rx="56" fill="#121316" stroke="#303139"/>'
        f'<polygon points="{white}" fill="#f7f7f9"/><polygon points="{red}" fill="#f04452"/></svg>',
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

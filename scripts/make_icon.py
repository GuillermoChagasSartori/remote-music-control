"""Draw the app icon (src/remote_music_control/app/icon.ico).

Run it again after changing the design:

    uv run --with pillow python scripts/make_icon.py

The icon is drawn in code rather than in an image editor so anyone can change
it with a text editor and see exactly what it is made of. It is drawn large and
scaled down, which smooths the edges (*supersampling*); the .ico file holds
several sizes, because Windows picks a different one for the tray, the taskbar
and the Start menu.
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUTPUT = Path(__file__).resolve().parent.parent / "src" / "remote_music_control" / "app" / "icon.ico"
CANVAS = 1024
BACKGROUND = (91, 60, 196)  # deep purple: distinct from YouTube's red, so it isn't mistaken for their logo
FOREGROUND = (255, 255, 255)
ICON_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def draw() -> Image.Image:
    image = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)
    pen.rounded_rectangle((32, 32, CANVAS - 32, CANVAS - 32), radius=220, fill=BACKGROUND)

    # A play triangle, low and left of centre.
    pen.polygon([(230, 330), (230, 820), (620, 575)], fill=FOREGROUND)

    # "Signal" arcs around a dot, top right: control from a distance.
    centre_x, centre_y = 640, 390
    pen.ellipse((centre_x - 42, centre_y - 42, centre_x + 42, centre_y + 42), fill=FOREGROUND)
    for radius in (140, 250):
        box = (centre_x - radius, centre_y - radius, centre_x + radius, centre_y + radius)
        pen.arc(box, start=-90, end=0, fill=FOREGROUND, width=58)
    return image


if __name__ == "__main__":
    draw().resize((256, 256), Image.LANCZOS).save(OUTPUT, sizes=ICON_SIZES)
    print(f"wrote {OUTPUT}")

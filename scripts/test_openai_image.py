"""
Standalone test to generate a simple PNG using Pillow (no network).

Usage (Heroku):
  heroku run --app <your-app> python scripts/test_openai_image.py "Your text here"

Saves PNG under app/static/uploads and prints the path and URL (if BASE_URL set).
"""
import os
import sys
import time
from PIL import Image, ImageDraw, ImageFont  # type: ignore


def wrap_text(text: str, width: int = 18) -> str:
    words = text.split()
    lines = []
    line = ""
    for w in words:
        if len(line) + len(w) + 1 > width:
            lines.append(line)
            line = w
        else:
            line = (line + " " + w).strip()
    if line:
        lines.append(line)
    return "\n".join(lines[:6])


def main() -> int:
    text = sys.argv[1] if len(sys.argv) > 1 else "Roast Cotton"
    here = os.path.dirname(os.path.abspath(__file__))
    uploads = os.path.join(os.path.dirname(here), "app", "static", "uploads")
    os.makedirs(uploads, exist_ok=True)

    # Transparent 1024x1024 canvas
    img = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    try:
        # Try to load a nicer font if available on dyno; otherwise default
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 64)
    except Exception:
        font = ImageFont.load_default()

    content = wrap_text(text, width=18)
    # Compute text size and center
    try:
        w, h = draw.multiline_textbbox((0, 0), content, font=font, spacing=6)[2:]
    except Exception:
        w, h = draw.multiline_textsize(content, font=font, spacing=6)
    x = (1024 - w) // 2
    y = (1024 - h) // 2
    draw.multiline_text((x, y), content, fill=(0, 0, 0, 255), font=font, align="center", spacing=6)

    fname = f"pillow_test_{int(time.time())}.png"
    path = os.path.join(uploads, fname)
    img.save(path, format="PNG")

    print("OK")
    print(f"saved: {path}")
    base_url = os.getenv("BASE_URL", "").rstrip("/")
    if base_url:
        print(f"url: {base_url}/static/uploads/{fname}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



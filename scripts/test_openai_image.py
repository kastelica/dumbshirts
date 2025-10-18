"""
Standalone test to generate an image with OpenAI (for Heroku dyno testing).

Usage (Heroku):
  heroku run --app <your-app> python scripts/test_openai_image.py "Your prompt here"

Requires env var OPENAI_API_KEY. Saves PNG under app/static/uploads and prints the path.
"""
import os
import sys
import time
from base64 import b64decode


def main() -> int:
    prompt = sys.argv[1] if len(sys.argv) > 1 else "Bold wordmark: DUMBSHIRTS"
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set")
        return 2

    os.environ["OPENAI_API_KEY"] = api_key
    try:
        from openai import OpenAI  # type: ignore
    except Exception as e:
        print(f"ERROR: failed to import openai sdk: {e}")
        return 2

    try:
        client = OpenAI().with_options(timeout=30.0)
        print(f"Generating image for prompt: {prompt!r}")
        t0 = time.time()
        res = client.images.generate(model="gpt-image-1", prompt=prompt, size="1024x1024")
        b64 = res.data[0].b64_json
        img = b64decode(b64)
        # Save under app/static/uploads
        here = os.path.dirname(os.path.abspath(__file__))
        uploads = os.path.join(os.path.dirname(here), "app", "static", "uploads")
        os.makedirs(uploads, exist_ok=True)
        fname = f"openai_test_{int(time.time())}.png"
        path = os.path.join(uploads, fname)
        with open(path, "wb") as f:
            f.write(img)
        dt = time.time() - t0
        print("OK")
        print(f"saved: {path}")
        print(f"elapsed_s: {dt:.2f}")
        # If BASE_URL is set, show absolute URL
        base_url = os.getenv("BASE_URL", "").rstrip("/")
        if base_url:
            print(f"url: {base_url}/static/uploads/{fname}")
        return 0
    except Exception as e:
        print(f"ERROR: generation failed: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())



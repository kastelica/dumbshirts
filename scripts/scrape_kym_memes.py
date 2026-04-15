import json
import sys
import time
from typing import List, Dict
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


BASE = "https://knowyourmeme.com"


def fetch_html(url: str, timeout: int = 15) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def _clean_title(title: str) -> str:
    t = (title or "").strip()
    # Remove common artifacts like 'X★X' and arrows
    if "★" in t:
        parts = [p.strip() for p in t.split("★") if p.strip()]
        # If duplicates like 'Doge★Doge', keep the first
        if parts:
            t = parts[0]
    t = t.replace("→", "").strip()
    return t


def parse_listing(html: str) -> List[Dict[str, str]]:
    """Return entries with title and detail page slug/url from the listing page.

    We intentionally ignore thumbnail images on the listing, since the goal is to
    fetch the canonical image from the detail page.
    """
    soup = BeautifulSoup(html, "html.parser")
    results: List[Dict[str, str]] = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        # Normalize to absolute
        abs_url = urljoin(BASE, href)
        p = urlparse(abs_url)
        if not p.path.startswith("/memes/"):
            continue
        # Require exactly two path segments: /memes/<slug>
        segs = [s for s in p.path.split("/") if s]
        if len(segs) != 2:
            continue
        slug = segs[1]
        # Exclude category/utility slugs
        banned = {"new", "submissions", "confirmed", "newsworthy", "deadpool", "page"}
        if slug in banned or slug.startswith("page"):
            continue

        title = _clean_title(a.get_text(strip=True) or "")
        if not title or len(title) < 2:
            continue
        key = (title, slug)
        if key in seen:
            continue
        seen.add(key)
        results.append({"title": title, "slug": slug, "url": abs_url})

    return results


def parse_detail_image(html: str) -> str:
    """Best-effort extraction of the primary image URL from a meme detail page."""
    soup = BeautifulSoup(html, "html.parser")
    # Prefer prominent body copy image
    # Try OpenGraph first
    og = soup.find("meta", attrs={"property": "og:image"})
    if og and og.get("content"):
        return og["content"].strip()

    selectors = [
        'a.photo.left.wide[href*="/entries/icons/"]',
        "section.bodycopy a[href*='/entries/icons/']",
        "#entry_body a[href*='/entries/icons/']",
        "section.bodycopy img.kym-image",
        "article.entry img.kym-image",
        "#entry_body img.kym-image",
        "img.kym-image",
    ]
    for sel in selectors:
        el = soup.select_one(sel)
        if not el:
            continue
        # Anchor points to full-size icon
        if el.name == "a" and el.get("href"):
            return urljoin(BASE, el["href"])  # original icon
        # Else read from image
        src = el.get("src") or el.get("data-src") or el.get("data-image") or ""
        if src:
            return src
    return ""


def main():
    url = "https://knowyourmeme.com/memes?kind=all&sort=views"
    if len(sys.argv) > 1:
        url = sys.argv[1]

    html = fetch_html(url)
    entries = parse_listing(html)

    # Optionally follow to detail pages to fetch canonical images
    with_images = []
    for i, e in enumerate(entries[:100]):  # cap to first 100
        try:
            detail_html = fetch_html(e["url"])
            img = parse_detail_image(detail_html)
        except Exception:
            img = ""
        with_images.append({"title": e["title"], "slug": e["slug"], "url": e["url"], "image": img})
        # Be polite
        time.sleep(0.2)

    print(json.dumps({"count": len(with_images), "memes": with_images}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()



import os
import sys
import re
import unicodedata
import difflib
from decimal import Decimal
from typing import List, Dict, Iterable

# Ensure project root (containing the `app` package) is on sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app import create_app
from app.extensions import db
from app.models import Category, Design, Product, Variant
from app.utils import slugify

# Reuse scraper pieces
from scripts.scrape_kym_memes import fetch_html, parse_listing, parse_detail_image, BASE


def get_or_create_category(name: str, slug: str) -> Category:
    cat = Category.query.filter_by(slug=slug).first()
    if not cat:
        cat = Category(name=name, slug=slug)
        db.session.add(cat)
        db.session.commit()
    return cat


def create_product_from_image(title: str, image_url: str) -> Product:
    """Create a draft shirt product with a square front design image."""
    # 1) Design row
    d = Design(type="image", text=title, approved=True)
    d.image_url = image_url
    d.preview_url = image_url
    d.extra_image1_url = image_url
    db.session.add(d)
    db.session.flush()

    # 2) Product row with pricing
    base_cost = Decimal("18.00")
    from flask import current_app
    markup_percent = Decimal(str(current_app.config.get("MARKUP_PERCENT", 35)))
    price = (base_cost * (Decimal(1) + markup_percent / Decimal(100))).quantize(Decimal("0.01"))

    # Append "T-Shirt" to product titles
    product_title = f"{title} T-Shirt"
    base_slug = slugify(product_title) or "product"
    slug = base_slug
    idx = 2
    while Product.query.filter_by(slug=slug).first():
        slug = f"{base_slug}-{idx}"
        idx += 1

    p = Product(
        slug=slug,
        title=product_title,
        description=f"Free Shipping! Shirt inspired by the meme '{title}'. 100% Cotton, Crewneck, Unisex.",
        status="draft",
        base_cost=base_cost,
        price=price,
        currency=(current_app.config.get("STORE_CURRENCY", "USD")),
        design=d,
    )
    db.session.add(p)
    db.session.flush()

    # Category: Shirts
    shirts = get_or_create_category("Shirts", "shirts")
    p.categories.append(shirts)

    # 3) Variants: sizes S-XL, colors Black/White, printed on front
    for size in ["S", "M", "L", "XL"]:
        for color in ["Black", "White"]:
            v = Variant(
                product_id=p.id,
                name=f"{size} / {color} / Front",
                color=color,
                size=size,
                print_area="front",
                price=p.price,
                base_cost=p.base_cost,
            )
            db.session.add(v)
    db.session.flush()

    return p


def main() -> None:
    url = "https://knowyourmeme.com/memes?kind=all&sort=views"
    limit = 5
    if len(sys.argv) > 1:
        try:
            limit = int(sys.argv[1])
        except Exception:
            pass
    if len(sys.argv) > 2:
        url = sys.argv[2]

    app = create_app()
    with app.app_context():
        # Helpers for fuzzy duplicate detection
        STOP = {"the", "a", "an", "meme", "shirt", "t-shirt", "tshirt", "tee"}
        def _norm_title(s: str) -> str:
            if not s:
                return ""
            s2 = unicodedata.normalize("NFKD", s)
            s2 = s2.encode("ascii", "ignore").decode("ascii")
            s2 = s2.lower()
            s2 = re.sub(r"[^a-z0-9]+", " ", s2)
            toks = [t for t in s2.split() if t and t not in STOP]
            return " ".join(toks)

        # Load existing slugs and titles once
        existing_slug_rows = db.session.query(Product.slug).all()
        existing_slugs = {row[0] for row in existing_slug_rows if row and row[0]}
        existing_title_rows = db.session.query(Product.title).all()
        existing_titles = [row[0] for row in existing_title_rows if row and row[0]]
        existing_design_rows = db.session.query(Design.text).all()
        existing_design_titles = [row[0] for row in existing_design_rows if row and row[0]]
        existing_norm_titles = {_norm_title(t) for t in (existing_titles + existing_design_titles)}
        # 1) Scrape listing and follow detail pages for images
        html = fetch_html(url)
        entries = parse_listing(html)
        picked = entries[:limit]

        created = 0
        def _already_imported(title: str, meme_slug: str) -> bool:
            # Check by final product slug (title + " T-Shirt")
            pslug = slugify(f"{title} T-Shirt")
            if pslug in existing_slugs:
                return True
            # Check by existing product pointing to a Design with same text title
            if title in existing_design_titles:
                return True
            # Legacy: if an older run used the meme slug directly
            if meme_slug in existing_slugs:
                return True
            # Fuzzy: normalized match or high similarity to any existing title
            cand_norm = _norm_title(title)
            if not cand_norm:
                return False
            if cand_norm in existing_norm_titles:
                return True
            for t in existing_norm_titles:
                if not t:
                    continue
                if difflib.SequenceMatcher(None, cand_norm, t).ratio() >= 0.90:
                    return True
            return False

        for e in picked:
            if _already_imported(e["title"], e["slug"]):
                continue
            try:
                dhtml = fetch_html(e["url"])
                img = parse_detail_image(dhtml)
            except Exception:
                img = ""
            if not img:
                continue
            p = create_product_from_image(e["title"], img)
            db.session.commit()
            created += 1
            print(f"Created product {p.id}: {p.title}")

        print(f"Done. Created {created} products.")


if __name__ == "__main__":
    main()



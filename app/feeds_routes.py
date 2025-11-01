from flask import Blueprint, url_for, current_app
from urllib.parse import urljoin
from .feeds import render_google_shopping_feed, render_google_promotions_feed
from flask import Response
import os
import json
from .models import Product, Promotion
from decimal import Decimal
import datetime
from flask import url_for, current_app

feeds_bp = Blueprint("feeds", __name__)


@feeds_bp.get("/feeds/google.xml")
def google_feed():
	products = Product.query.filter_by(status="active").all()
	items = []

	def _absolute_url(u: str) -> str:
		if not u:
			return ""
		if u.startswith("http://") or u.startswith("https://"):
			return u
		base = current_app.config.get("BASE_URL", "http://localhost:5000")
		return urljoin(base, u)

	for p in products:
		# Compute 15% off sale price
		try:
			sale = (Decimal(str(p.price)) * Decimal('0.85')).quantize(Decimal('0.01'))
		except Exception:
			sale = p.price
		# Build additional images list (up to 10 allowed; we add up to 2 if present)
		add_imgs = []
		try:
			if p.design and getattr(p.design, 'extra_image1_url', None):
				add_imgs.append(_absolute_url(p.design.extra_image1_url))
			if p.design and getattr(p.design, 'extra_image2_url', None):
				add_imgs.append(_absolute_url(p.design.extra_image2_url))
		except Exception:
			pass

		checkout_url = url_for('main.checkout', item_id=p.id, _external=True)
		items.append({
			"id": p.id,
			"title": p.title,
			"link": url_for('main.product_detail', slug=p.slug, _external=True),
			"description": p.description or "",
			"price": f"{p.price}",
			"sale_price": f"{sale}",
			"cost_of_goods_sold": "8.64",
			"auto_pricing_min_price": "18.99",
			"availability": "in stock",
			"image": _absolute_url(p.design.preview_url if (p.design and p.design.preview_url) else ""),
			"additional_images": add_imgs,
			"brand": "Dumbshirts.store",
			"age_group": "adult",
			"color": "white",
			"gender": "unisex",
			"size": "Large",
			"checkout_link_template": checkout_url,
			# Google Shopping
			"google_product_category": "Apparel & Accessories > Clothing > Shirts & Tops",
			"product_type": "t-shirt",
			"shipping": {"country": "US"},
		})
		# Removed monthly subscription items from Shopping feed
	return render_google_shopping_feed(items)


@feeds_bp.get("/feeds/promotions.xml")
def promotions_feed():
    # Read promotions from DB so they persist across deploys; fail soft if table missing
    rows = []
    try:
        for p in Promotion.query.order_by(Promotion.created_at.desc()).all():
            rows.append({
                "promotion_id": p.promotion_id,
                "long_title": p.long_title,
                "percent_off": p.percent_off,
                "generic_redemption_code": p.generic_redemption_code,
                "start_date": p.start_date,
                "end_date": p.end_date,
                "display_start_date": p.display_start_date,
                "display_end_date": p.display_end_date,
                "promotion_url": p.promotion_url,
                "promotion_destination": (p.promotion_destination.split(',') if p.promotion_destination else ["Shopping_ads", "Free_listings"]),
                "redemption_channel": p.redemption_channel or "online",
            })
    except Exception as _e:
        current_app.logger.warning(f"[promotions] feed fallback, table missing: {_e}")
    return render_google_promotions_feed(rows)


@feeds_bp.get("/feeds/reviews.xml")
def reviews_feed():
    """Google Product Review Feed following the official schema 2.4.
    
    Implements the complete Google Product Review Feed schema as defined in:
    http://www.google.com/shopping/reviews/schema/product/2.4/product_reviews.xsd
    """
    # Load reviews from data JSON managed via admin
    try:
        data_path = os.path.join(os.path.dirname(__file__), "data", "reviews.json")
        with open(data_path, "r", encoding="utf-8") as f:
            reviews = json.load(f) or []
    except Exception:
        reviews = []

    # Build XML following Google Product Review Feed schema
    from xml.etree.ElementTree import Element, SubElement, tostring
    root = Element("feed")
    
    # Required top-level elements in order
    SubElement(root, "version").text = "2.4"
    
    # Publisher (required)
    publisher = SubElement(root, "publisher")
    SubElement(publisher, "name").text = "Dumbshirts.store"
    base = current_app.config.get("BASE_URL", "http://localhost:5000").rstrip("/")
    SubElement(publisher, "favicon").text = f"{base}/static/uploads/brand.png"
    
    # Reviews container
    reviews_container = SubElement(root, "reviews")
    
    # Map products to ensure stable references
    prods = {p.id: p for p in Product.query.all()}

    for r in reviews:
        # Skip reviews without product_id
        pid = r.get("product_id")
        if not pid:
            continue
            
        p = prods.get(int(pid)) if pid else None
        if not p:
            continue
            
        # Individual review
        review = SubElement(reviews_container, "review")
        
        # Required fields
        SubElement(review, "review_id").text = str(r.get("review_id", f"R-{r.get('product_id', 'unknown')}"))
        
        # Reviewer (required)
        reviewer = SubElement(review, "reviewer")
        reviewer_name = SubElement(reviewer, "name")
        reviewer_name.text = str(r.get("reviewer_name", "Customer"))
        
        # Review timestamp (required) - convert to proper format
        review_timestamp = r.get("created_at", "")
        if not review_timestamp:
            review_timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        SubElement(review, "review_timestamp").text = review_timestamp
        
        # Content (required)
        SubElement(review, "content").text = str(r.get("content", ""))
        
        # Review URL (required) - use product URL if no specific review URL
        review_url = r.get("review_url", "")
        if not review_url and p:
            review_url = url_for('main.product_detail', slug=p.slug, _external=True)
        if review_url:
            review_url_elem = SubElement(review, "review_url")
            review_url_elem.text = review_url
            review_url_elem.set("type", "singleton")
        
        # Ratings (required)
        ratings = SubElement(review, "ratings")
        overall = SubElement(ratings, "overall")
        overall.text = str(r.get("rating", "5"))
        overall.set("min", "1")
        overall.set("max", "5")
        
        # Products (required)
        products = SubElement(review, "products")
        product = SubElement(products, "product")
        
        # Product name
        SubElement(product, "product_name").text = p.title
        
        # Product URL (required)
        SubElement(product, "product_url").text = url_for('main.product_detail', slug=p.slug, _external=True)
        
        # Product IDs (required for matching)
        product_ids = SubElement(product, "product_ids")
        
        # SKUs (required for products with known SKU)
        skus = SubElement(product_ids, "skus")
        SubElement(skus, "sku").text = str(p.id)
        
        # MPNs (Manufacturer Part Numbers) - use product ID as MPN
        mpns = SubElement(product_ids, "mpns")
        SubElement(mpns, "mpn").text = str(p.id)
        
        # Brands (required for products with known brand)
        brands = SubElement(product_ids, "brands")
        SubElement(brands, "brand").text = "Dumbshirts.store"
        
        # Optional fields
        if r.get("title"):
            SubElement(review, "title").text = str(r.get("title"))
        
        # Mark as verified purchase (optional)
        SubElement(review, "is_verified_purchase").text = "true"
        
        # Mark as not incentivized (optional)
        SubElement(review, "is_incentivized_review").text = "false"

    xml_bytes = tostring(root, encoding="utf-8", xml_declaration=True)
    return Response(xml_bytes, content_type="application/xml; charset=utf-8")

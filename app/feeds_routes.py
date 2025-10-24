from flask import Blueprint, url_for, current_app
from urllib.parse import urljoin
from .feeds import render_google_shopping_feed, render_google_promotions_feed
import os
import json
from .models import Product, Promotion
from decimal import Decimal

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
		# Compute 5% off sale price
		try:
			sale = (Decimal(str(p.price)) * Decimal('0.95')).quantize(Decimal('0.01'))
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

		items.append({
			"id": p.id,
			"title": p.title,
			"link": url_for('main.product_detail', slug=p.slug, _external=True),
			"description": p.description or "",
			"price": f"{p.price}",
			"sale_price": f"{sale}",
			"availability": "in stock",
			"image": _absolute_url(p.design.preview_url if (p.design and p.design.preview_url) else ""),
			"additional_images": add_imgs,
			"brand": "Dumbshirts.store",
			"age_group": "adult",
			"color": "white",
			"gender": "unisex",
			"size": "Large",
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

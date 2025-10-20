from flask import Blueprint, url_for, current_app
from urllib.parse import urljoin
from .feeds import render_google_shopping_feed
from .models import Product
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
		items.append({
			"id": p.id,
			"title": p.title,
			"link": url_for('main.product_detail', slug=p.slug, _external=True),
			"description": p.description or "",
			"price": f"{p.price}",
			"sale_price": f"{sale}",
			"availability": "in stock",
			"image": _absolute_url(p.design.preview_url if (p.design and p.design.preview_url) else ""),
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
	return render_google_shopping_feed(items)

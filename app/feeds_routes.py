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
        # Add a subscription variant item linking to the subscription landing page (one price per page)
        items.append({
            "id": f"sub-{p.id}",
            "title": f"{p.title} - Monthly Subscription",
            "link": url_for('main.subscribe_monthly', _external=True),
            "description": (p.description or "") + " Monthly subscription: $15.00 billed every 1 month.",
            "price": f"15.00",
            "availability": "in stock",
            "image": _absolute_url(p.design.preview_url if (p.design and p.design.preview_url) else ""),
            "brand": "Dumbshirts.store",
            "age_group": "adult",
            "color": "white",
            "gender": "unisex",
            "size": "Large",
            "google_product_category": "Apparel & Accessories > Clothing > Shirts & Tops",
            "product_type": "t-shirt",
            "shipping": {"country": "US"},
            "subscription_cost": {"period": "month", "period_length": 1, "amount": "15.00 USD"},
        })
	return render_google_shopping_feed(items)

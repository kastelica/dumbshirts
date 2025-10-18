from flask import Blueprint, url_for
from .feeds import render_google_shopping_feed
from .models import Product

feeds_bp = Blueprint("feeds", __name__)


@feeds_bp.get("/feeds/google.xml")
def google_feed():
	products = Product.query.filter_by(status="active").all()
	items = []
	for p in products:
		items.append({
			"id": p.id,
			"title": p.title,
			"link": url_for('main.product_detail', slug=p.slug, _external=True),
			"description": p.description or "",
			"price": f"{p.price}",
			"availability": "in stock",
		})
	return render_google_shopping_feed(items)

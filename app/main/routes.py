from flask import render_template, current_app, request, abort, session
from . import main_bp
from ..models import Product, Category, Variant, Trend
from decimal import Decimal


@main_bp.get("/")
def index():
	products = Product.query.filter_by(status="active").order_by(Product.created_at.desc()).limit(9).all()
	return render_template("index.html", products=products)


@main_bp.get("/shop")
def shop():
	# Filters
	cat_slug = request.args.get("cat", "").strip()
	sort = request.args.get("sort", "newest").strip()
	min_price = request.args.get("min", "").strip()
	max_price = request.args.get("max", "").strip()

	q = Product.query.filter_by(status="active")
	if cat_slug:
		q = q.join(Product.categories).filter(Category.slug == cat_slug)
	if min_price:
		try:
			q = q.filter(Product.price >= Decimal(min_price))
		except Exception:
			pass
	if max_price:
		try:
			q = q.filter(Product.price <= Decimal(max_price))
		except Exception:
			pass

	if sort == "price_asc":
		q = q.order_by(Product.price.asc())
	elif sort == "price_desc":
		q = q.order_by(Product.price.desc())
	else:  # newest
		q = q.order_by(Product.created_at.desc())

	products = q.all()
	categories = Category.query.order_by(Category.name.asc()).all()
	return render_template(
		"shop.html",
		products=products,
		categories=categories,
		selected_cat=cat_slug,
		sort=sort,
		min_price=min_price,
		max_price=max_price,
	)


@main_bp.get("/search")
def search():
	q = request.args.get("q", "").strip()
	results = []
	# Recent approved trends for bubbles
	trend_bubbles = Trend.query.filter_by(status="approved").order_by(Trend.created_at.desc()).limit(10).all()
	if q:
		like = f"%{q}%"
		results = Product.query.filter(Product.status == "active").filter(
			(Product.title.ilike(like)) | (Product.description.ilike(like))
		).order_by(Product.created_at.desc()).all()
	return render_template("search.html", q=q, results=results, trend_bubbles=trend_bubbles)


@main_bp.get("/product/<slug>")
def product_detail(slug: str):
	product = Product.query.filter_by(slug=slug).first_or_404()
	if product.status != "active":
		return abort(404)
	# Collect available sizes/colors from variants (mock if none)
	sizes = sorted({v.size for v in product.variants if v.size}) or ["S", "M", "L", "XL"]
	colors = sorted({v.color for v in product.variants if v.color}) or ["Black", "White"]
	images = [
		{"src": product.design.preview_url or "", "alt": product.title},
		{"src": "", "alt": product.title},
		{"src": "", "alt": product.title},
	]
	# Prev/Next products by created_at among active products
	prev_p = Product.query.filter(Product.status == "active", Product.created_at < product.created_at).order_by(Product.created_at.desc()).first()
	next_p = Product.query.filter(Product.status == "active", Product.created_at > product.created_at).order_by(Product.created_at.asc()).first()
	return render_template(
		"product_detail.html",
		product=product,
		sizes=sizes,
		colors=colors,
		images=images,
		prev_slug=(prev_p.slug if prev_p else None),
		next_slug=(next_p.slug if next_p else None),
	)


@main_bp.get("/checkout")
def checkout():
	cart = session.get("cart") or {"items": []}
	total = Decimal("0.00")
	for it in cart.get("items", []):
		total += Decimal(str(it.get("price", 0))) * int(it.get("quantity", 0))
	publishable = current_app.config.get("STRIPE_PUBLISHABLE_KEY", "")
	return render_template(
		"checkout.html",
		publishable_key=publishable,
		cart=cart,
		total_amount=float(total),
		currency=current_app.config.get("STORE_CURRENCY", "USD"),
	)


@main_bp.get("/health")
def health():
	return {"status": "ok"}

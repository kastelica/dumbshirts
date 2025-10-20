from flask import render_template, current_app, request, abort, session, Response
from . import main_bp
from ..models import Product, Category, Variant, Trend
from decimal import Decimal
from ..models import Order, Address
from urllib.parse import urljoin
from datetime import datetime
from ..gelato_client import GelatoClient


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
		# Sum discounted price stored in cart
		total += Decimal(str(it.get("price", 0))) * int(it.get("quantity", 0))
	publishable = current_app.config.get("STRIPE_PUBLISHABLE_KEY", "")
	return render_template(
		"checkout.html",
		publishable_key=publishable,
		cart=cart,
		total_amount=float(total),
		currency=current_app.config.get("STORE_CURRENCY", "USD"),
	)


@main_bp.get("/loyalty")
def loyalty_page():
	"""Show loyalty status for the email stored in session, or a signup form."""
	email = (session.get("loyalty_email") or "").strip().lower()
	points = 0
	tier = "none"
	perks = []
	if email:
		# Sum dollars from qualifying orders for this email
		total_spent = Decimal("0.00")
		q = Order.query.filter(Order.status.in_(["paid", "submitted", "fulfilled"]))
		q = q.join(Address, Order.shipping_address_id == Address.id).filter(Address.email.ilike(email))
		for o in q.all():
			total_spent += (o.total_amount or Decimal("0.00"))
		points = int(total_spent)
		if points >= 100:
			tier = "vip"
			perks = ["Bigger discounts", "One free shirt"]
		else:
			tier = "member"
	return render_template("loyalty.html", email=email, points=points, tier=tier, perks=perks)


@main_bp.post("/loyalty/signup")
def loyalty_signup():
	email = (request.form.get("email") or "").strip().lower()
	if email:
		session["loyalty_email"] = email
		session.modified = True
	return render_template("loyalty.html", email=email, points=0, tier="member", perks=[]) 


@main_bp.get("/health")
def health():
	return {"status": "ok"}


@main_bp.get("/shipping-returns")
def shipping_returns():
	return render_template("shipping_returns.html")


@main_bp.get("/contact")
def contact_page():
	return render_template("contact.html")


@main_bp.get("/privacy")
def privacy_page():
	return render_template("privacy.html")


@main_bp.get("/terms")
def terms_page():
	return render_template("terms.html")


@main_bp.get("/sitemap.xml")
def sitemap_xml():
	base = current_app.config.get("BASE_URL", request.url_root).rstrip("/")
	items = []
	iso_today = datetime.utcnow().date().isoformat()

	def add_url(loc: str, lastmod: str | None = None, changefreq: str | None = None, priority: str | None = None, image: str | None = None, image_title: str | None = None):
		parts = [f"<loc>{loc}</loc>"]
		if lastmod:
			parts.append(f"<lastmod>{lastmod}</lastmod>")
		if changefreq:
			parts.append(f"<changefreq>{changefreq}</changefreq>")
		if priority:
			parts.append(f"<priority>{priority}</priority>")
		if image:
			img = f"<image:image><image:loc>{image}</image:loc>" + (f"<image:title>{image_title}</image:title>" if image_title else "") + "</image:image>"
			parts.append(img)
		items.append("<url>" + "".join(parts) + "</url>")

	# Static pages
	static_pages = [
		("/", iso_today, "daily", "0.9"),
		("/shop", iso_today, "daily", "0.8"),
		("/search", iso_today, "weekly", "0.5"),
		("/cart", iso_today, "daily", "0.3"),
		("/checkout", iso_today, "daily", "0.6"),
		("/shipping-returns", iso_today, "yearly", "0.3"),
		("/contact", iso_today, "yearly", "0.2"),
		("/privacy", iso_today, "yearly", "0.2"),
		("/terms", iso_today, "yearly", "0.2"),
	]
	for path, lm, cf, pr in static_pages:
		add_url(urljoin(base, path), lm, cf, pr)

	# Category filtered pages
	for c in Category.query.all():
		add_url(urljoin(base, f"/shop?cat={c.slug}"), iso_today, "weekly", "0.6")

	# Product pages with images and lastmod
	for p in Product.query.filter_by(status="active").all():
		img = p.design.preview_url if getattr(p, "design", None) and p.design.preview_url else ""
		img_abs = img if (img.startswith("http://") or img.startswith("https://")) else (urljoin(base, img) if img else None)
		lm = (p.updated_at or p.created_at).date().isoformat() if getattr(p, "updated_at", None) or getattr(p, "created_at", None) else iso_today
		add_url(urljoin(base, f"/product/{p.slug}"), lm, "weekly", "0.7", img_abs, p.title)

	xml = (
		"<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
		+ "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\" xmlns:image=\"http://www.google.com/schemas/sitemap-image/1.1\">"
		+ "".join(items)
		+ "</urlset>"
	)
	return Response(xml, content_type="application/xml")


@main_bp.get("/robots.txt")
def robots_txt():
	base = current_app.config.get("BASE_URL", request.url_root).rstrip("/")
	body = f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n"
	return Response(body, content_type="text/plain")


@main_bp.get("/api/gelato/product")
def gelato_product_info():
	uid = (request.args.get("uid") or "").strip()
	if not uid:
		return jsonify({"error": "missing uid"}), 400
	try:
		client = GelatoClient()
		data = client.get_product_v3(uid)
		return jsonify(data)
	except Exception as e:
		return jsonify({"error": str(e)}), 400

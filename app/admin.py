from decimal import Decimal
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_user, logout_user, login_required
from .extensions import db
from .models import Admin, Design, Product, Category, Variant, Trend
from .trends import fetch_trending_phrases_any
from .trends_store import load_cache, save_cache
from .gelato_client import GelatoClient
from flask import current_app
from .utils import slugify, normalize_trend_term
from .phrasegen import generate_candidates_from_title, memeify_term
import os
from werkzeug.utils import secure_filename

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.get("/login")
def login_page():
	return render_template("admin_login.html")


@admin_bp.post("/login")
def login_submit():
	email = request.form.get("email", "").strip().lower()
	password = request.form.get("password", "")
	admin = Admin.query.filter_by(email=email).first()
	if not admin or not admin.check_password(password):
		flash("Invalid credentials", "error")
		return redirect(url_for("admin.login_page"))
	login_user(admin)
	return redirect(url_for("admin.dashboard"))


@admin_bp.get("/logout")
@login_required
def logout():
	logout_user()
	return redirect(url_for("admin.login_page"))


@admin_bp.get("/")
@login_required
def dashboard():
	pending = Design.query.filter_by(approved=False).order_by(Design.created_at.desc()).all()
	return render_template("admin_dashboard.html", pending=pending)


@admin_bp.get("/trends")
@login_required
def trends_page():
	geo = request.args.get("geo", "US").upper()
	limit = int(request.args.get("limit", "10"))
	refresh = request.args.get("refresh") == "1"

	cached = None if refresh else load_cache(geo)
	phrases = []
	debug = {}
	if cached:
		phrases = cached.get("phrases", [])[:limit]
		debug = {**cached.get("debug", {}), "cache": "hit", "ts": cached.get("ts", "")}
	else:
		phrases, debug = fetch_trending_phrases_any(geo=geo, limit=limit)
		save_cache(geo, phrases, debug)
		debug = {**debug, "cache": "miss"}

	source = (debug or {}).get("source", "")
	suggestions = []
	for title_or_term in phrases:
		norm = normalize_trend_term(title_or_term)
		if not norm:
			continue
		existing = Trend.query.filter_by(normalized=norm).first()
		if not existing:
			t = Trend(term=title_or_term.strip(), normalized=norm, slug=slugify(norm), source=source, geo=geo, status="new")
			db.session.add(t)
		if source == "serpapi":
			cands = memeify_term(title_or_term, max_candidates=3)
		else:
			cands = generate_candidates_from_title(title_or_term, max_candidates=2)
			if not cands:
				cands = memeify_term(title_or_term, max_candidates=2)
		suggestions.append({"title": title_or_term, "normalized": norm, "candidates": cands})
	db.session.commit()
	trends = Trend.query.order_by(Trend.created_at.desc()).limit(50).all()
	return render_template("trends_admin.html", phrases=phrases, suggestions=suggestions, trends=trends, debug=debug, geo=geo, limit=limit, refresh=refresh)


@admin_bp.post("/designs/queue")
@login_required
def queue_design():
	phrase = request.form.get("phrase", "").strip()
	if not phrase:
		return redirect(url_for("admin.trends_page"))
	design = Design(type="text", text=phrase, approved=False)
	db.session.add(design)
	db.session.commit()
	flash("Design queued as draft", "success")
	return redirect(url_for("admin.trends_page"))


@admin_bp.post("/trends/<int:trend_id>/approve")
@login_required
def approve_trend(trend_id: int):
	t = Trend.query.get_or_404(trend_id)
	t.status = "approved"
	db.session.commit()
	flash("Trend approved", "success")
	return redirect(url_for("admin.trends_page"))


@admin_bp.post("/trends/<int:trend_id>/ignore")
@login_required
def ignore_trend(trend_id: int):
	t = Trend.query.get_or_404(trend_id)
	t.status = "ignored"
	db.session.commit()
	flash("Trend ignored", "success")
	return redirect(url_for("admin.trends_page"))

def _create_product_for_design(design: Design) -> Product:
	base_cost = Decimal("10.00")
	markup_percent = Decimal(str(current_app.config.get("MARKUP_PERCENT", 35)))
	price = (base_cost * (Decimal(1) + markup_percent / Decimal(100))).quantize(Decimal("0.01"))

	title = f"Trending '{design.text}' Tee"
	base_slug = slugify(title)
	slug = base_slug or slugify(design.text) or "product"
	idx = 2
	while Product.query.filter_by(slug=slug).first():
		slug = f"{base_slug}-{idx}"
		idx += 1

	product = Product(
		slug=slug,
		title=title,
		description=f"Text design: {design.text}",
		status="draft",
		base_cost=base_cost,
		price=price,
		currency=current_app.config.get("STORE_CURRENCY", "USD"),
		design=design,
	)
	db.session.add(product)
	cat = Category.query.filter_by(slug="shirts").first()
	if cat:
		product.categories.append(cat)
	db.session.commit()

	if not product.variants:
		for size in ["S", "M", "L", "XL"]:
			for color in ["Black", "White"]:
				v = Variant(
					product_id=product.id,
					name=f"{size} / {color} / Front",
					color=color,
					size=size,
					print_area="front",
					price=product.price,
					base_cost=product.base_cost,
				)
				db.session.add(v)
		db.session.commit()
	return product


DEFAULT_SINGLE_VARIANT_NAME = "L / White / Front"


def _ensure_single_variant(product: Product) -> None:
	"""Ensure the product has exactly one variant mapped to default tee UID."""
	from .config import BaseConfig
	# Remove existing variants
	for v in list(product.variants):
		db.session.delete(v)
	db.session.flush()
	# Create one variant
	uid = current_app.config.get("DEFAULT_TEE_UID")
	v = Variant(
		product_id=product.id,
		name=DEFAULT_SINGLE_VARIANT_NAME,
		color="White",
		size="L",
		print_area="front",
		gelato_sku=uid,
		price=product.price,
		base_cost=product.base_cost,
	)
	db.session.add(v)
	db.session.flush()


@admin_bp.post("/designs/<int:design_id>/approve")
@login_required
def approve_design(design_id: int):
	design = Design.query.get_or_404(design_id)
	design.approved = True
	db.session.commit()
	# Auto-create a draft product page for this approved design
	product = Product.query.filter_by(design_id=design.id).first()
	if not product:
		product = _create_product_for_design(design)
	_ensure_single_variant(product)
	db.session.commit()
	flash("Design approved and draft product created", "success")
	return redirect(url_for("admin.edit_product_page", product_id=product.id))


@admin_bp.post("/designs/<int:design_id>/create-product")
@login_required
def create_product_from_design(design_id: int):
	design = Design.query.get_or_404(design_id)
	if not design.approved:
		flash("Approve the design first", "error")
		return redirect(url_for("admin.dashboard"))
	product = Product.query.filter_by(design_id=design.id).first()
	if not product:
		product = _create_product_for_design(design)
	_ensure_single_variant(product)
	db.session.commit()
	flash("Draft product created", "success")
	return redirect(url_for("admin.edit_product_page", product_id=product.id))


# Products management
@admin_bp.get("/products")
@login_required
def products_list():
	products = Product.query.order_by(Product.created_at.desc()).all()
	return render_template("admin_products.html", products=products)


@admin_bp.post("/products/<int:product_id>/toggle")
@login_required
def toggle_product_visibility(product_id: int):
	p = Product.query.get_or_404(product_id)
	p.status = "draft" if p.status == "active" else "active"
	db.session.commit()
	flash("Visibility updated", "success")
	return redirect(url_for("admin.products_list"))


@admin_bp.post("/products/<int:product_id>/publish")
@login_required
def publish_product(product_id: int):
	p = Product.query.get_or_404(product_id)
	p.status = "active"
	db.session.commit()
	flash("Product published", "success")
	return redirect(url_for("admin.edit_product_page", product_id=p.id))


@admin_bp.post("/products/<int:product_id>/unpublish")
@login_required
def unpublish_product(product_id: int):
	p = Product.query.get_or_404(product_id)
	p.status = "draft"
	db.session.commit()
	flash("Product unpublished", "success")
	return redirect(url_for("admin.edit_product_page", product_id=p.id))


@admin_bp.get("/products/<int:product_id>/preview")
@login_required
def preview_product(product_id: int):
	p = Product.query.get_or_404(product_id)
	return render_template("product_detail.html", product=p, sizes=sorted({v.size for v in p.variants if v.size}) or ["S","M","L","XL"], colors=sorted({v.color for v in p.variants if v.color}) or ["Black","White"], images=[{"src": p.design.preview_url or "", "alt": p.title}])


@admin_bp.get("/products/<int:product_id>/edit")
@login_required
def edit_product_page(product_id: int):
	p = Product.query.get_or_404(product_id)
	categories = Category.query.order_by(Category.name.asc()).all()
	selected_cat = p.categories[0].slug if p.categories else ""
	return render_template("admin_product_edit.html", product=p, categories=categories, selected_cat=selected_cat)


@admin_bp.post("/products/<int:product_id>/variants/<int:variant_id>/set-productuid")
@login_required
def set_variant_productuid(product_id: int, variant_id: int):
	p = Product.query.get_or_404(product_id)
	v = Variant.query.get_or_404(variant_id)
	if v.product_id != p.id:
		return redirect(url_for("admin.edit_product_page", product_id=p.id))
	uid = request.form.get("productUid", "").strip()
	v.gelato_sku = uid
	db.session.commit()
	flash("Variant updated", "success")
	return redirect(url_for("admin.edit_product_page", product_id=p.id))


@admin_bp.post("/products/<int:product_id>/variants/set-all-productuid")
@login_required
def set_all_variants_productuid(product_id: int):
	p = Product.query.get_or_404(product_id)
	uid = request.form.get("productUidAll", "").strip()
	if not uid:
		flash("Please provide a productUid", "error")
		return redirect(url_for("admin.edit_product_page", product_id=p.id))
	for v in p.variants:
		v.gelato_sku = uid
	db.session.commit()
	flash("Applied productUid to all variants", "success")
	return redirect(url_for("admin.edit_product_page", product_id=p.id))


@admin_bp.post("/products/<int:product_id>/edit")
@login_required
def edit_product_submit(product_id: int):
	p = Product.query.get_or_404(product_id)
	title = request.form.get("title", "").strip()
	description = request.form.get("description", "").strip()
	cat_slug = request.form.get("category", "").strip()
	generate_ai = request.form.get("generate_ai") == "1"
	image_file = request.files.get("image")

	if title:
		p.title = title
		# Regenerate slug if title changed
		new_slug = slugify(title)
		if new_slug != p.slug:
			base = new_slug
			slug = base
			idx = 2
			while Product.query.filter(Product.id != p.id, Product.slug == slug).first():
				slug = f"{base}-{idx}"
				idx += 1
			p.slug = slug
	p.description = description

	# Update category (tshirt/hoodie/mug)
	if cat_slug:
		cat = Category.query.filter_by(slug=cat_slug).first()
		if cat:
			p.categories = [cat]

	# Ensure design exists
	if not p.design:
		d = Design(type="text", text=p.title, approved=True)
		db.session.add(d)
		db.session.flush()
		p.design = d

	uploaded = False
	# Handle image upload
	if image_file and image_file.filename:
		fname = secure_filename(image_file.filename)
		upload_dir = os.path.join(os.path.dirname(__file__), "static", "uploads")
		os.makedirs(upload_dir, exist_ok=True)
		path = os.path.join(upload_dir, fname)
		image_file.save(path)
		# Public URL
		p.design.preview_url = f"/static/uploads/{fname}"
		uploaded = True

	# Placeholder AI generation (no external call yet)
	if generate_ai and not uploaded:
		text = (p.design.text or p.title or "Design").replace(" ", "+")
		p.design.preview_url = f"https://via.placeholder.com/1024x1024?text={text}"

	# Single-variant enforcement with default tee uid
	_ensure_single_variant(p)

	db.session.commit()
	flash("Product updated", "success")
	return redirect(url_for("admin.edit_product_page", product_id=p.id))


@admin_bp.post("/products/<int:product_id>/generate-image")
@login_required
def generate_openai_image(product_id: int):
	from base64 import b64decode
	import time
	prompt = (request.json or {}).get("prompt", "").strip()
	if not prompt:
		return jsonify({"error": "Missing prompt"}), 400
	api_key = current_app.config.get("OPENAI_API_KEY", "")
	if not api_key:
		return jsonify({"error": "OPENAI_API_KEY not set"}), 400
	try:
		# Use OpenAI SDK v1+ exclusively
		import os as _os
		_os.environ["OPENAI_API_KEY"] = api_key
		from openai import OpenAI
		client = OpenAI()
		result = client.images.generate(model="gpt-image-1", prompt=prompt, size="1024x1024")
		b64_data = result.data[0].b64_json

		img_bytes = b64decode(b64_data)
		fname = f"openai_{product_id}_{int(time.time())}.png"
		upload_dir = os.path.join(os.path.dirname(__file__), "static", "uploads")
		os.makedirs(upload_dir, exist_ok=True)
		path = os.path.join(upload_dir, fname)
		with open(path, "wb") as f:
			f.write(img_bytes)

		p = Product.query.get_or_404(product_id)
		if not p.design:
			d = Design(type="image", text=p.title, approved=True)
			db.session.add(d)
			db.session.flush()
			p.design = d
		p.design.preview_url = f"/static/uploads/{fname}"
		db.session.commit()
		return jsonify({"ok": True, "url": p.design.preview_url})
	except Exception as e:
		# Attach extra debug to aid troubleshooting
		version = None
		try:
			import openai as _ov
			version = getattr(_ov, "__version__", None)
		except Exception:
			pass
		return jsonify({
			"error": str(e),
			"type": e.__class__.__name__,
			"openai_version": version,
		}), 400


@admin_bp.get("/gelato")
@login_required
def gelato_status():
	client = GelatoClient()
	ok, debug = client.verify()
	return render_template("admin_gelato.html", ok=ok, debug=debug)

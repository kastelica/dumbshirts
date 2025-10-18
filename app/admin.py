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
import threading

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
	# Re-imaged: show existing tracked trends only, newest first
	trends = Trend.query.order_by(Trend.created_at.desc()).all()
	return render_template("trends_admin.html", trends=trends)


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

def _auto_import_trends(limit: int = 1, generate_images: bool = False, messages: list | None = None) -> int:
	"""Create draft products from the most recent trends (default: 1). Returns created count.

	Writes progress to current_app.logger and optional messages list for flashing.
	"""
	created = 0
	trends = Trend.query.order_by(Trend.created_at.desc()).limit(limit * 3).all()
	current_app.logger.info(f"[auto-mode] scanning {len(trends)} trends, target={limit}")
	if messages is not None:
		messages.append(f"Scanning {len(trends)} trends…")
	for t in trends:
		if t.products:
			current_app.logger.info(f"[auto-mode] skip already linked trend {t.id}:{t.normalized}")
			continue
		text = t.term or t.normalized
		if not text:
			continue
		current_app.logger.info(f"[auto-mode] creating design for '{text}'")
		d = Design(type="image", text=text, approved=True)
		db.session.add(d)
		db.session.flush()
		product = _create_product_for_design(d)
		product.status = "draft"
		_ensure_single_variant(product)
		if messages is not None:
			messages.append(f"Draft product '{product.title}' created.")
		if generate_images and current_app.config.get("OPENAI_API_KEY"):
			try:
				from base64 import b64decode
				import os as _os
				from openai import OpenAI
				_os.environ["OPENAI_API_KEY"] = current_app.config.get("OPENAI_API_KEY")
				client = OpenAI()
				prompt = f"Minimal bold text or simple icon graphic for '{text}'. Solid colors, transparent PNG, centered."
				res = client.images.generate(model="gpt-image-1", prompt=prompt, size="1024x1024")
				b64_data = res.data[0].b64_json
				img_bytes = b64decode(b64_data)
				fname = f"auto_{product.id}.png"
				upload_dir = os.path.join(os.path.dirname(__file__), "static", "uploads")
				os.makedirs(upload_dir, exist_ok=True)
				path = os.path.join(upload_dir, fname)
				with open(path, "wb") as f:
					f.write(img_bytes)
				product.design.preview_url = f"/static/uploads/{fname}"
				product.design.image_url = f"/static/uploads/{fname}"
				current_app.logger.info(f"[auto-mode] artwork generated {fname}")
			except Exception as e:
				current_app.logger.warning(f"[auto-mode] artwork generation failed: {e}")
		product.trends.append(t)
		current_app.logger.info(f"[auto-mode] linked trend {t.id} -> product {product.id}")
		created += 1
		break
	db.session.commit()
	current_app.logger.info(f"[auto-mode] created={created}")
	return created


@admin_bp.post("/auto-mode/toggle")
@login_required
def toggle_auto_mode():
	current = bool(current_app.config.get("AUTO_MODE", False))
	new_state = not current
	current_app.config["AUTO_MODE"] = new_state
	created = 0
	if new_state:
		steps = []
		created = _auto_import_trends(limit=1, generate_images=current_app.config.get("AUTO_MODE_GENERATE_IMAGES", False), messages=steps)
		flash("Auto mode ON.", "success")
		for m in steps:
			flash(m, "info")
		flash(f"Imported {created} product(s).", "success")
	else:
		flash("Auto mode OFF.", "success")
	return redirect(url_for("admin.products_list"))

@admin_bp.post("/trends/<int:trend_id>/create-tshirt")
@login_required
def create_tshirt_from_trend(trend_id: int):
	t = Trend.query.get_or_404(trend_id)
	text = t.term or t.normalized
	if not text:
		return redirect(url_for("admin.trends_page"))
	d = Design(type="text", text=text, approved=False)
	db.session.add(d)
	db.session.commit()
	flash("Queued design from trend", "success")
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

	# Use the raw trend term as the product title (no prefixes/suffixes)
	title = (design.text or "").strip()
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
		p.design.image_url = f"/static/uploads/{fname}"
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
	# Run in background to avoid 30s Heroku router timeout
	def _worker(app_ctx, pid: int, prm: str):
		with app_ctx:
			try:
				import os as _os
				_os.environ["OPENAI_API_KEY"] = api_key
				from openai import OpenAI
				client = OpenAI().with_options(timeout=20.0)
				import time as _time
				# Retry with backoff up to ~45s
				delays = [3, 6, 12, 24]
				last_err = None
				for attempt, delay in enumerate(delays, start=1):
					try:
						res = client.images.generate(model="gpt-image-1", prompt=prm, size="1024x1024")
						b64 = res.data[0].b64_json
						img = b64decode(b64)
						fname = f"openai_{pid}_{int(_time.time())}.png"
						upload_dir = os.path.join(os.path.dirname(__file__), "static", "uploads")
						os.makedirs(upload_dir, exist_ok=True)
						path = os.path.join(upload_dir, fname)
						with open(path, "wb") as f:
							f.write(img)
						p = Product.query.get(pid)
						if p:
							if not p.design:
								d = Design(type="image", text=p.title, approved=True)
								db.session.add(d)
								db.session.flush()
								p.design = d
							p.design.preview_url = f"/static/uploads/{fname}"
							p.design.image_url = f"/static/uploads/{fname}"
							db.session.commit()
						current_app.logger.info("generate-image bg completed via OpenAI")
						return
					except Exception as e:
						last_err = e
						current_app.logger.warning(f"generate-image attempt {attempt} failed: {e}")
						_time.sleep(delay)
				# Fallback: render simple text PNG so preview still appears
				try:
					from PIL import Image, ImageDraw, ImageFont
					p = Product.query.get(pid)
					text = (p.title if p else prm) or "Design"
					img = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
					draw = ImageDraw.Draw(img)
					font = ImageFont.load_default()
					# simple wrap
					words = text.split()
					lines = []
					line = ""
					for w in words:
						if len(line) + len(w) + 1 > 18:
							lines.append(line)
							line = w
						else:
							line = (line + " " + w).strip()
					if line:
						lines.append(line)
					content = "\n".join(lines[:6])
					w, h = draw.multiline_textsize(content, font=font, spacing=6)
					x = (1024 - w) // 2
					y = (1024 - h) // 2
					draw.multiline_text((x, y), content, fill=(0, 0, 0, 255), font=font, align="center", spacing=6)
					fname = f"fallback_{pid}_{int(_time.time())}.png"
					upload_dir = os.path.join(os.path.dirname(__file__), "static", "uploads")
					os.makedirs(upload_dir, exist_ok=True)
					path = os.path.join(upload_dir, fname)
					img.save(path, format="PNG")
					if p:
						if not p.design:
							d = Design(type="image", text=p.title, approved=True)
							db.session.add(d)
							db.session.flush()
							p.design = d
						p.design.preview_url = f"/static/uploads/{fname}"
						p.design.image_url = f"/static/uploads/{fname}"
						db.session.commit()
					current_app.logger.warning(f"generate-image used fallback after error: {last_err}")
				except Exception as e2:
					current_app.logger.error(f"generate-image fallback failed: {e2}")
			except Exception as e_all:
				current_app.logger.error(f"generate-image bg outer failed: {e_all}")

	thr = threading.Thread(target=_worker, args=(current_app.app_context(), product_id, prompt), daemon=True)
	thr.start()
	return jsonify({"ok": True, "started": True})


@admin_bp.get("/products/<int:product_id>/generate-status")
@login_required
def generate_status(product_id: int):
	p = Product.query.get_or_404(product_id)
	url = p.design.preview_url if p.design else ""
	return jsonify({"ready": bool(url), "url": url or ""})


@admin_bp.get("/gelato")
@login_required
def gelato_status():
	client = GelatoClient()
	ok, debug = client.verify()
	return render_template("admin_gelato.html", ok=ok, debug=debug)

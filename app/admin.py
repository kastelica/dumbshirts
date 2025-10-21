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


@admin_bp.post("/trends/import")
@login_required
def import_trends():
	geo = (request.form.get("geo") or "US").upper()
	try:
		limit = int(request.form.get("limit") or "10")
	except Exception:
		limit = 10
	limit = max(1, min(limit, 50))

	phrases, debug = fetch_trending_phrases_any(geo=geo, limit=limit)
	created = 0
	for phrase in phrases:
		norm = normalize_trend_term(phrase)
		if not norm:
			continue
		if Trend.query.filter_by(normalized=norm).first():
			continue
		slug = slugify(phrase) or slugify(norm) or "trend"
		base = slug
		idx = 2
		while Trend.query.filter_by(slug=slug).first():
			slug = f"{base}-{idx}"
			idx += 1
		t = Trend(
			term=phrase,
			normalized=norm,
			slug=slug,
			source=(debug.get("source") if isinstance(debug, dict) else None),
			status="new",
		)
		db.session.add(t)
		created += 1

	if created:
		try:
			save_cache(geo, phrases, debug if isinstance(debug, dict) else {})
		except Exception:
			pass
		db.session.commit()
		flash(f"Imported {created} new trend(s).", "success")
	else:
		flash("No new trends found.", "info")

	return redirect(url_for("admin.trends_page"))


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
				res = client.images.generate(model="gpt-image-1-mini", prompt=prompt, size="1024x1024")
				b64_data = res.data[0].b64_json
				img_bytes = b64decode(b64_data)
				cloud_url = current_app.config.get("CLOUDINARY_URL", "").strip()
				if cloud_url:
					import cloudinary.uploader as cu
					public_id = slugify(product.title or text or "design")
					res_up = cu.upload(img_bytes, folder="products", public_id=public_id, overwrite=True, resource_type="image")
					secure_url = res_up.get("secure_url") or res_up.get("url")
					product.design.preview_url = secure_url
					product.design.image_url = secure_url
				else:
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
	base_cost = Decimal("18.00")
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
		description=f"Free Shipping! Shirt inspired by the \{design.text}\ grab it before it's gone.",
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
	"""Ensure a primary variant exists and avoid deleting variants referenced by orders.

	Strategy:
	- If there are no variants: create one default variant.
	- If variants exist: pick one to keep (prefer one referenced by OrderItem), update it to defaults,
	  and delete only unreferenced extras. Referenced variants are preserved to avoid FK violations.
	"""
	# Local import to avoid circulars
	from .models import OrderItem

	uid = current_app.config.get("DEFAULT_TEE_UID")
	variant_ids = [v.id for v in product.variants]
	if not variant_ids:
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
		return

	# Determine which variants are referenced by existing order items
	ref_rows = db.session.query(OrderItem.variant_id).filter(OrderItem.variant_id.in_(variant_ids)).all()
	referenced_ids = {rid for (rid,) in ref_rows if rid is not None}

	# Choose a primary variant to keep (prefer referenced)
	keep_variant = None
	if referenced_ids:
		for v in product.variants:
			if v.id in referenced_ids:
				keep_variant = v
				break
	else:
		keep_variant = product.variants[0]

	# Update primary variant fields to match defaults
	keep_variant.name = DEFAULT_SINGLE_VARIANT_NAME
	keep_variant.color = "White"
	keep_variant.size = "L"
	keep_variant.print_area = "front"
	keep_variant.gelato_sku = uid
	keep_variant.price = product.price
	keep_variant.base_cost = product.base_cost

	# Delete only unreferenced, non-primary variants
	for v in list(product.variants):
		if v.id == keep_variant.id:
			continue
		if v.id in referenced_ids:
			# Preserve variants tied to orders to avoid FK violations
			continue
		db.session.delete(v)

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


@admin_bp.post("/products/<int:product_id>/gelato-order")
@login_required
def gelato_order_product(product_id: int):
	p = Product.query.get_or_404(product_id)
	# Hardcoded Gelato product UID to start with
	uid = "apparel_product_gca_t-shirt_gsc_crewneck_gcu_unisex_gqa_heavy-weight_gsi_l_gco_white_gpr_4-0_gildan_5000"
	# Build minimal draft order payload
	file_url = "https://cdn-origin.gelato-api-dashboard.ie.live.gelato.tech/docs/sample-print-files/logo.png"
	if p.design:
		if getattr(p.design, "image_url", None):
			file_url = p.design.image_url
		elif p.design.preview_url:
			file_url = p.design.preview_url
	from .gelato_client import GelatoClient
	client = GelatoClient()
	payload = {
		"orderType": "draft",
		"orderReferenceId": f"admin-product-{p.id}",
		"customerReferenceId": "admin-trigger",
		"currency": (p.currency or current_app.config.get("STORE_CURRENCY", "USD")),
		"items": [
			{
				"itemReferenceId": f"prod-{p.id}-1",
				"productUid": uid,
				"files": [ {"type": "default", "url": file_url} ],
				"quantity": 1,
			}
		],
		"shipmentMethodUid": current_app.config.get("DEFAULT_SHIPMENT_METHOD", "express"),
		"shippingAddress": {
			"firstName": "Test",
			"lastName": "Admin",
			"addressLine1": "451 Clarkson Ave",
			"addressLine2": "Brooklyn",
			"state": "NY",
			"city": "New York",
			"postCode": "11203",
			"country": "US",
			"email": "test@example.com",
			"phone": "123456789",
		},
	}
	try:
		res = client.create_order(payload)
		flash(f"Gelato order created: {res.get('id', 'ok')}", "success")
	except Exception as e:
		flash(f"Gelato order failed: {e}", "error")
	return redirect(url_for("admin.products_list"))


@admin_bp.post("/products/<int:product_id>/delete")
@login_required
def delete_product(product_id: int):
	p = Product.query.get_or_404(product_id)
	product_title = p.title
	
	# Handle foreign key constraints by first removing references
	# Delete order items that reference this product's variants
	from .models import OrderItem
	OrderItem.query.filter(OrderItem.product_id == p.id).delete()
	
	# Delete variants (now safe since no order items reference them)
	for variant in p.variants:
		db.session.delete(variant)
	
	# Remove product from categories and trends
	p.categories.clear()
	p.trends.clear()
	
	# Delete the design if it's only used by this product
	if p.design and len(p.design.products) <= 1:
		db.session.delete(p.design)
	
	# Finally delete the product
	db.session.delete(p)
	db.session.commit()
	flash(f"Product '{product_title}' deleted", "success")
	return redirect(url_for("admin.products_list"))

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
		# Upload to Cloudinary if configured; fallback to local
		cloud_url = current_app.config.get("CLOUDINARY_URL", "").strip()
		if cloud_url:
			import cloudinary.uploader as cu
			public_id = slugify(p.title or "design")
			res = cu.upload(image_file, folder="products", public_id=public_id, overwrite=True, resource_type="image")
			secure_url = res.get("secure_url") or res.get("url")
			p.design.preview_url = secure_url
			p.design.image_url = secure_url
		else:
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
				client = OpenAI().with_options(timeout=60.0)
				import time as _time
				last_err = None
				# Single attempt only; no retries, no Pillow fallback
				res = client.images.generate(model="gpt-image-1-mini", prompt=prm, size="1024x1024")
				b64 = res.data[0].b64_json
				img = b64decode(b64)
				p2 = Product.query.get(pid)
				slug_base = slugify((p2.title if p2 else prm) or "design") or "design"
				# Upload to Cloudinary if configured; otherwise save locally
				cloud_url = current_app.config.get("CLOUDINARY_URL", "").strip()
				if cloud_url:
					import cloudinary.uploader as cu
					# Upload bytes directly
					res_up = cu.upload(img, folder="products", public_id=slug_base, overwrite=True, resource_type="image")
					secure_url = res_up.get("secure_url") or res_up.get("url")
					final_url = secure_url
				else:
					fname = f"{slug_base}_{int(_time.time())}.png"
					upload_dir = os.path.join(os.path.dirname(__file__), "static", "uploads")
					os.makedirs(upload_dir, exist_ok=True)
					path = os.path.join(upload_dir, fname)
					with open(path, "wb") as f:
						f.write(img)
					final_url = f"/static/uploads/{fname}"
				if p2:
					if not p2.design:
						d = Design(type="image", text=p2.title, approved=True)
						db.session.add(d)
						db.session.flush()
						p2.design = d
					p2.design.preview_url = final_url
					p2.design.image_url = final_url
					db.session.commit()
				current_app.logger.info("generate-image completed")
			except Exception as e_all:
				current_app.logger.warning(f"generate-image failed: {e_all}")

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


@admin_bp.post("/gelato/action")
@login_required
def gelato_action():
	client = GelatoClient()
	action = (request.form.get("op") or request.form.get("action") or "").strip()
	result = {}
	error = None
	try:
		if action == "list_products":
			limit = int(request.form.get("limit") or "10")
			result = client.list_products(limit=limit)
		elif action == "get_product":
			uid = (request.form.get("product_uid") or "").strip()
			result = client.get_product(uid)
		elif action == "get_order":
			oid = (request.form.get("order_id") or "").strip()
			result = client.get_order(oid)
		elif action == "shipping_rates":
			# Minimal example payload; adjust as needed
			uid_in = (request.form.get("product_uid") or current_app.config.get("DEFAULT_TEE_UID") or "").strip()
			uid_clean = uid_in[uid_in.find("apparel_product_"):] if ("apparel_product_" in uid_in) else uid_in
			uid_clean = uid_clean.replace(" ", "")
			payload = {
				"items": [
					{
						"productUid": uid_clean,
						"quantity": int(request.form.get("quantity") or "1"),
					}
				],
				"address": {
					"country": request.form.get("country") or "US",
				},
			}
			rates = client.get_shipping_rates(payload)
			result = {"rates": rates}
		elif action == "create_test_order":
			# Build a minimal draft order
			from .models import Address
			addr = Address(
				first_name="Test",
				last_name="User",
				address_line1="1600 Amphitheatre Pkwy",
				city="Mountain View",
				state="CA",
				post_code="94043",
				country="US",
				email="test@example.com",
				phone="5550001111",
			)
			db.session.add(addr)
			db.session.flush()
			uid_in = (request.form.get("product_uid") or current_app.config.get("DEFAULT_TEE_UID") or "").strip()
			uid_clean = uid_in[uid_in.find("apparel_product_"):] if ("apparel_product_" in uid_in) else uid_in
			uid_clean = uid_clean.replace(" ", "")
			payload = {
				"orderType": "order",
				"orderReferenceId": "admin-test",
				"customerReferenceId": "local-tester",
				"currency": current_app.config.get("STORE_CURRENCY", "USD"),
				"shipmentMethodUid": current_app.config.get("DEFAULT_SHIPMENT_METHOD", "express"),
				"items": [
					{
						"itemReferenceId": "admin-1",
						"productUid": uid_clean,
						"files": [
							{"type": "default", "url": request.form.get("file_url") or "https://cdn-origin.gelato-api-dashboard.ie.live.gelato.tech/docs/sample-print-files/logo.png"},
							{"type": "back", "url": request.form.get("file_url") or "https://cdn-origin.gelato-api-dashboard.ie.live.gelato.tech/docs/sample-print-files/logo.png"}
						],
						"quantity": int(request.form.get("quantity") or "1"),
					}
				],
				"shippingAddress": {
					"firstName": addr.first_name,
					"lastName": addr.last_name,
					"addressLine1": addr.address_line1,
					"city": addr.city,
					"state": addr.state,
					"postCode": addr.post_code,
					"country": addr.country,
					"email": addr.email,
					"phone": addr.phone,
				},
				"returnAddress": {
					"companyName": "TrendMerch",
					"addressLine1": "3333 Saint Marys Avenue",
					"addressLine2": "Brooklyn",
					"city": "New York",
					"state": "NY",
					"postCode": "13202",
					"country": "US",
					"email": "apisupport@gelato.com",
					"phone": "123456789"
				},
				"metadata": [
					{"key": "keyIdentifier1", "value": "keyValue1"},
					{"key": "keyIdentifier2", "value": "keyValue2"}
				]
			}
			result = client.create_order(payload)
		else:
			error = "Unknown action"
	except Exception as e:
		error = str(e)

	return jsonify({"ok": error is None, "error": error, "result": result})

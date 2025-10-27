from decimal import Decimal
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_user, logout_user, login_required
from .extensions import db
from .models import Admin, Design, Product, Category, Variant, Trend, Promotion
from .trends import fetch_trending_phrases_any
from .trends_store import load_cache, save_cache
from .gelato_client import GelatoClient
from flask import current_app
from .utils import slugify, normalize_trend_term, send_email_via_sendgrid, render_simple_email, validate_google_jwt_token, extract_google_discount_info
from .phrasegen import generate_candidates_from_title, memeify_term
import os
from werkzeug.utils import secure_filename
import threading
import json
from datetime import datetime, timedelta

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


# --------------
# Auto-mode state
# --------------
def _get_progress_state():
	"""Return (messages_list, lock). Initializes if missing."""
	if "AUTO_MODE_PROGRESS" not in current_app.config:
		current_app.config["AUTO_MODE_PROGRESS"] = []
	if "AUTO_MODE_LOCK" not in current_app.config:
		current_app.config["AUTO_MODE_LOCK"] = threading.Lock()
	return current_app.config["AUTO_MODE_PROGRESS"], current_app.config["AUTO_MODE_LOCK"]


def _progress_add(msg: str) -> None:
	msgs, lock = _get_progress_state()
	try:
		with lock:
			# keep last 100 entries
			stamp = datetime.utcnow().strftime("%H:%M:%S")
			msgs.append(f"[{stamp}] {msg}")
			if len(msgs) > 100:
				del msgs[:-100]
	except Exception:
		pass


def _compose_design_on_blank_tee(design_png_bytes: bytes) -> bytes | None:
	"""Composite the design PNG onto a blank white t-shirt image and return PNG bytes.

	Uses BLANK_TEE_URL from config if set; otherwise falls back to
	`https://dumbshirts.store/static/uploads/2600.png` and finally to local `/static/uploads/2600.png`.
	"""
	try:
		from io import BytesIO as _BytesIO
		from PIL import Image as _Image
		import requests as _req
		# Load base tee image
		base_url = (current_app.config.get("BLANK_TEE_URL") or "").strip() or "https://dumbshirts.store/static/uploads/2600.png"
		base_bytes = None
		if base_url.startswith("http://") or base_url.startswith("https://"):
			resp = _req.get(base_url, timeout=10)
			resp.raise_for_status()
			base_bytes = resp.content
		else:
			fallback_path = os.path.join(os.path.dirname(__file__), "static", "uploads", "2600.png")
			if os.path.exists(fallback_path):
				with open(fallback_path, "rb") as f:
					base_bytes = f.read()
			else:
				return None
		base_img = _Image.open(_BytesIO(base_bytes)).convert("RGBA")
		design_img = _Image.open(_BytesIO(design_png_bytes)).convert("RGBA")
		bw, bh = base_img.size
		# Target box ~35% of base width/height while preserving aspect ratio
		max_w = int(bw * 0.35)
		max_h = int(bh * 0.35)
		dw, dh = design_img.size
		scale = min(max_w / max(dw, 1), max_h / max(dh, 1))
		sw, sh = max(1, int(dw * scale)), max(1, int(dh * scale))
		design_resized = design_img.resize((sw, sh), _Image.LANCZOS)
		# Center placement on chest, then shift up by ~5% of shirt height
		x = (bw - sw) // 2
		y = (bh - sh) // 2 - int(bh * 0.05)
		if y < 0:
			y = 0
		composite = base_img.copy()
		composite.alpha_composite(design_resized, dest=(x, y))
		buf = _BytesIO()
		composite.save(buf, format="PNG")
		return buf.getvalue()
	except Exception as _e:
		current_app.logger.warning(f"[auto-mode] mockup compose failed: {_e}")
		return None


def _remove_bg_hf(png_bytes: bytes) -> bytes | None:
	"""Attempt to remove background via Hugging Face Inference API (briaai/RMBG-1.4).

	Reads token from config HUGGINGFACE_TOKEN or env var. Returns processed bytes on
	success, otherwise None. Non-fatal on failure.
	"""
	try:
		import requests as _req
		token = (current_app.config.get("HUGGINGFACE_TOKEN") or os.getenv("HUGGINGFACE_TOKEN") or "").strip()
		if not token:
			return None
		# New Inference Providers router (2025+)
		url_new = "https://router.huggingface.co/hf-inference/models/briaai/RMBG-1.4"
		r = _req.post(url_new, headers={"Authorization": f"Bearer {token}", "Accept": "image/png"}, data=png_bytes, timeout=45)
		if r.status_code == 200 and r.content:
			return r.content
		# Fallback to legacy endpoint until fully retired
		url_old = "https://api-inference.huggingface.co/models/briaai/RMBG-1.4"
		r2 = _req.post(url_old, headers={"Authorization": f"Bearer {token}", "Accept": "image/png"}, data=png_bytes, timeout=45)
		if r2.status_code == 200 and r2.content:
			current_app.logger.info("[bg-remove] used legacy HF endpoint; consider upgrading base URL")
			return r2.content
		current_app.logger.warning(f"[bg-remove] HF responses new={r.status_code} old={r2.status_code}")
		return None
	except Exception as _e:
		current_app.logger.warning(f"[bg-remove] HF failed: {_e}")
		return None


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


def _auto_mode_generate_from_serpapi(messages: list | None = None, geo: str = "US", generate_images: bool = True) -> int:
	"""Fetch a fresh trend from SerpAPI, de-dupe against DB, generate AI copy + image, and create a draft product.

	Returns number of products created (0 or 1). Writes progress to logger and optional messages list.
	"""
	created = 0
	try:
		# Step 1: Fetch phrases (network I/O). Ask for more at once to reduce extra calls
		phrases, debug = fetch_trending_phrases_any(geo=geo, limit=30)
		current_app.logger.info(f"[auto-mode] fetched {len(phrases)} phrases via {debug.get('source') if isinstance(debug, dict) else 'unknown'}")
		msg0 = f"Fetched {len(phrases)} trends from source: {debug.get('source', 'unknown') if isinstance(debug, dict) else 'unknown'}"
		if messages is not None:
			messages.append(msg0)
		_progress_add(msg0)
		picked_phrase = None
		picked_norm = None
		for phrase in phrases:
			norm = normalize_trend_term(phrase)
			if not norm:
				continue
			if Trend.query.filter_by(normalized=norm).first():
				current_app.logger.info(f"[auto-mode] skip duplicate trend '{phrase}' -> '{norm}'")
				_progress_add(f"Skip duplicate: {phrase}")
				continue
			picked_phrase = phrase
			picked_norm = norm
			break
		if not picked_phrase:
			if messages is not None:
				messages.append("No new trends to add (all were duplicates).")
			return 0

		# Create Trend row
		slug = slugify(picked_phrase) or slugify(picked_norm) or "trend"
		base = slug
		idx = 2
		while Trend.query.filter_by(slug=slug).first():
			slug = f"{base}-{idx}"
			idx += 1
		t = Trend(
			term=picked_phrase,
			normalized=picked_norm,
			slug=slug,
			source=(debug.get("source") if isinstance(debug, dict) else None),
			status="new",
		)
		db.session.add(t)
		db.session.flush()
		current_app.logger.info(f"[auto-mode] created Trend {t.id}:{t.normalized}")
		msg1 = f"New trend: {picked_phrase}"
		if messages is not None:
			messages.append(msg1)
		_progress_add(msg1)

		# Step 2: Generate AI product copy (title, description, price)
		title_out = picked_phrase.strip()
		desc_out = f"Shirt inspired by '{picked_phrase}'."
		from decimal import Decimal as _D
		base_cost = _D("18.00")
		markup_percent = _D(str(current_app.config.get("MARKUP_PERCENT", 35)))
		price_out = (base_cost * (_D(1) + markup_percent / _D(100))).quantize(_D("0.01"))
		api_key = current_app.config.get("OPENAI_API_KEY", "").strip()
		if api_key:
			try:
				import os as _os
				_os.environ["OPENAI_API_KEY"] = api_key
				from openai import OpenAI as _OpenAI
				client = _OpenAI().with_options(timeout=60.0)
				prompt = (
					"You are an e-commerce copywriter for a print-on-demand apparel store. "
					"Given a trend, create concise product copy. Respond ONLY as strict JSON with keys: "
					"title (<=60 chars), description (2 sentences, no emojis/hashtags), price (USD float)."
				)
				messages_chat = [
					{"role": "system", "content": prompt},
					{"role": "user", "content": f"Trend: {picked_phrase}"},
				]
				resp = client.chat.completions.create(
					model="gpt-4o-mini",
					messages=messages_chat,
					response_format={"type": "json_object"},
				)
				content = (resp.choices[0].message.content or "{}").strip()
				import json as _json
				obj = _json.loads(content)
				title_out = (obj.get("title") or title_out).strip()[:60]
				desc_out = (obj.get("description") or desc_out).strip()
				try:
					p_val = _D(str(obj.get("price")))
					if _D("10.00") <= p_val <= _D("60.00"):
						price_out = p_val.quantize(_D("0.01"))
				except Exception:
					pass
				current_app.logger.info("[auto-mode] AI copy generated")
				msg2 = "AI copy generated"
				if messages is not None:
					messages.append(msg2)
				_progress_add(msg2)
			except Exception as e_ai:
				current_app.logger.warning(f"[auto-mode] AI copy generation failed: {e_ai}")
				msg2b = "AI copy failed; using defaults"
				if messages is not None:
					messages.append(msg2b)
				_progress_add(msg2b)
		else:
			msg2c = "OPENAI_API_KEY not set; using default title/description/price"
			if messages is not None:
				messages.append(msg2c)
			_progress_add(msg2c)

		# Step 3: Generate AI image and upload (Cloudinary if configured; else local)
		final_image_url = None
		if not generate_images:
			_progress_add("Image generation skipped by request")
		elif api_key:
			try:
				from base64 import b64decode as _b64d
				from time import time as _time
				from openai import OpenAI as _OpenAI2
				client2 = _OpenAI2().with_options(timeout=60.0)
				img_prompt = (
					f"Minimal bold graphic for a T-shirt inspired by '{picked_phrase}'. "
					"Solid colors only, no gradients, simple icon or bold typography, "
					"transparent background PNG, centered composition."
				)
				res_i = client2.images.generate(model="gpt-image-1-mini", prompt=img_prompt, size="1024x1024")
				b64_data = res_i.data[0].b64_json
				img_bytes = _b64d(b64_data)
				# Try background removal to ensure transparency
				try:
					clean_bytes = _remove_bg_hf(img_bytes)
					if clean_bytes:
						img_bytes = clean_bytes
						_progress_add("Background removed via HF")
				except Exception:
					pass
				cloud_url = current_app.config.get("CLOUDINARY_URL", "").strip()
				if cloud_url:
					import cloudinary.uploader as cu
					public_id = slugify(title_out or picked_phrase or "design")
					res_up_design = cu.upload(img_bytes, folder="products", public_id=public_id + "_design", overwrite=True, resource_type="image")
					secure_design = res_up_design.get("secure_url") or res_up_design.get("url")
					# Compose mockup and upload as secondary
					mock_bytes = _compose_design_on_blank_tee(img_bytes)
					secure_mock = None
					if mock_bytes:
						res_up_mock = cu.upload(mock_bytes, folder="products", public_id=public_id + "_mockup", overwrite=True, resource_type="image")
						secure_mock = res_up_mock.get("secure_url") or res_up_mock.get("url")
					final_image_url = secure_design
					final_mockup_url = secure_mock or secure_design
				else:
					fname = f"auto_{int(_time())}.png"
					upload_dir = os.path.join(os.path.dirname(__file__), "static", "uploads")
					os.makedirs(upload_dir, exist_ok=True)
					path_design = os.path.join(upload_dir, fname)
					with open(path_design, "wb") as f:
						f.write(img_bytes)
					final_image_url = f"/static/uploads/{fname}"
					# Save mockup if we can compose
					mock_bytes = _compose_design_on_blank_tee(img_bytes)
					final_mockup_url = None
					if mock_bytes:
						fname2 = f"auto_mockup_{int(_time())}.png"
						path_mock = os.path.join(upload_dir, fname2)
						with open(path_mock, "wb") as f2:
							f2.write(mock_bytes)
						final_mockup_url = f"/static/uploads/{fname2}"
				i_msg = "AI image generated"
				if messages is not None:
					messages.append(i_msg)
				current_app.logger.info(f"[auto-mode] {i_msg}")
				_progress_add(i_msg)
			except Exception as e_img:
				current_app.logger.warning(f"[auto-mode] AI image generation failed: {e_img}")
				msg3b = "AI image failed; proceeding without image"
				if messages is not None:
					messages.append(msg3b)
				_progress_add(msg3b)
		else:
			msg3c = "OPENAI_API_KEY not set; cannot generate image"
			if messages is not None:
				messages.append(msg3c)
			_progress_add(msg3c)

		# Step 4: Create design and product
		design = Design(type="image", text=picked_phrase, approved=True)
		if final_image_url:
			design.image_url = final_image_url
			# Keep the transparent/raw design as the first extra image for galleries
			design.extra_image1_url = final_image_url
			# Use mockup if present for preview; else use design
			try:
				design.preview_url = final_mockup_url or final_image_url
			except NameError:
				design.preview_url = final_image_url
		db.session.add(design)
		db.session.flush()

		product = _create_product_for_design(design)
		# Override with AI copy/price
		if title_out:
			product.title = title_out
			new_slug = slugify(title_out)
			if new_slug and new_slug != product.slug:
				base = new_slug
				slug2 = base
				idx2 = 2
				from .models import Product as _Product
				while _Product.query.filter(_Product.id != product.id, _Product.slug == slug2).first():
					slug2 = f"{base}-{idx2}"
					idx2 += 1
				product.slug = slug2
		product.description = desc_out
		product.price = price_out
		
		# Step 5: Ensure at least one good variant
		_ensure_single_variant(product)

		# Step 6: Link product <-> trend
		product.trends.append(t)
		db.session.commit()
		created = 1
		msg4 = f"Draft product '{product.title}' created."
		if messages is not None:
			messages.append(msg4)
		_progress_add(msg4)
		current_app.logger.info(f"[auto-mode] linked trend {t.id} -> product {product.id}")
	except Exception as e_all:
		current_app.logger.warning(f"[auto-mode] flow failed: {e_all}")
		msgF = f"Auto-mode failed: {e_all}"
		if messages is not None:
			messages.append(msgF)
		_progress_add(msgF)
		# Best-effort rollback of partial transaction
		try:
			db.session.rollback()
		except Exception:
			pass
	return created


@admin_bp.post("/auto-mode/toggle")
@login_required
def toggle_auto_mode():
	current = bool(current_app.config.get("AUTO_MODE", False))
	new_state = not current
	current_app.config["AUTO_MODE"] = new_state
	if new_state:
		# Kick work to background to avoid router 30s timeout
		# Reset progress for a clean session
		msgs, lock = _get_progress_state()
		with lock:
			msgs.clear()
		_progress_add("Auto mode starting…")
		flash("Auto mode ON. Working in background…", "success")
		# Respect checkboxes
		skip_images = (request.form.get("skip_images") == "1")
		continuous = (request.form.get("continuous") == "1")
		# Persist choices so UI can reflect state
		current_app.config["AUTO_MODE_SKIP_IMAGES"] = skip_images
		current_app.config["AUTO_MODE_CONTINUOUS"] = continuous
		def _run(app_ctx):
			with app_ctx:
				try:
					from time import sleep as _sleep
					iterations = 2 if continuous else 1
					_progress_add(f"Mode: {'continuous' if continuous else 'single'} ({iterations} run(s))")
					total_created = 0
					for i in range(iterations):
						steps = []
						created = _auto_mode_generate_from_serpapi(messages=steps, geo="US", generate_images=(not skip_images))
						for m in steps:
							_progress_add(m)
						total_created += created
						_progress_add(f"Run {i+1}/{iterations} imported {created} product(s).")
						# If nothing created, don't delay too long; break early
						if created == 0 and not continuous:
							break
						if i < iterations - 1:
							_sleep(1.0)
					_progress_add(f"Imported {total_created} product(s) total.")
				except Exception as e_bg:
					_progress_add(f"Auto mode failed: {e_bg}")
		thr = threading.Thread(target=_run, args=(current_app.app_context(),), daemon=True)
		thr.start()
	else:
		flash("Auto mode OFF.", "success")
	return redirect(url_for("admin.products_list"))


@admin_bp.get("/auto-mode/status")
@login_required
def auto_mode_status():
	msgs, _ = _get_progress_state()
	ordered = list(reversed(msgs[-50:]))
	seq = len(msgs)
	last_message = ordered[0] if ordered else ""
	return jsonify({
		"enabled": bool(current_app.config.get("AUTO_MODE", False)),
		"messages": ordered,
		"seq": seq,
		"last_message": last_message,
		"skip_images": bool(current_app.config.get("AUTO_MODE_SKIP_IMAGES", False)),
		"continuous": bool(current_app.config.get("AUTO_MODE_CONTINUOUS", False)),
	})

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
			for color in ["White", "Black", "Heather", "Red", "Blue"]:
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
	msgs, _ = _get_progress_state()
	enabled = bool(current_app.config.get("AUTO_MODE", False))
	skip_images = bool(current_app.config.get("AUTO_MODE_SKIP_IMAGES", False))
	continuous = bool(current_app.config.get("AUTO_MODE_CONTINUOUS", False))
	return render_template(
		"admin_products.html",
		products=products,
		auto_mode_progress=list(reversed(msgs[-10:])),
		auto_mode_enabled=enabled,
		auto_mode_skip_images=skip_images,
		auto_mode_continuous=continuous,
	)


@admin_bp.post("/products/<int:product_id>/toggle")
@login_required
def toggle_product_visibility(product_id: int):
	p = Product.query.get_or_404(product_id)
	p.status = "draft" if p.status == "active" else "active"
	db.session.commit()
	flash("Visibility updated", "success")
	return redirect(url_for("admin.products_list"))


@admin_bp.post("/products/new")
@login_required
def create_blank_product():
    """Create a draft product with minimal defaults and redirect to edit page."""
    title = "New Product"
    base_slug = slugify(title) or "product"
    slug = base_slug
    idx = 2
    while Product.query.filter_by(slug=slug).first():
        slug = f"{base_slug}-{idx}"
        idx += 1

    p = Product(
        slug=slug,
        title=title,
        description="",
        status="draft",
        base_cost=Decimal("0.00"),
        price=Decimal("0.00"),
        currency=current_app.config.get("STORE_CURRENCY", "USD"),
    )
    db.session.add(p)
    db.session.commit()
    # Ensure at least one variant exists for editing/preview flows
    _ensure_single_variant(p)
    db.session.commit()
    flash("Draft product created", "success")
    return redirect(url_for("admin.edit_product_page", product_id=p.id))


@admin_bp.post("/products/<int:product_id>/publish")
@login_required
def publish_product(product_id: int):
	p = Product.query.get_or_404(product_id)
	p.status = "active"
	db.session.commit()
	flash("Product published", "success")
	# Optional: test email send to admin if configured via env ADMIN_EMAIL
	try:
		to = (current_app.config.get("ADMIN_EMAIL") or os.getenv("ADMIN_EMAIL") or "").strip()
		if to:
			html = render_simple_email("Product Published", [f"'{p.title}' is now live."])
			send_email_via_sendgrid(to, "Product published", html)
	except Exception:
		pass
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
	use_formula = request.form.get("use_formula") == "1"
	base_cost_in = (request.form.get("base_cost") or "").strip()
	price_in = (request.form.get("price") or "").strip()
	image_file = request.files.get("image")
	extra1 = request.files.get("extra_image1")
	extra2 = request.files.get("extra_image2")

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

	# Pricing updates
	try:
		if base_cost_in:
			p.base_cost = Decimal(str(base_cost_in)).quantize(Decimal("0.01"))
		# Apply pricing formula if requested; otherwise use provided price if any
		if use_formula:
			markup_percent = Decimal(str(current_app.config.get("MARKUP_PERCENT", 35)))
			p.price = (Decimal(p.base_cost) * (Decimal(1) + markup_percent / Decimal(100))).quantize(Decimal("0.01"))
		elif price_in:
			p.price = Decimal(str(price_in)).quantize(Decimal("0.01"))
	except Exception:
		# Silently ignore bad inputs; keep previous values
		pass

	uploaded = False
	# Handle image upload
	if image_file and image_file.filename:
		# Read bytes once to compose mockup and upload
		file_bytes = image_file.read()
		# Try removing background for uploaded images
		try:
			clean = _remove_bg_hf(file_bytes)
			if clean:
				file_bytes = clean
				current_app.logger.info("[bg-remove] Applied on admin upload")
		except Exception:
			pass
		try:
			image_file.stream.seek(0)
		except Exception:
			pass
		mock_bytes = _compose_design_on_blank_tee(file_bytes) if file_bytes else None
		# Upload to Cloudinary if configured; fallback to local
		cloud_url = current_app.config.get("CLOUDINARY_URL", "").strip()
		if cloud_url:
			import cloudinary.uploader as cu
			public_id = slugify(p.title or "design") or "design"
			# Upload raw design
			res_design = cu.upload(file_bytes, folder="products", public_id=public_id + "_design", overwrite=True, resource_type="image")
			design_url = res_design.get("secure_url") or res_design.get("url")
			# Upload mockup if composed; otherwise reuse design
			if mock_bytes:
				res_mock = cu.upload(mock_bytes, folder="products", public_id=public_id + "_mockup", overwrite=True, resource_type="image")
				mock_url = res_mock.get("secure_url") or res_mock.get("url")
			else:
				mock_url = design_url
			p.design.image_url = design_url
			p.design.preview_url = mock_url
			p.design.extra_image1_url = design_url
		else:
			fname = secure_filename(image_file.filename)
			upload_dir = os.path.join(os.path.dirname(__file__), "static", "uploads")
			os.makedirs(upload_dir, exist_ok=True)
			path_design = os.path.join(upload_dir, fname)
			with open(path_design, "wb") as f:
				f.write(file_bytes)
			design_url = f"/static/uploads/{fname}"
			# Save mockup if composed
			if mock_bytes:
				fname2 = f"mockup_{secure_filename(os.path.splitext(fname)[0])}.png"
				path_mock = os.path.join(upload_dir, fname2)
				with open(path_mock, "wb") as f2:
					f2.write(mock_bytes)
				mock_url = f"/static/uploads/{fname2}"
			else:
				mock_url = design_url
			p.design.image_url = design_url
			p.design.preview_url = mock_url
			p.design.extra_image1_url = design_url
		uploaded = True

	# Handle extra images upload
	if (extra1 and extra1.filename) or (extra2 and extra2.filename):
		# Ensure design exists
		if not p.design:
			d = Design(type="image", text=p.title, approved=True)
			db.session.add(d)
			db.session.flush()
			p.design = d
		cloud_url = current_app.config.get("CLOUDINARY_URL", "").strip()
		def _save_extra(file_obj):
			if not file_obj or not file_obj.filename:
				return None
			if cloud_url:
				import cloudinary.uploader as cu
				public_id = slugify(p.title or "design") + "_extra"
				res = cu.upload(file_obj, folder="products", public_id=public_id + '_' + (file_obj.filename or 'x'), overwrite=True, resource_type="image")
				return res.get("secure_url") or res.get("url")
			else:
				fname = secure_filename(file_obj.filename)
				upload_dir = os.path.join(os.path.dirname(__file__), "static", "uploads")
				os.makedirs(upload_dir, exist_ok=True)
				path = os.path.join(upload_dir, fname)
				file_obj.save(path)
				return f"/static/uploads/{fname}"
		url1 = _save_extra(extra1)
		url2 = _save_extra(extra2)
		if url1:
			p.design.extra_image1_url = url1
		if url2:
			p.design.extra_image2_url = url2

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
				# Try background removal
				try:
					clean = _remove_bg_hf(img)
					if clean:
						img = clean
						current_app.logger.info("[bg-remove] Applied on-demand image")
				except Exception:
					pass
				p2 = Product.query.get(pid)
				slug_base = slugify((p2.title if p2 else prm) or "design") or "design"
				# Upload to Cloudinary if configured; otherwise save locally
				cloud_url = current_app.config.get("CLOUDINARY_URL", "").strip()
				if cloud_url:
					import cloudinary.uploader as cu
					# Upload bytes directly (design)
					res_up_design = cu.upload(img, folder="products", public_id=slug_base + "_design", overwrite=True, resource_type="image")
					design_url = res_up_design.get("secure_url") or res_up_design.get("url")
					# Compose mockup
					mock_bytes = _compose_design_on_blank_tee(img)
					if mock_bytes:
						res_up_mock = cu.upload(mock_bytes, folder="products", public_id=slug_base + "_mockup", overwrite=True, resource_type="image")
						final_url = res_up_mock.get("secure_url") or res_up_mock.get("url")
					else:
						final_url = design_url
				else:
					fname = f"{slug_base}_{int(_time.time())}.png"
					upload_dir = os.path.join(os.path.dirname(__file__), "static", "uploads")
					os.makedirs(upload_dir, exist_ok=True)
					path_design = os.path.join(upload_dir, fname)
					with open(path_design, "wb") as f:
						f.write(img)
					design_url = f"/static/uploads/{fname}"
					mock_bytes = _compose_design_on_blank_tee(img)
					if mock_bytes:
						fname_m = f"{slug_base}_mockup_{int(_time.time())}.png"
						path_m = os.path.join(upload_dir, fname_m)
						with open(path_m, "wb") as fm:
							fm.write(mock_bytes)
						final_url = f"/static/uploads/{fname_m}"
					else:
						final_url = design_url
				if p2:
					if not p2.design:
						d = Design(type="image", text=p2.title, approved=True)
						db.session.add(d)
						db.session.flush()
						p2.design = d
					p2.design.preview_url = final_url
					p2.design.image_url = design_url
					p2.design.extra_image1_url = design_url
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


# -----------------------------
# Admin: Google Shopping Feeds
# -----------------------------

def _data_dir() -> str:
	return os.path.join(os.path.dirname(__file__), "data")


def _ensure_data_dir() -> None:
	os.makedirs(_data_dir(), exist_ok=True)


def _data_path(name: str) -> str:
	return os.path.join(_data_dir(), name)


def _normalize_promotion_id(raw: str) -> str:
	"""Allow only A–Z, a–z, 0–9, dash and underscore; convert spaces to underscore and trim to 50 chars."""
	if not raw:
		return ""
	builder = []
	for ch in raw.strip():
		c = "_" if ch == " " else ch
		if c.isalnum() or c in ("-", "_"):
			builder.append(c)
	return "".join(builder)[:50]


def _load_json_list(path: str) -> list:
	try:
		with open(path, "r", encoding="utf-8") as f:
			data = json.load(f)
			return data if isinstance(data, list) else []
	except FileNotFoundError:
		return []
	except Exception:
		return []


def _save_json_list(path: str, rows: list) -> None:
	_ensure_data_dir()
	with open(path, "w", encoding="utf-8") as f:
		json.dump(rows, f, ensure_ascii=False, indent=2)


@admin_bp.get("/feeds/promotions")
@login_required
def manage_promotions():
	try:
		rows = Promotion.query.order_by(Promotion.created_at.desc()).all()
	except Exception as _e:
		current_app.logger.warning(f"[promotions] DB not ready or table missing: {_e}")
		rows = []
	# Default dates: start in 2 days, end in ~1 month; display starts tomorrow
	today = datetime.utcnow().date()
	defaults = {
		"start_date": (today + timedelta(days=2)).isoformat(),
		"end_date": (today + timedelta(days=30)).isoformat(),
		"display_start_date": (today + timedelta(days=1)).isoformat(),
		"display_end_date": (today + timedelta(days=30)).isoformat(),
	}
	return render_template("admin_promotions.html", promotions=rows, defaults=defaults)


@admin_bp.post("/feeds/promotions/add")
@login_required
def add_promotion():
	# Gather fields (persist to DB)
	raw_id = (request.form.get("promotion_id") or "").strip()
	promo_id = _normalize_promotion_id(raw_id) or f"PROMO-{int(datetime.utcnow().timestamp())}"
	row = Promotion.query.filter_by(promotion_id=promo_id).first()
	if not row:
		row = Promotion(promotion_id=promo_id)
		db.session.add(row)
	row.long_title = (request.form.get("long_title") or "").strip()
	row.generic_redemption_code = (request.form.get("generic_redemption_code") or "").strip()
	row.percent_off = (request.form.get("percent_off") or "").strip()
	row.start_date = (request.form.get("start_date") or "").strip()
	row.end_date = (request.form.get("end_date") or "").strip()
	row.display_start_date = (request.form.get("display_start_date") or "").strip()
	row.display_end_date = (request.form.get("display_end_date") or "").strip()
	row.promotion_url = (request.form.get("promotion_url") or "").strip()
	db.session.commit()
	flash("Promotion saved", "success")
	return redirect(url_for("admin.manage_promotions"))


@admin_bp.post("/feeds/promotions/<string:promotion_id>/delete")
@login_required
def delete_promotion(promotion_id: str):
	row = Promotion.query.filter_by(promotion_id=str(promotion_id)).first()
	if row:
		db.session.delete(row)
		db.session.commit()
	flash("Promotion deleted", "success")
	return redirect(url_for("admin.manage_promotions"))


@admin_bp.get("/feeds/promotions/<string:promotion_id>/edit")
@login_required
def edit_promotion_page(promotion_id: str):
	row = Promotion.query.filter_by(promotion_id=str(promotion_id)).first()
	if not row:
		flash("Promotion not found", "error")
		return redirect(url_for("admin.manage_promotions"))
	return render_template("admin_promotion_edit.html", promotion=row)


@admin_bp.post("/feeds/promotions/<string:promotion_id>/edit")
@login_required
def edit_promotion_submit(promotion_id: str):
	row = Promotion.query.filter_by(promotion_id=str(promotion_id)).first()
	if not row:
		flash("Promotion not found", "error")
		return redirect(url_for("admin.manage_promotions"))
	# Allow changing ID with normalization; otherwise keep existing
	if request.form.get("promotion_id"):
		new_id = _normalize_promotion_id(request.form.get("promotion_id"))
		if new_id:
			row.promotion_id = new_id
	row.long_title = (request.form.get("long_title") or "").strip()
	row.percent_off = (request.form.get("percent_off") or "").strip()
	row.start_date = (request.form.get("start_date") or "").strip()
	row.end_date = (request.form.get("end_date") or "").strip()
	row.display_start_date = (request.form.get("display_start_date") or "").strip()
	row.display_end_date = (request.form.get("display_end_date") or "").strip()
	row.promotion_url = (request.form.get("promotion_url") or "").strip()
	# Destinations (comma-separated)
	dests_raw = (request.form.get("promotion_destination") or "").strip()
	if dests_raw:
		row.promotion_destination = ",".join([s.strip() for s in dests_raw.split(",") if s.strip()])
	# Redemption channel
	if request.form.get("redemption_channel"):
		row.redemption_channel = request.form.get("redemption_channel").strip()
	db.session.commit()
	flash("Promotion updated", "success")
	return redirect(url_for("admin.manage_promotions"))


@admin_bp.get("/feeds/reviews")
@login_required
def manage_reviews():
	path = _data_path("reviews.json")
	reviews = _load_json_list(path)
	# Sort newest first by created_at if present
	try:
		reviews.sort(key=lambda r: r.get("created_at", ""), reverse=True)
	except Exception:
		pass
	products = Product.query.order_by(Product.created_at.desc()).all()
	return render_template("admin_reviews.html", reviews=reviews, products=products)


@admin_bp.post("/feeds/reviews/add")
@login_required
def add_review():
	path = _data_path("reviews.json")
	reviews = _load_json_list(path)
	try:
		rating_val = int((request.form.get("rating") or "").strip() or "5")
		if rating_val < 1 or rating_val > 5:
			rating_val = 5
	except Exception:
		rating_val = 5
	review_id = f"R-{int(datetime.utcnow().timestamp())}"
	entry = {
		"review_id": review_id,
		"product_id": (request.form.get("product_id") or "").strip(),
		"title": (request.form.get("title") or "").strip(),
		"content": (request.form.get("content") or "").strip(),
		"reviewer_name": (request.form.get("reviewer_name") or "").strip(),
		"review_url": (request.form.get("review_url") or "").strip(),
		"rating": rating_val,
		"created_at": datetime.utcnow().isoformat() + "Z",
	}
	reviews.append(entry)
	_save_json_list(path, reviews)
	flash("Review added", "success")
	return redirect(url_for("admin.manage_reviews"))


@admin_bp.post("/feeds/reviews/<string:review_id>/delete")
@login_required
def delete_review(review_id: str):
	path = _data_path("reviews.json")
	reviews = _load_json_list(path)
	reviews = [r for r in reviews if str(r.get("review_id")) != str(review_id)]
	_save_json_list(path, reviews)
	flash("Review deleted", "success")
	return redirect(url_for("admin.manage_reviews"))


@admin_bp.get("/test-google-jwt")
@login_required
def test_google_jwt():
	"""Test Google JWT validation functionality."""
	return render_template("admin_test_jwt.html")


@admin_bp.post("/test-google-jwt")
@login_required
def test_google_jwt_submit():
	"""Test Google JWT validation with provided token."""
	token = request.form.get("token", "").strip()
	merchant_id = current_app.config.get("GOOGLE_MERCHANT_ID", "114634997")
	
	result = {"success": False, "message": "", "payload": None, "discount_info": None}
	
	if not token:
		result["message"] = "Please provide a JWT token"
	else:
		try:
			payload = validate_google_jwt_token(token, merchant_id)
			if payload:
				result["success"] = True
				result["message"] = "Token validation successful!"
				result["payload"] = payload
				result["discount_info"] = extract_google_discount_info(payload)
			else:
				result["message"] = "Token validation failed - invalid token or expired"
		except Exception as e:
			result["message"] = f"Error validating token: {str(e)}"
	
	return render_template("admin_test_jwt.html", result=result)

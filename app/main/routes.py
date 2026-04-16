from flask import render_template, current_app, request, abort, session, Response, jsonify, redirect, url_for
from werkzeug.utils import secure_filename
import os
import json
import hashlib
import requests
import threading
import time
from . import main_bp
from ..models import Product, Category, Variant, Trend
from decimal import Decimal
from ..models import Order, Address
from urllib.parse import urljoin
from datetime import datetime
from ..gelato_client import GelatoClient
from datetime import timedelta
from xml.sax.saxutils import escape as xml_escape
from ..utils import send_email_via_sendgrid, render_simple_email, validate_google_jwt_token, extract_google_discount_info, is_google_discount_valid
from ..extensions import db


@main_bp.get("/")
def index():
	page = request.args.get("page", 1, type=int)
	per_page = 15
	
	products_query = Product.query.filter_by(status="active").order_by(Product.created_at.desc())
	products_pagination = products_query.paginate(
		page=page, per_page=per_page, error_out=False
	)
	
	# Fetch 5 random active products for hero slideshow
	import random
	all_active = Product.query.filter_by(status="active").all()
	hero_products = random.sample(all_active, min(5, len(all_active))) if len(all_active) >= 5 else all_active
	
	return render_template("index.html", 
		products=products_pagination.items,
		pagination=products_pagination,
		current_page=page,
		hero_products=hero_products
	)


@main_bp.before_app_request
def capture_referral():
	"""Capture referral code from ?ref=CODE and stash in session."""
	try:
		code = (request.args.get("ref") or "").strip()
		if code:
			session["ref"] = code[:50]
			session.modified = True
	except Exception:
		pass


@main_bp.get("/shop")
def shop():
	# Filters
	cat_slug = request.args.get("cat", "").strip()
	sort = request.args.get("sort", "newest").strip()
	min_price = request.args.get("min", "").strip()
	max_price = request.args.get("max", "").strip()
	page = request.args.get("page", 1, type=int)
	per_page = 12

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

	products_pagination = q.paginate(
		page=page, per_page=per_page, error_out=False
	)
	categories = Category.query.order_by(Category.name.asc()).all()
	return render_template(
		"shop.html",
		products=products_pagination.items,
		pagination=products_pagination,
		categories=categories,
		selected_cat=cat_slug,
		sort=sort,
		min_price=min_price,
		max_price=max_price,
		current_page=page,
	)


def _render_category_page(category_name: str, category_slug: str, category_description: str, category_keywords: str):
	"""Helper function to render category pages with pagination and SEO data"""
	import random
	page = request.args.get("page", 1, type=int)
	per_page = 24
	
	# Get all active products, randomized per page
	all_active = list(Product.query.filter_by(status="active").all())
	random.shuffle(all_active)
	
	# Paginate manually (simple approach)
	start_idx = (page - 1) * per_page
	end_idx = start_idx + per_page
	products = all_active[start_idx:end_idx]
	
	# Create pagination object-like structure
	total = len(all_active)
	total_pages = (total + per_page - 1) // per_page if total > 0 else 0
	
	class SimplePagination:
		def __init__(self, page, per_page, total):
			self.page = page
			self.per_page = per_page
			self.total = total
			self.pages = total_pages
			self.has_prev = page > 1
			self.has_next = page < total_pages
			self.prev_num = page - 1 if self.has_prev else None
			self.next_num = page + 1 if self.has_next else None
			
		def iter_pages(self, left_edge=2, right_edge=2, left_current=2, right_current=2):
			last = self.pages
			for num in range(1, last + 1):
				if num <= left_edge or (num > self.page - left_current - 1 and num < self.page + right_current) or num > last - right_edge:
					yield num
	
	pagination = SimplePagination(page, per_page, total) if total_pages > 0 else None
	category_title = f"{category_name} | Roast Cotton"
	
	return render_template("category.html",
		products=products,
		pagination=pagination,
		current_page=page,
		category_name=category_name,
		category_slug=category_slug,
		category_title=category_title,
		category_description=category_description,
		category_keywords=category_keywords
	)


@main_bp.get("/funny-tshirts")
def funny_tshirts():
	"""Category page for funny t-shirts - SEO focused"""
	return _render_category_page(
		category_name="Funny T-Shirts",
		category_slug="funny-tshirts",
		category_description="Shop our collection of funny t-shirts. Discover hilarious, witty, and entertaining t-shirt designs that bring humor to your wardrobe. Free shipping",
		category_keywords="funny t-shirts, funny shirts, humorous t-shirts, comedy tees, joke t-shirts, witty t-shirts"
	)


@main_bp.get("/meme-tshirts")
def meme_tshirts():
	"""Category page for meme t-shirts - SEO focused"""
	return _render_category_page(
		category_name="Meme T-Shirts",
		category_slug="meme-tshirts",
		category_description="Browse our selection of meme t-shirts. From viral internet memes to classic pop culture references, find the perfect meme-inspired t-shirt to express your personality.",
		category_keywords="meme t-shirts, meme shirts, internet meme tees, viral meme t-shirts, meme culture t-shirts, trending meme designs"
	)


@main_bp.get("/sarcastic-tshirts")
def sarcastic_tshirts():
	"""Category page for sarcastic t-shirts - SEO focused"""
	return _render_category_page(
		category_name="Sarcastic T-Shirts",
		category_slug="sarcastic-tshirts",
		category_description="Express your sharp wit with our collection of sarcastic t-shirts. Perfect for those who appreciate dry humor and clever comebacks. Stand out with designs that speak your mind in style.",
		category_keywords="sarcastic t-shirts, sarcastic shirts, witty sarcastic tees, dry humor t-shirts, sassy t-shirts, clever comeback shirts"
	)


@main_bp.get("/witty-shirts")
def witty_shirts():
	"""Category page for witty shirts - SEO focused"""
	return _render_category_page(
		category_name="Witty Shirts",
		category_slug="witty-shirts",
		category_description="Show off your intelligence and sense of humor with our witty t-shirt collection. Featuring clever wordplay, smart observations, and intellectually humorous designs that make people think and laugh.",
		category_keywords="witty shirts, witty t-shirts, clever t-shirts, smart humor shirts, intellectual humor tees, witty wordplay shirts"
	)


@main_bp.get("/funny-saying-tshirts")
def funny_saying_tshirts():
	"""Category page for funny saying t-shirts - SEO focused"""
	return _render_category_page(
		category_name="Funny Saying T-Shirts",
		category_slug="funny-saying-tshirts",
		category_description="Browse our collection of funny saying t-shirts featuring hilarious quotes, catchphrases, and memorable one-liners. Perfect for expressing your personality and making people laugh wherever you go.",
		category_keywords="funny saying t-shirts, quote t-shirts, funny quote shirts, catchphrase t-shirts, one-liner shirts, humorous quote tees"
	)


@main_bp.get("/pun-shirts")
def pun_shirts():
	"""Category page for pun shirts - SEO focused"""
	return _render_category_page(
		category_name="Pun Shirts",
		category_slug="pun-shirts",
		category_description="Get ready to groan and giggle with our pun t-shirt collection! Featuring clever wordplay, pun-tastic designs, and humor that's so bad it's good. Perfect for pun lovers and anyone who appreciates a good play on words.",
		category_keywords="pun shirts, pun t-shirts, wordplay t-shirts, punny shirts, clever pun tees, dad joke pun shirts, pun humor t-shirts"
	)


@main_bp.get("/dad-joke-shirts")
def dad_joke_shirts():
	"""Category page for dad joke shirts - SEO focused"""
	return _render_category_page(
		category_name="Dad Joke Shirts",
		category_slug="dad-joke-shirts",
		category_description="Embrace the dad joke aesthetic with our collection of dad joke t-shirts. Featuring classic dad humor, cheesy jokes, and puns that are so corny they're charming. Perfect for dads, dads-to-be, and anyone who loves wholesome humor.",
		category_keywords="dad joke shirts, dad joke t-shirts, dad humor shirts, cheesy joke tees, dad pun shirts, wholesome humor t-shirts, dad joke merchandise"
	)


@main_bp.get("/black-friday")
def black_friday():
	"""Black Friday sale page - SEO focused"""
	return _render_category_page(
		category_name="Black Friday Deals",
		category_slug="black-friday",
		category_description="Shop our Black Friday sale! Huge discounts on funny t-shirts, meme shirts, and all your favorite designs. Limited time offers on trending designs. Free shipping available.",
		category_keywords="black friday, black friday deals, black friday t-shirts, black friday sale, black friday shirts, black friday 2025, funny t-shirts sale, meme t-shirts sale"
	)


@main_bp.get("/christmas-shirts")
def christmas_shirts():
	"""Category page for Christmas shirts - SEO focused"""
	return _render_category_page(
		category_name="Christmas Shirts",
		category_slug="christmas-shirts",
		category_description="Get into the holiday spirit with our collection of Christmas t-shirts! Featuring festive designs, funny holiday jokes, and festive themes perfect for celebrating the season. Spread Christmas cheer with unique and humorous holiday-themed shirts.",
		category_keywords="christmas shirts, christmas t-shirts, holiday shirts, christmas tees, festive t-shirts, holiday humor shirts, christmas joke shirts, holiday themed shirts"
	)


@main_bp.get("/weird-shirts")
def weird_shirts():
	"""Category page for weird shirts - SEO focused"""
	return _render_category_page(
		category_name="Weird Shirts",
		category_slug="weird-shirts",
		category_description="Discover our collection of weird and unusual t-shirts! Featuring bizarre designs, odd humor, and unconventional styles for those who love to stand out. Find unique and quirky t-shirts that break the mold.",
		category_keywords="weird shirts, weird t-shirts, unusual shirts, quirky t-shirts, bizarre shirts, odd t-shirts, unconventional shirts, strange t-shirts"
	)


@main_bp.get("/search")
def search():
	q = request.args.get("q", "").strip()
	if not q:
		q = "meme"
	results = []
	# Recent approved trends for bubbles
	trend_bubbles = Trend.query.filter_by(status="approved").order_by(Trend.created_at.desc()).limit(10).all()
	if q:
		# Split query into words for fuzzy matching
		query_words = q.lower().split()
		
		# Build a filter that matches if ANY word from the query appears in title or description
		from sqlalchemy import or_
		conditions = []
		
		for word in query_words:
			# Match word as substring (handles plurals: "cats" will match "cat" in "nyan cat")
			word_pattern = f"%{word}%"
			conditions.append(Product.title.ilike(word_pattern))
			conditions.append(Product.description.ilike(word_pattern))
			
			# Also try singular/plural variations for better matching
			# If word ends with 's', try without it (cats -> cat)
			if word.endswith('s') and len(word) > 1:
				singular_word = word[:-1]
				singular_pattern = f"%{singular_word}%"
				conditions.append(Product.title.ilike(singular_pattern))
				conditions.append(Product.description.ilike(singular_pattern))
			# If word doesn't end with 's', try with 's' (cat -> cats)
			elif not word.endswith('s'):
				plural_word = f"{word}s"
				plural_pattern = f"%{plural_word}%"
				conditions.append(Product.title.ilike(plural_pattern))
				conditions.append(Product.description.ilike(plural_pattern))
		
		# Combine all conditions with OR (matches if any word matches)
		# Also include the full query as a substring match for exact phrase matching
		full_query_pattern = f"%{q}%"
		conditions.append(Product.title.ilike(full_query_pattern))
		conditions.append(Product.description.ilike(full_query_pattern))
		
		results = Product.query.filter(Product.status == "active").filter(
			or_(*conditions)
		).order_by(Product.created_at.desc()).all()
	return render_template("search.html", q=q, results=results, trend_bubbles=trend_bubbles)


@main_bp.get("/personalized-t-shirt-printing-design-your-own-custom-photo-shirt")
def custom_shirt():
	"""Custom shirt design page where users can upload or generate their own design."""
	# Track OpenAI generations in session (limit to 2)
	generation_count = session.get("custom_shirt_generations", 0)
	# Check for accepted design in session
	accepted_design = session.get("custom_shirt_accepted", {})
	return render_template("custom_shirt.html", 
		generation_count=generation_count, 
		max_generations=2,
		accepted_design=accepted_design)


@main_bp.post("/custom-shirt/upload-image")
def custom_shirt_upload():
	"""Upload a custom image for custom shirt design."""
	from io import BytesIO
	from PIL import Image
	import cloudinary.uploader as cu
	
	if "image" not in request.files:
		return jsonify({"error": "No image file provided"}), 400
	
	file = request.files["image"]
	if file.filename == "":
		return jsonify({"error": "No file selected"}), 400
	
	try:
		# Read and validate image
		file_bytes = file.read()
		if len(file_bytes) == 0:
			return jsonify({"error": "Empty file"}), 400
		
		# Validate it's an image
		img = Image.open(BytesIO(file_bytes))
		img.verify()
		
		# Reopen for processing (verify closes the file)
		img = Image.open(BytesIO(file_bytes))
		img = img.convert("RGBA")
		
		# Save to BytesIO
		buf = BytesIO()
		img.save(buf, format="PNG")
		img_bytes = buf.getvalue()
		
		# Upload to Cloudinary
		cloud_url = current_app.config.get("CLOUDINARY_URL", "").strip()
		if cloud_url:
			import time
			public_id = f"custom_shirt_{int(time.time())}_{hashlib.md5(img_bytes[:1000]).hexdigest()[:8]}"
			res = cu.upload(img_bytes, folder="custom_shirts", public_id=public_id, overwrite=True, resource_type="image")
			design_url = res.get("secure_url") or res.get("url")
			
			# Generate mockup
			from ..admin import _compose_design_on_blank_tee
			mockup_bytes = _compose_design_on_blank_tee(img_bytes)
			if mockup_bytes:
				mockup_public_id = f"{public_id}_mockup"
				mockup_res = cu.upload(mockup_bytes, folder="custom_shirts", public_id=mockup_public_id, overwrite=True, resource_type="image")
				mockup_url = mockup_res.get("secure_url") or mockup_res.get("url")
			else:
				mockup_url = design_url
			
			return jsonify({
				"success": True,
				"design_url": design_url,
				"mockup_url": mockup_url
			})
		else:
			return jsonify({"error": "Cloudinary not configured"}), 500
	except Exception as e:
		current_app.logger.error(f"Custom shirt upload error: {e}")
		return jsonify({"error": str(e)}), 500


def _get_custom_shirt_jobs():
	"""Return (jobs_dict, lock). Initializes if missing."""
	if "CUSTOM_SHIRT_JOBS" not in current_app.config:
		current_app.config["CUSTOM_SHIRT_JOBS"] = {}
	if "CUSTOM_SHIRT_LOCK" not in current_app.config:
		current_app.config["CUSTOM_SHIRT_LOCK"] = threading.Lock()
	return current_app.config["CUSTOM_SHIRT_JOBS"], current_app.config["CUSTOM_SHIRT_LOCK"]


@main_bp.post("/custom-shirt/generate-image")
def custom_shirt_generate():
	"""Generate an image using OpenAI for custom shirt design (runs in background to avoid timeout)."""
	prompt = (request.json or {}).get("prompt", "").strip()
	if not prompt:
		return jsonify({"error": "Missing prompt"}), 400
	
	# Check generation limit (2 per session)
	generation_count = session.get("custom_shirt_generations", 0)
	if generation_count >= 2:
		return jsonify({"error": "Maximum 2 generations per session. Please refresh the page to reset."}), 400
	
	api_key = current_app.config.get("OPENAI_API_KEY", "")
	if not api_key:
		return jsonify({"error": "Image generation is currently unavailable"}), 500
	
	# Create unique job ID for this generation
	job_id = f"custom_{int(time.time())}_{hashlib.md5((prompt + str(time.time())).encode()).hexdigest()[:8]}"
	
	# Initialize job status in memory cache (thread-safe)
	jobs, lock = _get_custom_shirt_jobs()
	with lock:
		jobs[job_id] = {"status": "processing", "error": None}
	
	# Run in background thread to avoid 30s Heroku router timeout
	def _worker(app_ctx, job_id_inner: str, prompt_inner: str, gen_count: int):
		with app_ctx:
			try:
				from base64 import b64decode
				import cloudinary.uploader as cu
				from ..admin import _remove_bg_hf, _compose_design_on_blank_tee
				
				import os as _os
				_os.environ["OPENAI_API_KEY"] = api_key
				from openai import OpenAI
				client = OpenAI().with_options(timeout=60.0)
				
				current_app.logger.info(f"[custom-shirt] Starting generation for job {job_id_inner}")
				
				# Enhance prompt to always request transparent background
				enhanced_prompt = prompt_inner
				transparent_keywords = ["transparent background", "transparent bg", "no background", "transparent", "on transparent"]
				has_transparent = any(kw.lower() in enhanced_prompt.lower() for kw in transparent_keywords)
				if not has_transparent:
					enhanced_prompt = f"{enhanced_prompt}. Output on transparent background, no white background."
					current_app.logger.info("[custom-shirt] Enhanced prompt with transparent background instruction")
				
				# Generate image
				res = client.images.generate(model="gpt-image-1-mini", prompt=enhanced_prompt, size="1024x1024")
				b64 = res.data[0].b64_json
				img_bytes = b64decode(b64)
				current_app.logger.info(f"[custom-shirt] OpenAI image generated, size: {len(img_bytes)} bytes")
				
				# Try background removal with timeout protection
				img_for_mockup = img_bytes
				try:
					current_app.logger.info("[custom-shirt] Attempting background removal")
					# Use threading with timeout to prevent hanging
					import threading as _threading
					clean_result = [None]
					clean_exception = [None]
					
					def _bg_remove_worker():
						try:
							clean_result[0] = _remove_bg_hf(img_bytes)
						except Exception as e:
							clean_exception[0] = e
					
					bg_thread = _threading.Thread(target=_bg_remove_worker, daemon=True)
					bg_thread.start()
					bg_thread.join(timeout=30)  # 30 second timeout
					
					if bg_thread.is_alive():
						current_app.logger.warning("[custom-shirt] Background removal timed out after 30s, continuing with original")
					elif clean_exception[0]:
						current_app.logger.warning(f"[custom-shirt] Background removal exception: {clean_exception[0]}")
					elif clean_result[0]:
						img_for_mockup = clean_result[0]
						current_app.logger.info("[custom-shirt] Background removal successful")
					else:
						current_app.logger.info("[custom-shirt] Background removal returned None, trying RGBA conversion")
						# Try RGBA conversion for better mockup
						try:
							from PIL import Image
							from io import BytesIO
							img_pil = Image.open(BytesIO(img_bytes)).convert("RGBA")
							buf = BytesIO()
							img_pil.save(buf, format='PNG')
							img_for_mockup = buf.getvalue()
							current_app.logger.info("[custom-shirt] Converted to RGBA for mockup")
						except Exception:
							pass
				except Exception as bg_err:
					current_app.logger.warning(f"[custom-shirt] Background removal failed: {bg_err}")
					import traceback
					current_app.logger.warning(f"[custom-shirt] Traceback: {traceback.format_exc()}")
				
				# Upload to Cloudinary
				cloud_url = current_app.config.get("CLOUDINARY_URL", "").strip()
				if cloud_url:
					public_id = f"custom_shirt_ai_{int(time.time())}_{hashlib.md5(img_bytes[:1000]).hexdigest()[:8]}"
					design_res = cu.upload(img_bytes, folder="custom_shirts", public_id=public_id, overwrite=True, resource_type="image")
					design_url = design_res.get("secure_url") or design_res.get("url")
					current_app.logger.info(f"[custom-shirt] Design uploaded: {design_url}")
					
					# Generate mockup
					current_app.logger.info("[custom-shirt] Starting mockup composition")
					mockup_bytes = _compose_design_on_blank_tee(img_for_mockup)
					if mockup_bytes:
						mockup_public_id = f"{public_id}_mockup"
						mockup_res = cu.upload(mockup_bytes, folder="custom_shirts", public_id=mockup_public_id, overwrite=True, resource_type="image")
						mockup_url = mockup_res.get("secure_url") or mockup_res.get("url")
						current_app.logger.info(f"[custom-shirt] Mockup uploaded: {mockup_url}")
					else:
						mockup_url = design_url
						current_app.logger.warning("[custom-shirt] Mockup composition returned None, using design URL")
					
					# Update in-memory cache with result (thread-safe)
					jobs, lock = _get_custom_shirt_jobs()
					with lock:
						jobs[job_id_inner] = {
							"status": "ready",
							"design_url": design_url,
							"mockup_url": mockup_url,
							"generations_remaining": max(0, 2 - (gen_count + 1)),
							"generation_count": gen_count + 1  # Store for session update later
						}
					current_app.logger.info(f"[custom-shirt] Generation completed for job {job_id_inner}")
				else:
					raise Exception("Cloudinary not configured")
			except Exception as e_all:
				current_app.logger.error(f"[custom-shirt] Generation failed for job {job_id_inner}: {e_all}")
				import traceback
				current_app.logger.error(f"[custom-shirt] Traceback: {traceback.format_exc()}")
				jobs, lock = _get_custom_shirt_jobs()
				with lock:
					jobs[job_id_inner] = {
						"status": "error",
						"error": str(e_all)
					}
	
	thr = threading.Thread(target=_worker, args=(current_app.app_context(), job_id, prompt, generation_count), daemon=True)
	thr.start()
	return jsonify({"ok": True, "started": True, "job_id": job_id})


@main_bp.get("/custom-shirt/generate-status")
def custom_shirt_generate_status():
	"""Check status of custom shirt image generation."""
	job_id = request.args.get("job_id", "").strip()
	if not job_id:
		return jsonify({"error": "Missing job_id"}), 400
	
	# Read from in-memory cache (thread-safe)
	jobs, lock = _get_custom_shirt_jobs()
	with lock:
		job_data = jobs.get(job_id, {})
	
	if job_data.get("status") == "ready":
		# Update session generation count when we return the result (in request context)
		if "generation_count" in job_data:
			session["custom_shirt_generations"] = job_data["generation_count"]
			session.modified = True
		
		return jsonify({
			"ready": True,
			"design_url": job_data.get("design_url", ""),
			"mockup_url": job_data.get("mockup_url", ""),
			"generations_remaining": job_data.get("generations_remaining", 0)
		})
	elif job_data.get("status") == "error":
		return jsonify({
			"ready": False,
			"error": job_data.get("error", "Generation failed")
		}), 500
	else:
		return jsonify({"ready": False})


@main_bp.post("/custom-shirt/accept-design")
def custom_shirt_accept_design():
	"""Accept and persist a design so it persists across page refreshes."""
	design_url = (request.json or {}).get("design_url", "").strip()
	mockup_url = (request.json or {}).get("mockup_url", "").strip()
	
	if not design_url:
		return jsonify({"error": "Missing design_url"}), 400
	
	# Store in session for persistence
	session["custom_shirt_accepted"] = {
		"design_url": design_url,
		"mockup_url": mockup_url or design_url,
		"accepted_at": time.time()
	}
	session.modified = True
	
	return jsonify({"success": True, "message": "Design accepted"})

@main_bp.post("/custom-shirt/clear-accepted")
def custom_shirt_clear_accepted():
	"""Clear the accepted design."""
	session.pop("custom_shirt_accepted", None)
	session.modified = True
	return jsonify({"success": True})


@main_bp.post("/custom-shirt/add-to-cart")
def custom_shirt_add_to_cart():
	"""Add custom shirt to cart."""
	design_url = request.form.get("design_url", "").strip()
	color = request.form.get("color", "white").strip()
	size = request.form.get("size", "L").strip()
	qty = int(request.form.get("quantity", "1"))
	buy_now = request.form.get("buy_now") == "1"
	
	if not design_url:
		return redirect(request.referrer or url_for("main.custom_shirt"))
	
	# Fixed price: $19.99
	price = 19.99
	currency = "USD"
	
	cart = session.get("cart", {"items": []})
	if not cart.get("items"):
		cart["items"] = []
	
	# Create custom cart item
	cart_item = {
		"is_custom": True,
		"title": "Custom T-Shirt",
		"design_url": design_url,
		"orig_price": price,
		"price": price,
		"currency": currency,
		"quantity": qty,
		"color": color,
		"size": size,
		"image": design_url,
	}
	
	cart["items"].append(cart_item)
	session["cart"] = cart
	session.modified = True
	
	# GA4 tracking
	try:
		if hasattr(request, "gtag") or True:  # Always try if gtag is available
			pass  # Will be handled in template
	except:
		pass
	
	return redirect(url_for("main.checkout") if buy_now else url_for("cart.view_cart"))


@main_bp.get("/product/<slug>")
def product_detail(slug: str):
	product = Product.query.filter_by(slug=slug).first_or_404()
	if product.status != "active":
		return abort(404)
	
	# Handle Google Shopping automated discount token (pv2 parameter)
	google_discount_info = None
	pv2_token = request.args.get("pv2", "").strip()
	if pv2_token:
		# Get merchant ID from config (you'll need to set this in your config)
		merchant_id = current_app.config.get("GOOGLE_MERCHANT_ID", "140301646")
		
		# Validate the JWT token
		token_payload = validate_google_jwt_token(pv2_token, merchant_id)
		if token_payload:
			google_discount_info = extract_google_discount_info(token_payload)
			
			# Store discount info in session for persistence
			session["google_discount"] = {
				"product_id": product.id,
				"offer_id": google_discount_info["offer_id"],
				"discounted_price": google_discount_info["discounted_price"],
				"prior_price": google_discount_info["prior_price"],
				"currency": google_discount_info["currency"],
				"expires_at": google_discount_info["expires_at"],
				"token": pv2_token
			}
			session.modified = True
	
	# Check if we have a valid Google discount in session for this product
	if not google_discount_info and session.get("google_discount"):
		session_discount = session["google_discount"]
		if is_google_discount_valid(session_discount, product.id):
			google_discount_info = {
				"offer_id": session_discount.get("offer_id", ""),
				"discounted_price": session_discount.get("discounted_price", 0),
				"prior_price": session_discount.get("prior_price", 0),
				"currency": session_discount.get("currency", "USD"),
				"expires_at": session_discount.get("expires_at", 0)
			}
	
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
	
	# Load reviews for this product from reviews.json
	product_reviews = []
	try:
		path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "reviews.json")
		with open(path, "r", encoding="utf-8") as f:
			all_reviews = json.load(f) or []
		# Filter reviews for this product and sort by rating descending (highest first)
		product_reviews = [
			r for r in all_reviews 
			if r.get("product_id") and str(r.get("product_id")) == str(product.id)
		]
		# Sort by rating descending (highest first), then by created_at descending for same ratings
		try:
			# First sort by date descending (most recent first) for secondary sort
			product_reviews.sort(key=lambda r: r.get("created_at", "") or "", reverse=True)
			# Then sort by rating descending (highest first) - this is the primary sort
			product_reviews.sort(key=lambda r: r.get("rating", 0) or 0, reverse=True)
		except Exception:
			# Fallback: simple sort by rating descending
			try:
				product_reviews.sort(key=lambda r: r.get("rating", 0) or 0, reverse=True)
			except Exception:
				pass
	except Exception:
		product_reviews = []
	
	# Get loyalty email from session for TikTok Pixel identify
	loyalty_email = session.get("loyalty_email", "").strip().lower() or None
	
	return render_template(
		"product_detail.html",
		product=product,
		sizes=sizes,
		colors=colors,
		images=images,
		prev_slug=(prev_p.slug if prev_p else None),
		next_slug=(next_p.slug if next_p else None),
		google_discount_info=google_discount_info,
		reviews=product_reviews,
		loyalty_email=loyalty_email,
	)


@main_bp.get("/reviews")
def reviews_page():
	"""Public reviews page rendered from stored JSON reviews."""
	reviews = []
	try:
		# Use app/data/reviews.json (two levels up from this file's dir)
		path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "reviews.json")
		with open(path, "r", encoding="utf-8") as f:
			reviews = json.load(f) or []
	except Exception:
		reviews = []
	# Newest first
	try:
		reviews.sort(key=lambda r: r.get("created_at", ""), reverse=True)
	except Exception:
		pass
	# Map product ids to Product rows for linking
	products = {p.id: p for p in Product.query.filter_by(status="active").all()}
	return render_template("reviews.html", reviews=reviews, products=products)


@main_bp.get("/referrals")
def referrals_page():
	"""Simple referrals page to generate a code and show a share link/summary."""
	# Load existing codes
	base_dir = os.path.dirname(os.path.dirname(__file__))
	referrers_path = os.path.join(base_dir, "data", "referrers.json")
	ledger_path = os.path.join(base_dir, "data", "referrals_ledger.json")
	referrers = []
	ledger = []
	try:
		with open(referrers_path, "r", encoding="utf-8") as f:
			referrers = json.load(f) or []
	except Exception:
		referrers = []
	try:
		with open(ledger_path, "r", encoding="utf-8") as f:
			ledger = json.load(f) or []
	except Exception:
		ledger = []
	# If session has a code, show its summary
	my_code = session.get("ref") or ""
	my_rows = [r for r in ledger if (r.get("code") or "") == my_code] if my_code else []
	return render_template("referrals.html", referrers=referrers, my_code=my_code, my_rows=my_rows)


@main_bp.post("/referrals/create")
def referrals_create():
	"""Create or return a referral code for a submitted email."""
	email = (request.form.get("email") or "").strip().lower()
	if not email:
		return render_template("referrals.html", error="Please enter an email to generate your referral code.", referrers=[], my_code="", my_rows=[])
	# Load current list
	base_dir = os.path.dirname(os.path.dirname(__file__))
	referrers_path = os.path.join(base_dir, "data", "referrers.json")
	try:
		with open(referrers_path, "r", encoding="utf-8") as f:
			rows = json.load(f) or []
	except Exception:
		rows = []
	# Check if email already has a code
	for r in rows:
		if (r.get("email") or "").lower() == email:
			code = r.get("code") or ""
			session["ref"] = code
			session.modified = True
			# Notify existing referrer
			try:
				base = current_app.config.get("BASE_URL", request.url_root).rstrip("/")
				link = f"{base}/?ref={code}"
				html = render_simple_email("Referral Code", [
					f"Your referral code: {code}",
					f"Share this link: {link}",
				])
				send_email_via_sendgrid(email, "Your Roast Cotton referral code", html)
				# Admin notify
				to_admin = (current_app.config.get("ADMIN_EMAIL") or os.getenv("ADMIN_EMAIL") or "").strip()
				if to_admin:
					admin_html = render_simple_email("Referral code looked up", [f"Email: {email}", f"Code: {code}", f"Link: {link}"])
					send_email_via_sendgrid(to_admin, "Referral code lookup", admin_html)
			except Exception:
				pass
			return render_template("referrals.html", created=True, code=code, referrers=rows, my_code=code, my_rows=[])
	# Generate code from email hash
	base = email.split("@")[0].replace(" ", "-")[:12]
	code = f"{base}-{hashlib.md5(email.encode('utf-8')).hexdigest()[:6]}"
	rows.append({"email": email, "code": code})
	# Save
	try:
		os.makedirs(os.path.join(base_dir, "data"), exist_ok=True)
		with open(referrers_path, "w", encoding="utf-8") as f:
			json.dump(rows, f, ensure_ascii=False, indent=2)
	except Exception:
		pass
	# Stash in session
	session["ref"] = code
	session.modified = True
	# Notify new referrer
	try:
		base = current_app.config.get("BASE_URL", request.url_root).rstrip("/")
		link = f"{base}/?ref={code}"
		html = render_simple_email("Referral Code Created", [
			f"Your referral code: {code}",
			f"Share this link: {link}",
		])
		send_email_via_sendgrid(email, "Your Roast Cotton referral code", html)
		# Admin notify
		to_admin = (current_app.config.get("ADMIN_EMAIL") or os.getenv("ADMIN_EMAIL") or "").strip()
		if to_admin:
			admin_html = render_simple_email("New referral code", [f"Email: {email}", f"Code: {code}", f"Link: {link}"])
			send_email_via_sendgrid(to_admin, "New referral code created", admin_html)
	except Exception:
		pass
	return render_template("referrals.html", created=True, code=code, referrers=rows, my_code=code, my_rows=[])


@main_bp.get("/checkout")
def checkout():
	cart = session.get("cart") or {"items": []}
	# Support GET-based add-to-cart for Google checkout URLs
	try:
		pid_raw = request.args.get("product_id") or request.args.get("item_id")
		qty_raw = request.args.get("quantity") or request.args.get("qty") or "1"
		vid_raw = request.args.get("variant_id") or request.args.get("vid")
		color_raw = request.args.get("color")
		size_raw = request.args.get("size")
		if pid_raw:
			pid = int(str(pid_raw))
			qty = max(1, min(10, int(str(qty_raw))))
			product = Product.query.get(pid)
			if product and product.status == "active":
				variant = None
				if vid_raw:
					try:
						v = Variant.query.get(int(str(vid_raw)))
						if v and v.product_id == product.id:
							variant = v
					except Exception:
						variant = None
				if not variant and product.variants:
					variant = product.variants[0]
				# Price: honor Google discount if available, otherwise site-wide 15% sale
				from decimal import Decimal as _D
				if session.get("google_discount") and is_google_discount_valid(session["google_discount"], product.id):
					sale_price = _D(str(session["google_discount"].get("discounted_price", 0)))
				else:
					sale_price = (product.price * _D("85")) / _D("100")
				found = False
				for it in cart.get("items", []):
					if variant and it.get("variant_id") == variant.id:
						# only merge if same color/size as well
						it_color = (it.get("color") or "").strip().lower()
						it_size = (it.get("size") or "").strip().upper()
						new_color = (str(color_raw or (variant.color or "")).strip().lower())
						new_size = (str(size_raw or (variant.size or "")).strip().upper())
						if it_color == new_color and it_size == new_size:
							it["quantity"] += qty
							found = True
							break
				if not found:
					cart_item = {
						"product_id": product.id,
						"variant_id": (variant.id if variant else None),
						"title": product.title,
						"slug": product.slug,
						"orig_price": float(product.price),
						"price": float(sale_price),
						"currency": product.currency,
						"quantity": qty,
						"image": ((product.design.image_url) if product.design else ""),
						"product_uid": ((variant.gelato_sku) if variant else ""),
						"color": ((str(color_raw).lower()) if color_raw else ((variant.color) if variant else "")),
						"size": ((str(size_raw).upper()) if size_raw else ((variant.size) if variant else "")),
					}
					# Add Google discount data if available
					if session.get("google_discount") and is_google_discount_valid(session["google_discount"], product.id):
						cart_item.update({
							"google_discount_price": session["google_discount"].get("discounted_price"),
							"google_discount_currency": session["google_discount"].get("currency"),
							"google_offer_id": session["google_discount"].get("offer_id")
						})
					cart.setdefault("items", []).append(cart_item)
				session["cart"] = cart
				session.modified = True
	except Exception:
		pass
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
	# Try to get email and source from form data, JSON, or raw data
	email = ""
	source = ""
	
	# Try form data first (standard form submission)
	if request.form:
		email = (request.form.get("email") or "").strip().lower()
		source = (request.form.get("source") or "").strip().lower()
	
	# Try JSON if form data didn't work
	if not email and request.is_json and request.json:
		email = (request.json.get("email") or "").strip().lower()
		source = (request.json.get("source") or "").strip().lower()
	
	# Try parsing raw data as form-encoded if nothing else worked
	if not email and request.data:
		try:
			from urllib.parse import parse_qs
			parsed = parse_qs(request.data.decode('utf-8'))
			email = (parsed.get("email", [""])[0] or "").strip().lower()
			source = (parsed.get("source", [""])[0] or "").strip().lower()
		except Exception:
			pass
	
	# Debug logging
	current_app.logger.info(f"[loyalty-signup] Received signup - email: {email}, source: '{source}', form: {dict(request.form) if request.form else None}, json: {request.json if request.is_json else None}, content_type: {request.content_type}")
	if email:
		# Check if we've already processed this signup in this session to prevent duplicate admin emails
		processed_signups = set(session.get("loyalty_signups_processed", []))
		is_new_signup = email not in processed_signups
		
		session["loyalty_email"] = email
		session.modified = True
		# Send welcome email to user (always send, even if already processed)
		# Use different email templates based on the source
		try:
			current_app.logger.info(f"[loyalty-signup] Selecting email template - source: '{source}' (len={len(source)})")
			if source == "exit_intent_free_shirt":
				# Free shirt exit intent offer
				current_app.logger.info(f"[loyalty-signup] Using free shirt email template")
				html = render_template("email_free_shirt_welcome.html")
				subject = "Your Free Shirt is Waiting!"
			elif source == "promo_5off":
				# 5% discount popup offer
				current_app.logger.info(f"[loyalty-signup] Using 5% off email template")
				html = render_template("email_5off_welcome.html")
				subject = "Your 5% Off Code is Here!"
			else:
				# Regular loyalty signup (from loyalty page)
				current_app.logger.info(f"[loyalty-signup] Using default loyalty email template (source was: '{source}')")
				html = render_template("email_loyalty_welcome.html")
				subject = "Welcome to Roast Cotton Loyalty"
			
			ok, msg = send_email_via_sendgrid(email, subject, html)
			if ok:
				current_app.logger.info(f"[loyalty-signup] Welcome email sent to {email} (source: '{source}', subject: '{subject}')")
			else:
				current_app.logger.error(f"[loyalty-signup] Failed to send welcome email to {email}: {msg}")
		except Exception as e:
			current_app.logger.exception(f"[loyalty-signup] Exception sending welcome email to {email}: {e}")
		# Notify admin of new signup (best-effort) - only once per email per session
		if is_new_signup:
			try:
				to_admin = (current_app.config.get("ADMIN_EMAIL") or os.getenv("ADMIN_EMAIL") or "").strip()
				if to_admin:
					# Set admin email subject based on source
					if source == "exit_intent_free_shirt":
						admin_subject = "New Loyalty Signup - Exit Intent Free Shirt"
					elif source == "promo_5off":
						admin_subject = "New Loyalty Signup - 5% Off Popup"
					else:
						admin_subject = "New Loyalty Signup - Loyalty Page"
					
					admin_html = render_simple_email("New loyalty signup", [f"Email: {email}", f"Source: {source or 'loyalty page'}"])
					ok, msg = send_email_via_sendgrid(to_admin, admin_subject, admin_html)
					if ok:
						current_app.logger.info(f"[loyalty-signup] Admin email sent for {email} (source: {source})")
					else:
						current_app.logger.warning(f"[loyalty-signup] Admin email failed for {email}: {msg}")
					# Mark this email as processed to prevent duplicate admin emails
					processed_signups.add(email)
					session["loyalty_signups_processed"] = list(processed_signups)
					session.modified = True
			except Exception as e:
				current_app.logger.exception(f"[loyalty-signup] Exception sending admin email for {email}: {e}")
	
	# Return appropriate response based on request type
	# Check if this is an AJAX/fetch request
	is_ajax = (
		request.headers.get("Accept", "").startswith("application/json") or
		request.headers.get("X-Requested-With") == "XMLHttpRequest" or
		request.content_type and "application/json" in request.content_type
	)
	
	if is_ajax:
		return jsonify({"success": True, "email": email, "source": source})
	
	# Regular form submission - return HTML
	return render_template("loyalty.html", email=email, points=0, tier="member", perks=[]) 


@main_bp.get("/health")
def health():
	return {"status": "ok"}


@main_bp.get("/api/gelato/verify")
def gelato_verify():
    """Quick connectivity check to Gelato APIs."""
    client = GelatoClient()
    ok, debug = client.verify()
    return jsonify({"ok": ok, "debug": debug}), (200 if ok else 500)


@main_bp.get("/shipping-returns")
def shipping_returns():
	return render_template("shipping_returns.html")


@main_bp.route("/contact", methods=["GET","POST"])
def contact_page():
    # Basic GET renders form; POST triggers an email
    if request.method == 'POST':
        # Bot prevention: Check honeypot field
        honeypot = (request.form.get('website') or '').strip()
        if honeypot:
            # Bot detected - silently reject
            current_app.logger.warning("[contact] Bot detected via honeypot field")
            return render_template('contact.html', sent=True)  # Return success to bot
        
        name = (request.form.get('name') or '').strip()
        email = (request.form.get('email') or '').strip()
        msg = (request.form.get('message') or '').strip()
        subject = (request.form.get('subject') or '').strip()
        contact_reason = (request.form.get('contact_reason') or '').strip()
        order_number = (request.form.get('order_number') or '').strip()
        
        # Basic validation
        if not name or not email or not msg or not subject:
            return render_template('contact.html', sent=False, error='Please fill in all required fields.')
        
        # Validate email format
        if '@' not in email or '.' not in email.split('@')[1]:
            return render_template('contact.html', sent=False, error='Please enter a valid email address.')
        
        try:
            to = (current_app.config.get('ADMIN_EMAIL') or os.getenv('ADMIN_EMAIL') or 'email@roastcotton.com').strip()
            
            # Build email body with all details
            email_body_lines = [
                f'From: {name} <{email}>',
                f'Contact Reason: {contact_reason or "Not specified"}',
            ]
            if order_number:
                email_body_lines.append(f'Order Number: {order_number}')
            email_body_lines.extend([
                f'Subject: {subject}',
                '',
                'Message:',
                msg
            ])
            
            html = render_simple_email('New contact message', email_body_lines)
            ok, msg_result = send_email_via_sendgrid(to, f'Contact form: {subject}', html)
            
            if not ok:
                current_app.logger.error(f"[contact] Failed to send admin email: {msg_result}")
            
            # Send an acknowledgement to the user as well
            if email and ok:
                ack_html = render_simple_email('We received your message', [
                    f'Hi {name},',
                    '',
                    'Thanks for reaching out to Roast Cotton.',
                    '',
                    'We received your message and will get back to you as soon as possible.',
                    'Our team typically responds within 24 hours.',
                    '',
                    'If your inquiry is urgent, please include "URGENT" in your next message.',
                ])
                send_email_via_sendgrid(email, 'Thanks — we received your message', ack_html)
            
            # Forward to Formspree if configured
            try:
                fs = (current_app.config.get('FORMSPREE_ENDPOINT') or os.getenv('FORMSPREE_ENDPOINT') or '').strip()
                if fs:
                    payload = {
                        'name': name,
                        'email': email,
                        'subject': subject,
                        'message': msg,
                        'contact_reason': contact_reason,
                        'order_number': order_number,
                    }
                    headers = {'Accept': 'application/json'}
                    requests.post(fs, data=payload, headers=headers, timeout=8)
            except Exception:
                pass
        except Exception as e:
            current_app.logger.exception(f"[contact] Error processing contact form: {e}")
            return render_template('contact.html', sent=False, error='There was an error sending your message. Please try again.')
        
        return render_template('contact.html', sent=True)
    return render_template("contact.html")


@main_bp.get("/size-guide")
def size_guide_page():
    return render_template("size_guide.html")


@main_bp.get("/privacy")
def privacy_page():
	return render_template("privacy.html")


@main_bp.get("/about")
def about_page():
    faqs = [
        {"q": "What is Roast Cotton?", "a": "A small merch shop making shirts about whatever is trending - fun, timely, and limited."},
        {"q": "How often do you add new designs?", "a": "We try to add new designs daily based on what's happening online."},
        {"q": "What shirts do you print on?", "a": "High‑quality, unisex tees with durable prints."},
        {"q": "How long is shipping?", "a": "Free shipping usually arrives in 3–6 business days; Express is 2–3 days."},
        {"q": "What’s your return policy?", "a": "30‑day returns on unworn items. See Shipping & Returns for full details."},
        {"q": "Do you take custom requests?", "a": "Sometimes! Send ideas via the Contact page—we love suggestions."},
    ]
    return render_template("about.html", faqs=faqs)


@main_bp.get("/order/confirm/<int:order_id>")
def order_confirm(order_id: int):
	"""Order confirmation page hosting Google Customer Reviews opt-in snippet."""
	try:
		order = Order.query.get_or_404(order_id)
	except Exception as e:
		current_app.logger.exception(f"[order-confirm] Failed to load order {order_id}: {e}")
		abort(404)
	
	addr = order.shipping_address if order else None
	# Prefer email passed via query param (from checkout) if present
	qp_email = (request.args.get("email") or "").strip()
	email = qp_email or ((addr.email if addr else "") or "")
	country = (addr.country if addr and addr.country else "US")
	est_date = (datetime.utcnow().date() + timedelta(days=7)).isoformat()
	# Build product GTINs if any (we don't store GTINs; pass empty list for now)
	products = []

	# Optional: inline processing fallback (test-mode): if webhook hasn't run yet
	gelato_debug = {"attempted": False}
	try:
		# If email provided in query and not stored yet, persist for loyalty linkage
		if qp_email and order.shipping_address and not order.shipping_address.email:
			order.shipping_address.email = qp_email
			db.session.flush()
		# Create Gelato draft if still pending and no gelato id
		if (order.status in ("pending", "paid")) and not order.gelato_order_id:
			gelato_debug["attempted"] = True
			from ..gelato_client import GelatoClient as _GC
			client = _GC()
			items = []
			for oi in order.items:
				# Resolve product and design file
				prod = db.session.get(Product, oi.product_id) if oi.product_id else None
				file_url = "https://cdn-origin.gelato-api-dashboard.ie.live.gelato.tech/docs/sample-print-files/logo.png"
				if prod and prod.design:
					if getattr(prod.design, 'image_url', None):
						file_url = (prod.design.image_url)
					elif prod.design.preview_url:
						file_url = (prod.design.preview_url)
				# productUid priority: OrderItem.product_uid -> Variant.gelato_sku -> DEFAULT_TEE_UID
				uid = (oi.product_uid or "").strip()
				if not uid and oi.variant_id:
					v = db.session.get(Variant, oi.variant_id)
					if v and v.gelato_sku:
						uid = v.gelato_sku
				if not uid:
					uid = (current_app.config.get("DEFAULT_TEE_UID") or "").strip()
				items.append({
					"itemReferenceId": f"{order.id}-{oi.id}",
					"productUid": uid,
					"files": [{"type": "default", "url": file_url}],
					"quantity": int(oi.quantity or 1),
				})
			payload = {
				"orderType": "draft",
				"orderReferenceId": order.stripe_payment_intent_id or f"order-{order.id}",
				"customerReferenceId": email or "",
				"currency": order.currency,
				"items": items,
				"shipmentMethodUid": order.shipment_method_uid or current_app.config.get("DEFAULT_SHIPMENT_METHOD", "express"),
				"shippingAddress": {
					"companyName": (addr.company_name if addr else "") or "",
					"firstName": (addr.first_name if addr else "") or "",
					"lastName": (addr.last_name if addr else "") or "",
					"addressLine1": (addr.address_line1 if addr else "") or "",
					"addressLine2": (addr.address_line2 if addr else "") or "",
					"state": (addr.state if addr else "") or "",
					"city": (addr.city if addr else "") or "",
					"postCode": (addr.post_code if addr else "") or "",
					"country": country,
					"email": email or "",
					"phone": (addr.phone if addr else "") or "",
				},
			}
			gelato_debug["payload"] = payload
			try:
				resp = client.create_order(payload)
				order.gelato_order_id = resp.get("id")
				# Keep status as 'paid' if already paid; else mark submitted
				if order.status != "paid":
					order.status = "submitted"
				db.session.commit()
				gelato_debug["response"] = resp
				gelato_debug["ok"] = True
			except Exception as _ge:
				gelato_debug["ok"] = False
				gelato_debug["error"] = str(_ge)
		# Note: Customer and admin emails are sent by the Stripe webhook handler
		# Only send fallback emails if webhook hasn't run (check if order was just created)
		# Only send if order was created very recently (within last 10 seconds) as fallback
		time_since_creation = (datetime.utcnow() - (order.created_at or datetime.utcnow())).total_seconds()
		should_send_fallback = time_since_creation < 10  # Very recent order, webhook might not have run yet
		
		if should_send_fallback:
			# Send confirmation email only as fallback (webhook should handle this normally)
			if email:
				try:
					from flask import render_template as _rt
					currency = order.currency or current_app.config.get("STORE_CURRENCY", "USD")
					subtotal = sum([(oi.unit_price or 0) * (oi.quantity or 1) for oi in order.items])
					shipping_amount = 0
					amount_paid = float(order.total_amount or 0)
					confirm_url = urljoin(current_app.config.get("BASE_URL", ""), f"/order/confirm/{order.id}")
					html = _rt("email_order_confirmation.html", order=order, items=order.items, subtotal=float(subtotal), shipping=float(shipping_amount), amount_paid=amount_paid, currency=currency, confirm_url=confirm_url)
					send_email_via_sendgrid(email, f"Order #{order.id} confirmed", html)
					gelato_debug["email_sent"] = True
					current_app.logger.info(f"[order-confirm] Fallback customer email sent for order {order.id} (webhook may not have run)")
				except Exception as _ee:
					gelato_debug["email_sent"] = False
					gelato_debug["email_error"] = str(_ee)
			
			# Fallback: Notify admin of new paid/submitted order (in case webhook didn't fire or failed)
			# Only send if order status indicates payment succeeded
			if order.status in ("paid", "submitted"):
				try:
					to_admin = (current_app.config.get("ADMIN_EMAIL") or os.getenv("ADMIN_EMAIL") or "").strip()
					if to_admin:
						addr = order.shipping_address
						cust_name = f"{(addr.first_name if addr else '')} {(addr.last_name if addr else '')}".strip()
						cust_email = ((addr.email if addr else "") or "")
						items_lines = []
						try:
							for oi in order.items:
								total_line = float((oi.unit_price or 0) * (oi.quantity or 1))
								items_lines.append(f"{int(oi.quantity or 1)}× {oi.title or ''} — ${total_line:.2f}")
						except Exception:
							items_lines = []
						summary_lines = [
							f"Order ID: {order.id}",
							f"Status: {order.status}",
							f"Amount: {float(order.total_amount or 0):.2f} {order.currency}",
							f"Customer: {cust_name}",
							f"Email: {cust_email}",
							"",
							"Items:",
						] + items_lines
						html = render_simple_email(f"New Order #{order.id}", summary_lines)
						ok, msg = send_email_via_sendgrid(to_admin, f"New order #{order.id}", html)
						if ok:
							current_app.logger.info(f"[order-confirm] Fallback admin email sent for order {order.id} to {to_admin} (webhook may not have run)")
						else:
							current_app.logger.warning(f"[order-confirm] Fallback admin email failed for order {order.id}: {msg}")
				except Exception as e:
					current_app.logger.exception(f"[order-confirm] Fallback admin email exception for order {order.id}: {e}")
	except Exception as e:
		current_app.logger.exception(f"[order-confirm] Error in fallback processing for order {order_id}: {e}")
		# Continue to render page even if fallback processing fails
	
	# Clear cart after confirmation (best-effort)
	try:
		session["cart"] = {"items": []}
		session.modified = True
	except Exception as e:
		current_app.logger.warning(f"[order-confirm] Failed to clear cart for order {order_id}: {e}")
	
	# Convert OrderItem objects to dictionaries for JSON serialization
	order_items_dict = []
	try:
		items = order.items if order and hasattr(order, 'items') else []
		for oi in items:
			try:
				order_items_dict.append({
					"id": getattr(oi, 'id', None),
					"order_id": getattr(oi, 'order_id', None),
					"product_id": getattr(oi, 'product_id', None),
					"variant_id": getattr(oi, 'variant_id', None),
					"title": getattr(oi, 'title', '') or '',
					"quantity": getattr(oi, 'quantity', 1) or 1,
					"unit_price": float(oi.unit_price) if oi.unit_price else 0.0,
					"product_uid": getattr(oi, 'product_uid', '') or '',
				})
			except Exception as e:
				current_app.logger.warning(f"[order-confirm] Failed to serialize order item for order {order_id}: {e}")
				continue
	except Exception as e:
		current_app.logger.exception(f"[order-confirm] Failed to process order items for order {order_id}: {e}")
		# Continue with empty list
	
	try:
		return render_template(
			"order_confirmation.html",
			order=order,
			order_items=order_items_dict,
			email=email,
			country=country,
			est_delivery=est_date,
			products=products,
			gelato_debug=gelato_debug,
			merchant_id=114634997,
		)
	except Exception as e:
		current_app.logger.exception(f"[order-confirm] Failed to render template for order {order_id}: {e}")
		# Re-raise to trigger 500 handler, but with better logging
		raise


@main_bp.get("/terms")
def terms_page():
	return render_template("terms.html")


@main_bp.get("/sitemap.xml")
def sitemap_xml():
	base = current_app.config.get("BASE_URL", request.url_root).rstrip("/")
	items = []
	iso_today = datetime.utcnow().date().isoformat()

	def add_url(loc: str, lastmod: str | None = None, changefreq: str | None = None, priority: str | None = None, image: str | None = None, image_title: str | None = None):
		parts = [f"<loc>{xml_escape(loc)}</loc>"]
		if lastmod:
			parts.append(f"<lastmod>{xml_escape(lastmod)}</lastmod>")
		if changefreq:
			parts.append(f"<changefreq>{xml_escape(changefreq)}</changefreq>")
		if priority:
			parts.append(f"<priority>{xml_escape(priority)}</priority>")
		if image:
			img = f"<image:image><image:loc>{xml_escape(image)}</image:loc>" + (f"<image:title>{xml_escape(image_title)}</image:title>" if image_title else "") + "</image:image>"
			parts.append(img)
		items.append("<url>" + "".join(parts) + "</url>")

	# Static pages
	static_pages = [
		("/", iso_today, "daily", "0.9"),
		("/shop", iso_today, "daily", "0.8"),
		("/search", iso_today, "weekly", "0.5"),
		("/cart", iso_today, "daily", "0.3"),
		("/checkout", iso_today, "daily", "0.6"),
		("/about", iso_today, "yearly", "0.3"),
		("/shipping-returns", iso_today, "yearly", "0.3"),
		("/contact", iso_today, "yearly", "0.2"),
		("/privacy", iso_today, "yearly", "0.2"),
		("/terms", iso_today, "yearly", "0.2"),
		("/subscribe/monthly-shirt", iso_today, "monthly", "0.6"),
		("/loyalty", iso_today, "yearly", "0.3"),
		("/reviews", iso_today, "weekly", "0.5"),
		("/referrals", iso_today, "yearly", "0.4"),
		("/size-guide", iso_today, "yearly", "0.3"),
	]
	for path, lm, cf, pr in static_pages:
		add_url(urljoin(base, path), lm, cf, pr)

	# Category filtered pages
	for c in Category.query.all():
		add_url(urljoin(base, f"/shop?cat={c.slug}"), iso_today, "weekly", "0.6")

	# SEO category pages
	category_pages = [
		("/funny-tshirts", iso_today, "weekly", "0.7"),
		("/meme-tshirts", iso_today, "weekly", "0.7"),
		("/sarcastic-tshirts", iso_today, "weekly", "0.7"),
		("/witty-shirts", iso_today, "weekly", "0.7"),
		("/funny-saying-tshirts", iso_today, "weekly", "0.7"),
		("/pun-shirts", iso_today, "weekly", "0.7"),
		("/dad-joke-shirts", iso_today, "weekly", "0.7"),
		("/black-friday", iso_today, "daily", "0.8"),
		("/christmas-shirts", iso_today, "weekly", "0.7"),
		("/weird-shirts", iso_today, "weekly", "0.7"),
	]
	for path, lm, cf, pr in category_pages:
		add_url(urljoin(base, path), lm, cf, pr)

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


@main_bp.get("/subscribe/monthly-shirt")
def subscribe_monthly():
    products = Product.query.filter_by(status="active").order_by(Product.title.asc()).all()
    # Preload variants for client-side filtering
    product_variants = {}
    for p in products:
        product_variants[p.id] = [
            {
                "id": v.id,
                "name": v.name,
                "size": v.size or "",
                "color": v.color or "",
            }
            for v in (p.variants or [])
        ]
    return render_template(
        "subscribe_monthly.html",
        products=products,
        product_variants=product_variants,
        price_per_month=15.00,
    )

from flask import render_template, current_app, request, abort, session, Response, jsonify
import os
import json
import hashlib
import requests
from . import main_bp
from ..models import Product, Category, Variant, Trend
from decimal import Decimal
from ..models import Order, Address
from urllib.parse import urljoin
from datetime import datetime
from ..gelato_client import GelatoClient
from datetime import timedelta
from ..utils import send_email_via_sendgrid, render_simple_email, validate_google_jwt_token, extract_google_discount_info, is_google_discount_valid
from ..extensions import db


@main_bp.get("/")
def index():
	page = request.args.get("page", 1, type=int)
	per_page = 9
	
	products_query = Product.query.filter_by(status="active").order_by(Product.created_at.desc())
	products_pagination = products_query.paginate(
		page=page, per_page=per_page, error_out=False
	)
	
	return render_template("index.html", 
		products=products_pagination.items,
		pagination=products_pagination,
		current_page=page
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


@main_bp.get("/search")
def search():
	q = request.args.get("q", "").strip()
	if not q:
		q = "meme"
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
	return render_template(
		"product_detail.html",
		product=product,
		sizes=sizes,
		colors=colors,
		images=images,
		prev_slug=(prev_p.slug if prev_p else None),
		next_slug=(next_p.slug if next_p else None),
		google_discount_info=google_discount_info,
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
				send_email_via_sendgrid(email, "Your Dumbshirts referral code", html)
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
		send_email_via_sendgrid(email, "Your Dumbshirts referral code", html)
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
	email = (request.form.get("email") or "").strip().lower()
	if email:
		session["loyalty_email"] = email
		session.modified = True
		try:
			html = render_simple_email("Welcome to Loyalty", [
				"Thanks for joining our loyalty program.",
				"You earn 1 point per $1 spent.",
			])
			send_email_via_sendgrid(email, "Welcome to Dumbshirts Loyalty", html)
		except Exception:
			pass
		# Notify admin of new signup (best-effort)
		try:
			to_admin = (current_app.config.get("ADMIN_EMAIL") or os.getenv("ADMIN_EMAIL") or "").strip()
			if to_admin:
				admin_html = render_simple_email("New loyalty signup", [f"Email: {email}"])
				send_email_via_sendgrid(to_admin, "New loyalty signup", admin_html)
		except Exception:
			pass
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
        name = (request.form.get('name') or '').strip()
        email = (request.form.get('email') or '').strip()
        msg = (request.form.get('message') or '').strip()
        subject = (request.form.get('subject') or '').strip()
        try:
            to = (current_app.config.get('ADMIN_EMAIL') or os.getenv('ADMIN_EMAIL') or 'email@dumbshirts.store').strip()
            html = render_simple_email('New contact message', [f'From: {name} <{email}>', f'Subject: {subject}', '', msg])
            send_email_via_sendgrid(to, 'Contact form message', html)
            # Send an acknowledgement to the user as well
            if email:
                ack_html = render_simple_email('We received your message', [
                    'Thanks for reaching out to Dumbshirts.',
                    'We will get back to you shortly.',
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
                    }
                    headers = {'Accept': 'application/json'}
                    requests.post(fs, data=payload, headers=headers, timeout=8)
            except Exception:
                pass
        except Exception:
            pass
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
        {"q": "What is Dumbshirts.store?", "a": "A small merch shop making shirts about whatever is trending - fun, timely, and limited."},
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
	order = Order.query.get_or_404(order_id)
	addr = order.shipping_address
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
		# Send confirmation email best-effort
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
			except Exception as _ee:
				gelato_debug["email_sent"] = False
				gelato_debug["email_error"] = str(_ee)
	except Exception:
		pass
	# Clear cart after confirmation
	session["cart"] = {"items": []}
	session.modified = True
	
	# Convert OrderItem objects to dictionaries for JSON serialization
	order_items_dict = []
	for oi in order.items:
		order_items_dict.append({
			"id": oi.id,
			"order_id": oi.order_id,
			"product_id": oi.product_id,
			"variant_id": oi.variant_id,
			"title": oi.title,
			"quantity": oi.quantity,
			"unit_price": float(oi.unit_price) if oi.unit_price else 0,
			"product_uid": oi.product_uid,
		})
	
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

import os
import stripe
from flask import Blueprint, current_app, jsonify, request, session
import json
import os
from datetime import datetime
from .extensions import db
from .gelato_client import GelatoClient
from .models import Order, OrderItem, Address, Variant, Product
from urllib.parse import urljoin
from decimal import Decimal
from .utils import send_email_via_sendgrid, render_simple_email

stripe_bp = Blueprint("stripe", __name__)



@stripe_bp.post("/api/subscribe/create-session")
def create_subscribe_session():
	try:
		if not current_app.config.get("STRIPE_SECRET_KEY") or not current_app.config.get("STRIPE_PUBLISHABLE_KEY"):
			return jsonify({"error": "Stripe not configured"}), 400
		data = request.form or {}
		# Fixed subscription price: $15/month USD
		price_amount = 1500  # cents
		currency = current_app.config.get("STORE_CURRENCY", "USD").lower()

		# Create or reuse Price; for simplicity create inline now
		session_obj = stripe.checkout.Session.create(
			mode="subscription",
			line_items=[{
				"price_data": {
					"currency": currency,
					"product_data": {
						"name": "Monthly Shirt Subscription",
						"metadata": {
							"product_id": data.get("product_id") or "",
							"size": data.get("size") or "",
							"color": data.get("color") or "",
						}
					},
					"unit_amount": price_amount,
					"recurring": {"interval": "month", "interval_count": 1},
				},
				"quantity": 1,
			}],
			success_url=_absolute_url("/"),
			cancel_url=_absolute_url("/subscribe/monthly-shirt"),
			shipping_address_collection={"allowed_countries": ["US"]},
			allow_promotion_codes=False,
		)
		return jsonify({"url": session_obj.url})
	except Exception as e:
		current_app.logger.exception("create_subscribe_session failed")
		return jsonify({"error": str(e)}), 500

@stripe_bp.before_app_request
def _setup_stripe():
	stripe.api_key = current_app.config["STRIPE_SECRET_KEY"]


def _absolute_url(url: str) -> str:
	if not url:
		return ""
	if url.startswith("http://") or url.startswith("https://"):
		return url
	base = current_app.config.get("BASE_URL", "http://localhost:5000")
	return urljoin(base, url)


def _compute_cart_total(cart: dict) -> int:
	total = Decimal("0.00")
	for it in (cart or {}).get("items", []):
		qty = int(it.get("quantity", 0))
		price = Decimal(str(it.get("price", 0)))
		total += price * qty
	return int(total * 100)  # cents


def _lookup_gelato_uid(size: str | None, color: str | None, neck: str | None = "crewneck") -> str:
	"""Map size+color+neck to a Gelato productUid. Falls back to empty string when unknown.
	Keep this mapping in sync with the client-side lookup on product_detail.
	"""
	s = (size or "").strip().upper()
	c = (color or "").strip().lower()
	n = (neck or "crewneck").strip().lower()
	MAP = {
		'S|white|crewneck': 'apparel_product_gca_t-shirt_gsc_crewneck_gcu_unisex_gqa_heavy-weight_gsi_s_gco_white_gpr_4-0_gildan_5000',
		'M|white|crewneck': 'apparel_product_gca_t-shirt_gsc_crewneck_gcu_unisex_gqa_heavy-weight_gsi_m_gco_white_gpr_4-0_gildan_5000',
		'L|white|crewneck': 'apparel_product_gca_t-shirt_gsc_crewneck_gcu_unisex_gqa_heavy-weight_gsi_l_gco_white_gpr_4-0_gildan_5000',
		'XL|white|crewneck': 'apparel_product_gca_t-shirt_gsc_crewneck_gcu_unisex_gqa_heavy-weight_gsi_xl_gco_white_gpr_4-0_gildan_5000',
		'S|black|crewneck': 'apparel_product_gca_t-shirt_gsc_crewneck_gcu_unisex_gqa_heavy-weight_gsi_s_gco_black_gpr_4-0_gildan_5000',
		'M|black|crewneck': 'apparel_product_gca_t-shirt_gsc_crewneck_gcu_unisex_gqa_heavy-weight_gsi_m_gco_black_gpr_4-0_gildan_5000',
		'L|black|crewneck': 'apparel_product_gca_t-shirt_gsc_crewneck_gcu_unisex_gqa_heavy-weight_gsi_l_gco_black_gpr_4-0_gildan_5000',
		'XL|black|crewneck': 'apparel_product_gca_t-shirt_gsc_crewneck_gcu_unisex_gqa_heavy-weight_gsi_xl_gco_black_gpr_4-0_gildan_5000',
		'S|blue|crewneck': 'apparel_product_gca_t-shirt_gsc_crewneck_gcu_unisex_gqa_heavy-weight_gsi_s_gco_carolina-blue_gpr_4-0_gildan_5000	',
		'M|blue|crewneck': 'apparel_product_gca_t-shirt_gsc_crewneck_gcu_unisex_gqa_heavy-weight_gsi_m_gco_carolina-blue_gpr_4-0_gildan_5000',
		'L|blue|crewneck': 'apparel_product_gca_t-shirt_gsc_crewneck_gcu_unisex_gqa_heavy-weight_gsi_l_gco_carolina-blue_gpr_4-0_gildan_5000',
		'XL|blue|crewneck': 'apparel_product_gca_t-shirt_gsc_crewneck_gcu_unisex_gqa_heavy-weight_gsi_xl_gco_carolina-blue_gpr_4-0_gildan_5000',
	}
	return MAP.get(f"{s}|{c}|{n}", "")


@stripe_bp.get("/api/shipment-methods")
def shipment_methods():
	try:
		client = GelatoClient()
		cart = session.get("cart") or {"items": []}
		# Build minimal quote payload using cart contents and default US address
		products = []
		idx = 1
		for it in cart.get("items", []):
			uid = it.get("product_uid") or current_app.config.get("DEFAULT_TEE_UID", "")
			if not uid:
				continue
			products.append({
				"itemReferenceId": f"cart-{idx}",
				"productUid": uid,
				"files": [{"type": "default", "url": it.get("image") or "https://cdn-origin.gelato-api-dashboard.ie.live.gelato.tech/docs/sample-print-files/logo.png"}],
				"quantity": int(it.get("quantity", 1)),
			})
			idx += 1
		payload = {
			"orderReferenceId": "cart-quote",
			"customerReferenceId": "cart",
			"currency": current_app.config.get("STORE_CURRENCY", "USD"),
			"allowMultipleQuotes": False,
			"recipient": {
				"country": "US",
				"companyName": "Example",
				"firstName": "Test",
				"lastName": "User",
				"addressLine1": "451 Clarkson Ave",
				"addressLine2": "Brooklyn",
				"state": "NY",
				"city": "New York",
				"postCode": "11203",
				"email": "test@example.com",
				"phone": "123456789"
			},
			"products": products or []
		}
		q = client.quote_order(payload)
		# Flatten shipment methods from first quote
		quotes = (q or {}).get("quotes") or []
		methods = []
		if quotes:
			for m in (quotes[0].get("shipmentMethods") or []):
				methods.append({
					"name": m.get("name"),
					"uid": m.get("shipmentMethodUid"),
					"price": m.get("price"),
					"currency": m.get("currency"),
					"minDays": m.get("minDeliveryDays"),
					"maxDays": m.get("maxDeliveryDays"),
					"minDate": m.get("minDeliveryDate"),
					"maxDate": m.get("maxDeliveryDate"),
				})
		return jsonify({"methods": methods})
	except Exception as e:
		return jsonify({"error": str(e), "methods": []}), 200


@stripe_bp.post("/api/create-payment-intent")
def create_payment_intent():
	try:
		if not current_app.config.get("STRIPE_SECRET_KEY") or not current_app.config.get("STRIPE_PUBLISHABLE_KEY"):
			return jsonify({"error": "Stripe not configured"}), 400
		cart = session.get("cart") or {"items": []}
		data = request.get_json(silent=True) or {}
		amount_cents = _compute_cart_total(cart)
		# Apply coupon discount server-side as well (percent off subtotal)
		try:
			coupon = cart.get("coupon") or {}
			pct = float(coupon.get("percent", 0))
			if pct > 0:
				amount_cents = int(round(amount_cents * (1 - (pct/100.0))))
		except Exception:
			pass
		currency = current_app.config.get("STORE_CURRENCY", "USD").lower()
		if amount_cents <= 0:
			return jsonify({"error": "Cart is empty"}), 400

		# Create a local order (pending) with provided shipping details
		shipping = Address(
			company_name=(data.get("company_name") or ""),
			first_name=(data.get("first_name") or "Test"),
			last_name=(data.get("last_name") or "User"),
			address_line1=(data.get("address_line1") or "451 Clarkson Ave"),
			address_line2=(data.get("address_line2") or "Brooklyn"),
			state=(data.get("state") or "NY"),
			city=(data.get("city") or "New York"),
			post_code=(data.get("post_code") or "11203"),
			country=(data.get("country") or "US"),
			email=(data.get("email") or "test@example.com"),
			phone=(data.get("phone") or "123456789"),
		)
		db.session.add(shipping)
		db.session.flush()
		shipment_method = (data.get("shipment_method_uid") or current_app.config.get("DEFAULT_SHIPMENT_METHOD", "express")).strip()
		order = Order(
			status="pending",
			currency=currency.upper(),
			total_amount=Decimal(amount_cents) / 100,
			shipment_method_uid=shipment_method,
			shipping_address_id=shipping.id,
		)
		db.session.add(order)
		db.session.flush()
		# Capture referral code on order if present
		try:
			ref = (session.get("ref") or "").strip()
			if ref:
				# store temporarily in session keyed by order id
				refs = session.get("_ref_orders") or {}
				refs[str(order.id)] = ref
				session["_ref_orders"] = refs
				session.modified = True
		except Exception:
			pass

		# Items
		for it in cart.get("items", []):
			variant = db.session.get(Variant, int(it.get("variant_id"))) if it.get("variant_id") else None
			product = db.session.get(Product, int(it.get("product_id"))) if it.get("product_id") else None
			# Resolve productUid priority: variant.gelato_sku -> fallback by size/color mapping -> config default
			product_uid = ""
			if variant and variant.gelato_sku:
				product_uid = variant.gelato_sku
			if not product_uid:
				product_uid = _lookup_gelato_uid(it.get("size"), it.get("color")) or current_app.config.get("DEFAULT_TEE_UID", "")
			if not product_uid:
				product_uid = "apparel_product_gca_t-shirt_gsc_crewneck_gcu_unisex_gqa_classic_gsi_s_gco_white_gpr_4-4"
			order_item = OrderItem(
				order_id=order.id,
				product_id=product.id if product else None,
				variant_id=variant.id if variant else None,
				title=it.get("title"),
				quantity=int(it.get("quantity", 1)),
				unit_price=Decimal(str(it.get("price", 0))),
				product_uid=product_uid,
			)
			db.session.add(order_item)

		# Add shipping (ground free). Use selected price from client if provided
		ship_uid = (data.get("shipment_method_uid") or "").strip().lower()
		shipping_cents = 0
		if ship_uid and ship_uid not in ("economy", "free", "free_3_5"):
			try:
				shipping_cents = int(round(float(data.get("shipping_price", 0)) * 100))
			except Exception:
				shipping_cents = 0
		total_cents = amount_cents + shipping_cents
		# Create PaymentIntent
		pi = stripe.PaymentIntent.create(amount=total_cents, currency=currency, automatic_payment_methods={"enabled": True})
		order.stripe_payment_intent_id = pi.id
		db.session.commit()
		return jsonify({"clientSecret": pi.client_secret, "orderId": order.id})
	except Exception as e:
		current_app.logger.exception("create-payment-intent failed")
		# Rollback any partial transaction
		try:
			db.session.rollback()
		except Exception:
			pass
		return jsonify({"error": str(e)}), 500


@stripe_bp.post("/webhooks/stripe")
def stripe_webhook():
	payload = request.data
	sig_header = request.headers.get("Stripe-Signature", "")
	endpoint_secret = current_app.config["STRIPE_WEBHOOK_SECRET"]
	try:
		event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
	except Exception as e:
		return (str(e), 400)

	if event["type"] == "payment_intent.succeeded":
		pi = event["data"]["object"]
		order = Order.query.filter_by(stripe_payment_intent_id=pi["id"]).first()
		if not order:
			return ("order not found", 200)
		order.status = "paid"
		# Persist receipt_email to shipping address for loyalty linkage
		receipt = pi.get("receipt_email") or ""
		try:
			if receipt and order.shipping_address and not order.shipping_address.email:
				order.shipping_address.email = receipt
				db.session.flush()
		except Exception:
			pass
		# Record referral commission if any
		try:
			# Look up referral code stashed in session mapping (best-effort: client-side session may not be present here)
			# Fallback to server-side files by reading the mapping file keyed by order id if we later store it elsewhere.
			ref_code = None
			# Try to peek at a transient cookie-backed session mapping if available (rare in webhook context)
			ref_map = session.get("_ref_orders") or {}
			ref_code = ref_map.get(str(order.id))
			# Persist to ledger if we have a code
			if ref_code:
				base_dir = os.path.join(os.path.dirname(__file__))
				data_dir = os.path.join(os.path.dirname(base_dir), "data")
				os.makedirs(data_dir, exist_ok=True)
				ledger_path = os.path.join(data_dir, "referrals_ledger.json")
				try:
					with open(ledger_path, "r", encoding="utf-8") as f:
						rows = json.load(f) or []
				except Exception:
					rows = []
				commission = float(order.total_amount or 0) * 0.10  # 10% commission
				rows.append({
					"order_id": order.id,
					"code": ref_code,
					"commission": round(commission, 2),
					"status": "earned",
					"created_at": datetime.utcnow().isoformat() + "Z",
				})
				with open(ledger_path, "w", encoding="utf-8") as f:
					json.dump(rows, f, ensure_ascii=False, indent=2)
		except Exception:
			pass

		# Email customer confirmation (best-effort)
		try:
			email_to = order.shipping_address.email if order.shipping_address else ""
			if email_to:
				# Build templated HTML
				from flask import render_template as _rt
				currency = order.currency or current_app.config.get("STORE_CURRENCY", "USD")
				subtotal = sum([(oi.unit_price or 0) * (oi.quantity or 1) for oi in order.items])
				shipping_amount = 0
				amount_paid = float(order.total_amount or 0)
				confirm_url = urljoin(current_app.config.get("BASE_URL", ""), f"/order/confirm/{order.id}")
				html = _rt("email_order_confirmation.html", order=order, items=order.items, subtotal=float(subtotal), shipping=float(shipping_amount), amount_paid=amount_paid, currency=currency, confirm_url=confirm_url)
				send_email_via_sendgrid(email_to, f"Order #{order.id} confirmed", html)
		except Exception:
			pass

		# Build Gelato draft order
		client = GelatoClient()
		items = []
		for oi in order.items:
			prod = db.session.get(Product, oi.product_id) if oi.product_id else None
			file_url = "https://cdn-origin.gelato-api-dashboard.ie.live.gelato.tech/docs/sample-print-files/logo.png"
			if prod and prod.design:
				if getattr(prod.design, 'image_url', None):
					file_url = _absolute_url(prod.design.image_url)
				elif prod.design.preview_url:
					file_url = _absolute_url(prod.design.preview_url)
			# Ensure we have a valid productUid; if missing, try to recompute from variant size/color
			product_uid = oi.product_uid or ""
			if not product_uid:
				try:
					v = db.session.get(Variant, oi.variant_id) if oi.variant_id else None
					product_uid = (v.gelato_sku if (v and v.gelato_sku) else "")
				except Exception:
					product_uid = ""
			if not product_uid:
				product_uid = current_app.config.get("DEFAULT_TEE_UID", "")
			items.append({
				"itemReferenceId": f"{order.id}-{oi.id}",
				"productUid": product_uid,
				"files": [ {"type": "default", "url": file_url} ],
				"quantity": int(oi.quantity),
			})
		payload = {
			"orderType": "draft",
			"orderReferenceId": order.stripe_payment_intent_id,
			"customerReferenceId": pi.get("receipt_email") or "",
			"currency": order.currency,
			"items": items,
			"shipmentMethodUid": order.shipment_method_uid or current_app.config.get("DEFAULT_SHIPMENT_METHOD", "express"),
			"shippingAddress": {
				"companyName": order.shipping_address.company_name or "",
				"firstName": order.shipping_address.first_name or "",
				"lastName": order.shipping_address.last_name or "",
				"addressLine1": order.shipping_address.address_line1 or "",
				"addressLine2": order.shipping_address.address_line2 or "",
				"state": order.shipping_address.state or "",
				"city": order.shipping_address.city or "",
				"postCode": order.shipping_address.post_code or "",
				"country": order.shipping_address.country or "US",
				"email": order.shipping_address.email or "",
				"phone": order.shipping_address.phone or "",
			},
		}
		try:
			resp = client.create_order(payload)
			order.gelato_order_id = resp.get("id")
			order.status = "submitted"
			db.session.commit()
		except Exception:
			order.status = "failed"
			db.session.commit()
			# Even if Gelato fails, redirect user to confirmation
			return ("gelato order failed", 200)

	# Handle subscription renewals: create Gelato order after successful invoice payment
	if event["type"] in ("invoice.payment_succeeded",):
		invoice = event["data"]["object"]
		try:
			# Extract subscription and customer details
			customer_email = invoice.get("customer_email") or ""
			# Build a Gelato order using metadata stored on the price/product in the first line
			lines = (invoice.get("lines", {}) or {}).get("data", [])
			first = lines[0] if lines else {}
			# Try to get product metadata from Stripe Product via Price
			meta = {}
			try:
				if first.get("price", {}).get("id"):
					price_obj = stripe.Price.retrieve(first["price"]["id"])  # may contain product
					if price_obj and price_obj.get("product"):
						product_obj = stripe.Product.retrieve(price_obj["product"])
						meta = product_obj.get("metadata") or {}
			except Exception:
				meta = {}

			# Map metadata to a variant/product if present
			product_id = int(meta.get("product_id") or 0) if meta.get("product_id") else None
			size = (meta.get("size") or "")
			color = (meta.get("color") or "")

			# Resolve a variant
			variant = None
			product = None
			if product_id:
				product = db.session.get(Product, product_id)
				if product:
					qv = [v for v in (product.variants or []) if (not size or (v.size or "") == size) and (not color or (v.color or "") == color)]
					variant = qv[0] if qv else None

			# Build shipping from invoice shipping details if present; fallback empty US
			addr = (invoice.get("customer_shipping") or {}).get("address") if invoice.get("customer_shipping") else None
			shipping = {
				"companyName": "",
				"firstName": (invoice.get("customer_name") or "")[:50],
				"lastName": "",
				"addressLine1": (addr.get("line1") if addr else ""),
				"addressLine2": (addr.get("line2") if addr else ""),
				"state": (addr.get("state") if addr else ""),
				"city": (addr.get("city") if addr else ""),
				"postCode": (addr.get("postal_code") if addr else ""),
				"country": (addr.get("country") if addr else "US") or "US",
				"email": customer_email or "",
				"phone": "",
			}

			client = GelatoClient()
			product_uid = (variant.gelato_sku if variant and variant.gelato_sku else current_app.config.get("DEFAULT_TEE_UID", ""))
			items = [{
				"itemReferenceId": f"sub-{invoice.get('id')}",
				"productUid": product_uid,
				"files": [{"type": "default", "url": current_app.config.get("BASE_URL", "") + "/static/uploads/2600.png"}],
				"quantity": 1,
			}]
			payload = {
				"orderType": "draft",
				"orderReferenceId": invoice.get("id"),
				"customerReferenceId": customer_email,
				"currency": (invoice.get("currency") or "usd").upper(),
				"items": items,
				"shipmentMethodUid": current_app.config.get("DEFAULT_SHIPMENT_METHOD", "express"),
				"shippingAddress": shipping,
			}
			try:
				client.create_order(payload)
			except Exception:
				pass
		except Exception:
			pass

	# On success events, we can't redirect here. The client side should poll and navigate.
	return ("", 200)

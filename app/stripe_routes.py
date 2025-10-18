import os
import stripe
from flask import Blueprint, current_app, jsonify, request, session
from .extensions import db
from .gelato_client import GelatoClient
from .models import Order, OrderItem, Address, Variant, Product
from urllib.parse import urljoin
from decimal import Decimal

stripe_bp = Blueprint("stripe", __name__)


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


@stripe_bp.post("/api/create-payment-intent")
def create_payment_intent():
	try:
		if not current_app.config.get("STRIPE_SECRET_KEY") or not current_app.config.get("STRIPE_PUBLISHABLE_KEY"):
			return jsonify({"error": "Stripe not configured"}), 400
		cart = session.get("cart") or {"items": []}
		amount_cents = _compute_cart_total(cart)
		currency = current_app.config.get("STORE_CURRENCY", "USD").lower()
		if amount_cents <= 0:
			return jsonify({"error": "Cart is empty"}), 400

		# Create a local order (pending)
		shipping = Address(
			company_name="Example",
			first_name="Test",
			last_name="User",
			address_line1="451 Clarkson Ave",
			address_line2="Brooklyn",
			state="NY",
			city="New York",
			post_code="11203",
			country="US",
			email="test@example.com",
			phone="123456789",
		)
		db.session.add(shipping)
		db.session.flush()
		order = Order(
			status="pending",
			currency=currency.upper(),
			total_amount=Decimal(amount_cents) / 100,
			shipment_method_uid=current_app.config.get("DEFAULT_SHIPMENT_METHOD", "express"),
			shipping_address_id=shipping.id,
		)
		db.session.add(order)
		db.session.flush()

		# Items
		for it in cart.get("items", []):
			variant = db.session.get(Variant, int(it.get("variant_id"))) if it.get("variant_id") else None
			product = db.session.get(Product, int(it.get("product_id"))) if it.get("product_id") else None
			product_uid = variant.gelato_sku if variant and variant.gelato_sku else "apparel_product_gca_t-shirt_gsc_crewneck_gcu_unisex_gqa_classic_gsi_s_gco_white_gpr_4-4"
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

		# Create PaymentIntent
		pi = stripe.PaymentIntent.create(amount=amount_cents, currency=currency, automatic_payment_methods={"enabled": True})
		order.stripe_payment_intent_id = pi.id
		db.session.commit()
		return jsonify({"clientSecret": pi.client_secret})
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
			items.append({
				"itemReferenceId": f"{order.id}-{oi.id}",
				"productUid": oi.product_uid,
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
			return ("gelato order failed", 200)

	return ("", 200)

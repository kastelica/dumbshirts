from flask import Blueprint, request, jsonify, session, current_app
from .gelato_client import GelatoClient
import requests
from urllib.parse import urljoin
from .models import Product
from datetime import datetime

api_bp = Blueprint("api", __name__)


def _absolute_url(url: str) -> str:
	if not url:
		return ""
	if url.startswith("http://") or url.startswith("https://"):
		return url
	base = current_app.config.get("BASE_URL", "http://localhost:5000")
	return urljoin(base, url)


@api_bp.get("/api/shipment-methods")
def shipment_methods():
	country = request.args.get("country", "US")
	client = GelatoClient()
	try:
		resp = requests.get(
			"https://shipment.gelatoapis.com/v1/shipment-methods",
			headers=client.headers,
			params={"country": country},
			timeout=20,
		)
		resp.raise_for_status()
		data = resp.json()
		return jsonify(data)
	except Exception as e:
		return jsonify({"error": str(e)}), 400


@api_bp.post("/api/gelato/test-order")
def gelato_test_order():
	"""Submit a draft Gelato order directly from the cart (bypasses Stripe)."""
	client = GelatoClient()
	if not client.api_key:
		return jsonify({"error": "Gelato not configured"}), 400
	cart = session.get("cart") or {"items": []}
	if not cart.get("items"):
		return jsonify({"error": "Cart is empty"}), 400
	body = request.get_json(silent=True) or {}
	shipment_uid = body.get("shipment_method_uid") or current_app.config.get("DEFAULT_SHIPMENT_METHOD", "express")
	items = []
	used_files = []
	first_title = None
	base_url = current_app.config.get("BASE_URL", "http://localhost:5000")
	for it in cart.get("items", []):
		prod = Product.query.get(int(it.get("product_id"))) if it.get("product_id") else None
		if prod and not first_title:
			first_title = prod.title
		file_url = ""
		if prod and prod.design:
			if getattr(prod.design, 'image_url', None):
				file_url = _absolute_url(prod.design.image_url)
			elif prod.design.preview_url:
				file_url = _absolute_url(prod.design.preview_url)
		if "localhost" in base_url or "127.0.0.1" in base_url or not file_url:
			file_url = "https://cdn-origin.gelato-api-dashboard.ie.live.gelato.tech/docs/sample-print-files/logo.png"
		product_uid = it.get("product_uid") or current_app.config.get("DEFAULT_TEE_UID")
		items.append({
			"itemReferenceId": f"test-{it.get('variant_id')}",
			"productUid": product_uid,
			"files": [{"type": "default", "url": file_url}],
			"quantity": int(it.get("quantity", 1)),
		})
		used_files.append(file_url)
	date_str = datetime.utcnow().strftime("%Y-%m-%d")
	reference_base = first_title or "trendmerch"
	order_ref = f"tm-{date_str}-{reference_base[:40]}"
	payload = {
		"orderType": "draft",
		"orderReferenceId": order_ref,
		"customerReferenceId": "local-tester",
		"currency": current_app.config.get("STORE_CURRENCY", "USD"),
		"items": items,
		"shipmentMethodUid": shipment_uid,
		"shippingAddress": {
			"companyName": "Example",
			"firstName": "Test",
			"lastName": "User",
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
		resp = client.create_order(payload)
		return jsonify({"ok": True, "gelato": resp, "orderReferenceId": order_ref, "files": used_files, "base_url": base_url})
	except requests.HTTPError as he:
		r = he.response
		return jsonify({"error": r.text if r is not None else str(he)}), 400
	except Exception as e:
		return jsonify({"error": str(e)}), 400
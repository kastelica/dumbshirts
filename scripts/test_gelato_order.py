import os
import sys
import json
import argparse
import requests

# Allow running directly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.gelato_client import GelatoClient

DEFAULT_PRODUCT_UID = "apparel_product_gca_t-shirt_gsc_crewneck_gcu_unisex_gqa_classic_gsi_s_gco_white_gpr_4-4"
DEFAULT_FILE_URL = "https://cdn-origin.gelato-api-dashboard.ie.live.gelato.tech/docs/sample-print-files/logo.png"


def build_payload(order_type: str, order_id: str, customer_id: str, product_uid: str, shipment: str, qty: int) -> dict:
	return {
		"orderType": order_type,
		"orderReferenceId": order_id,
		"customerReferenceId": customer_id,
		"currency": "USD",
		"items": [
			{
				"itemReferenceId": f"{order_id}-item-1",
				"productUid": product_uid,
				"files": [
					{"type": "default", "url": DEFAULT_FILE_URL},
					{"type": "back", "url": DEFAULT_FILE_URL},
				],
				"quantity": qty,
			}
		],
		"shipmentMethodUid": shipment,
		"shippingAddress": {
			"companyName": "Example",
			"firstName": "Paul",
			"lastName": "Smith",
			"addressLine1": "451 Clarkson Ave",
			"addressLine2": "Brooklyn",
			"state": "NY",
			"city": "New York",
			"postCode": "11203",
			"country": "US",
			"email": "apisupport@gelato.com",
			"phone": "123456789"
		},
		"returnAddress": {
			"companyName": "My company",
			"addressLine1": "3333 Saint Marys Avenue",
			"addressLine2": "Brooklyn",
			"state": "NY",
			"city": "New York",
			"postCode": "13202",
			"country": "US",
			"email": "apisupport@gelato.com",
			"phone": "123456789"
		},
		"metadata": [
			{"key": "env", "value": "local-test"}
		]
	}


def main() -> int:
	parser = argparse.ArgumentParser(description="Create a test order via Gelato Order API")
	parser.add_argument("--api-key", dest="api_key", default=None, help="Override GELATO_API_KEY for this run")
	parser.add_argument("--order-type", dest="order_type", default="draft", choices=["order", "draft"], help="Order type (order or draft)")
	parser.add_argument("--order-id", dest="order_id", default="test-order-001", help="Order reference id")
	parser.add_argument("--customer-id", dest="customer_id", default="test-customer-001", help="Customer reference id")
	parser.add_argument("--product-uid", dest="product_uid", default=DEFAULT_PRODUCT_UID, help="Gelato productUid")
	parser.add_argument("--shipment", dest="shipment", default="express", help="shipmentMethodUid (e.g., dhl_express_worldwide)")
	parser.add_argument("--qty", dest="qty", type=int, default=1, help="Quantity")
	args = parser.parse_args()

	api_key = (args.api_key or os.environ.get("GELATO_API_KEY", "")).strip()
	if not api_key:
		print("GELATO_API_KEY missing. Pass --api-key or set env var.")
		return 2
	client = GelatoClient(api_key)
	payload = build_payload(args.order_type, args.order_id, args.customer_id, args.product_uid, args.shipment, args.qty)
	try:
		resp = client.create_order(payload)
		print(json.dumps(resp, indent=2))
		return 0
	except requests.HTTPError as he:
		r = getattr(he, "response", None)
		print("order HTTPError:", he)
		if r is not None:
			print("status:", r.status_code)
			print("body:", r.text[:1000])
			if r.status_code == 400:
				print("Hint: Complete company profile & billing in Gelato dashboard, or try --order-type draft.")
		return 1
	except Exception as e:
		print("order error:", e)
		return 1


if __name__ == "__main__":
	sys.exit(main())

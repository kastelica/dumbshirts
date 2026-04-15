import os
import sys
import json
import socket
import argparse
import requests

SHIPMENT_HOST = "https://shipment.gelatoapis.com/v1"


def resolve(hostname: str) -> list[str]:
	try:
		infos = socket.getaddrinfo(hostname, 443, proto=socket.IPPROTO_TCP)
		return sorted({ai[4][0] for ai in infos})
	except Exception:
		return []


def mask_key(k: str) -> str:
	k = k or ""
	return (k[:4] + "***" + k[-4:]) if len(k) > 8 else "*" * len(k)


def main() -> int:
	parser = argparse.ArgumentParser(description="Test Gelato shipment methods API")
	parser.add_argument("--api-key", dest="api_key", default=None, help="Override GELATO_API_KEY for this run")
	parser.add_argument("--country", dest="country", default=None, help="Destination country code, e.g. US")
	args = parser.parse_args()

	api_key = (args.api_key or os.environ.get("GELATO_API_KEY", "")).strip()
	print("GELATO_API_KEY set:", "yes" if api_key else "no")
	print("key masked:", mask_key(api_key))

	hostname = SHIPMENT_HOST.split("//",1)[1]
	print("dns:", ", ".join(resolve(hostname)) or "<unresolved>")

	headers = {"X-API-KEY": api_key, "Accept": "application/json"}
	params = {}
	if args.country:
		params["country"] = args.country

	url = f"{SHIPMENT_HOST}/shipment-methods"
	try:
		resp = requests.get(url, headers=headers, params=params, timeout=20)
		print("status:", resp.status_code)
		if resp.status_code != 200:
			print("text:", resp.text[:400])
			return 1
		data = resp.json()
		items = []
		if isinstance(data, list):
			items = data
		elif isinstance(data, dict):
			items = data.get("items", []) or data.get("shipmentMethods", []) or []
		print("methods:", len(items))
		for m in items[:10]:
			uid = (m.get("uid") or m.get("shipmentMethodUid") or m.get("id") or "?") if isinstance(m, dict) else "?"
			name = (m.get("name") or m.get("shipmentMethodName") or "?") if isinstance(m, dict) else "?"
			print("-", uid, ":", name)
		return 0
	except Exception as e:
		print("error:", e)
		return 2


if __name__ == "__main__":
	sys.exit(main())

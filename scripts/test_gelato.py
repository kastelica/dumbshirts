import os
import sys
import json
import socket
import requests
import argparse

# Allow running directly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.gelato_client import GelatoClient

HOSTS = [
	"https://api.gelatoapis.com/v4",   # Catalog API (correct)
	"https://order.gelatoapis.com/v4", # Order API (correct)
	"https://api.gelato.com/v4",       # Legacy/incorrect for auth (expect 403)
]


def resolve(hostname: str) -> list[str]:
	try:
		infos = socket.getaddrinfo(hostname, 443, proto=socket.IPPROTO_TCP)
		ips = sorted({ai[4][0] for ai in infos})
		return ips
	except Exception:
		return []


def mask_key(k: str) -> str:
	k = k or ""
	if len(k) <= 8:
		return "*" * len(k)
	return f"{k[:4]}***{k[-4:]}"


def main() -> int:
	parser = argparse.ArgumentParser(description="Test Gelato API connectivity and auth")
	parser.add_argument("--api-key", dest="api_key", default=None, help="Override GELATO_API_KEY for this run")
	args = parser.parse_args()

	api_key = (args.api_key or os.environ.get("GELATO_API_KEY", "")).strip()
	print("GELATO_API_KEY set:", "yes" if api_key else "no")
	print("key masked:", mask_key(api_key))

	headers = {"X-API-KEY": api_key, "Accept": "application/json"}
	overall_ok = False
	for base in HOSTS:
		hostname = base.split("//",1)[1].split("/",1)[0]
		ips = resolve(hostname)
		print(f"host: {base}")
		print("dns:", (", ".join(ips) if ips else "<unresolved>"))
		try:
			path = "/catalog/products?limit=1" if "api.gelato" in hostname and "order." not in hostname else "/orders"
			method = "GET" if "api.gelato" in hostname and "order." not in hostname else "HEAD"
			url = base + path
			if method == "GET":
				resp = requests.get(url, headers=headers, timeout=20)
			else:
				resp = requests.head(url, headers=headers, timeout=20)
			print("status:", resp.status_code)
			if resp.status_code == 200 and method == "GET":
				data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
				items = data.get("items", []) if isinstance(data, dict) else []
				print("sample_count:", len(items))
				overall_ok = True
			elif resp.status_code in (401, 403):
				print("auth error text:", resp.text[:200])
			else:
				print("text:", resp.text[:200])
		except Exception as e:
			print("error:", e)

	# Also test via client.verify()
	print("\nclient.verify():")
	client = GelatoClient(api_key)
	ok, debug = client.verify()
	print("ok:", ok)
	print(json.dumps(debug, indent=2))
	return 0 if overall_ok or ok else 1


if __name__ == "__main__":
	sys.exit(main())

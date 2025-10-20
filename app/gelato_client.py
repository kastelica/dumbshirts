import os
from typing import Dict, Any, List, Optional, Tuple
import requests


class GelatoClient:
	HOSTS = [
		"https://api.gelatoapis.com/v4",
		"https://api.gelato.com/v4",
	]
	ORDER_HOST = "https://order.gelatoapis.com/v4"

	def __init__(self, api_key: str | None = None):
		self.api_key = api_key or os.getenv("GELATO_API_KEY", "").strip()

	@property
	def headers(self) -> Dict[str, str]:
		# Gelato expects the API key via X-API-KEY
		return {
			"X-API-KEY": self.api_key,
			"Content-Type": "application/json",
			"Accept": "application/json",
		}

	def _get(self, host: str, path: str, params: Optional[Dict[str, str]] = None) -> requests.Response:
		url = f"{host}{path}"
		return requests.get(url, headers=self.headers, params=params or {}, timeout=20)

	def _head(self, host: str, path: str) -> requests.Response:
		url = f"{host}{path}"
		return requests.head(url, headers=self.headers, timeout=20)

	def verify(self) -> Tuple[bool, Dict[str, Any]]:
		"""Verify by trying Catalog (preferred) then Order API (fallback)."""
		if not self.api_key:
			return False, {"error": "missing_api_key"}
		debug: Dict[str, Any] = {}
		# Try Catalog host(s)
		for host in self.HOSTS:
			try:
				resp = self._get(host, "/catalog/products", params={"limit": "1"})
				entry = {"catalog_host": host, "catalog_status": resp.status_code}
				if resp.status_code == 200:
					data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
					entry["catalog_sample_count"] = len(data.get("items", [])) if isinstance(data, dict) else 0
					debug.update(entry)
					return True, debug
				else:
					entry["catalog_text"] = resp.text[:200]
					debug.update(entry)
			except Exception as e:
				debug.update({"catalog_host": host, "catalog_error": str(e)})
		# Fallback: Order API HEAD
		try:
			resp = self._head(self.ORDER_HOST, "/orders")
			debug.update({"order_host": self.ORDER_HOST, "order_status": resp.status_code})
			if 200 <= resp.status_code < 500:
				# Host reachable and key accepted for HEAD even if no body
				return True, debug
		except Exception as e:
			debug.update({"order_host": self.ORDER_HOST, "order_error": str(e)})
		return False, debug

	def list_products(self, limit: int = 10, page_token: Optional[str] = None) -> Dict[str, Any]:
		params = {"limit": str(limit)}
		if page_token:
			params["pageToken"] = page_token
		# try hosts until success
		last_exc: Optional[Exception] = None
		for host in self.HOSTS:
			try:
				resp = self._get(host, "/catalog/products", params=params)
				resp.raise_for_status()
				return resp.json()
			except Exception as e:
				last_exc = e
		if last_exc:
			raise last_exc
		raise RuntimeError("Failed to list products from Gelato")

	def get_product(self, product_uid: str) -> Dict[str, Any]:
		"""Fetch a single product by productUid from the Catalog API."""
		last_exc: Optional[Exception] = None
		for host in self.HOSTS:
			try:
				resp = self._get(host, f"/catalog/products/{product_uid}")
				resp.raise_for_status()
				return resp.json()
			except Exception as e:
				last_exc = e
		if last_exc:
			raise last_exc
		raise RuntimeError("Failed to fetch product from Gelato")

	def create_order(self, order: Dict[str, Any]) -> Dict[str, Any]:
		"""Create an order via Gelato Order API."""
		if not self.api_key:
			raise RuntimeError("Missing GELATO_API_KEY")
		url = f"{self.ORDER_HOST}/orders"
		resp = requests.post(url, headers=self.headers, json=order, timeout=30)
		try:
			resp.raise_for_status()
		except requests.HTTPError as e:
			# Surface response body for easier debugging in admin UI
			text = ""
			try:
				text = resp.text
			except Exception:
				text = ""
			raise RuntimeError(f"{resp.status_code} {text[:800]}") from e
		return resp.json()

	def get_order(self, order_id: str) -> Dict[str, Any]:
		"""Fetch a single order by ID from the Order API."""
		url = f"{self.ORDER_HOST}/orders/{order_id}"
		resp = requests.get(url, headers=self.headers, timeout=30)
		resp.raise_for_status()
		return resp.json()

	def get_shipping_rates(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
		"""Request shipping rates (endpoint may vary; this is a placeholder call)."""
		try:
			url = f"{self.ORDER_HOST}/shipping/rates"
			resp = requests.post(url, headers=self.headers, json=payload, timeout=30)
			resp.raise_for_status()
			data = resp.json()
			if isinstance(data, dict):
				return data.get("rates", []) or []
			return []
		except Exception:
			return []

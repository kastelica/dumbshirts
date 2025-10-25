from flask import Blueprint, request, redirect, url_for, session, render_template
from .models import Variant, Product
from decimal import Decimal

cart_bp = Blueprint("cart", __name__)


def _get_cart() -> dict:
	cart = session.get("cart")
	if not cart:
		cart = {"items": []}
		session["cart"] = cart
	return cart


def _save_cart(cart: dict) -> None:
	session["cart"] = cart
	session.modified = True


@cart_bp.post("/cart/add")
def add_to_cart():
	variant_id = request.form.get("variant_id")
	color_from_form = (request.form.get("color") or "").strip()
	qty = int(request.form.get("quantity", "1"))
	buy_now = request.form.get("buy_now") == "1"
	if not variant_id:
		return redirect(request.referrer or url_for("main.index"))
	variant = Variant.query.get(int(variant_id))
	if not variant:
		return redirect(request.referrer or url_for("main.index"))
	product: Product = variant.product
	cart = _get_cart()
	# merge if same variant exists
	for it in cart["items"]:
		if it["variant_id"] == variant.id:
			it["quantity"] += qty
			_save_cart(cart)
			return redirect(url_for("main.checkout") if buy_now else url_for("cart.view_cart"))
	cart["items"].append({
		"product_id": product.id,
		"variant_id": variant.id,
		"title": product.title,
		"slug": product.slug,
		# Store discounted sale price (5% off) as price, keep original as orig_price
		"orig_price": float(product.price),
		"price": float((product.price * Decimal("95")) / Decimal("100")),
		"currency": product.currency,
		"quantity": qty,
		"image": (product.design.preview_url if (product.design and product.design.preview_url) else ""),
		"product_uid": (variant.gelato_sku or ""),
		"color": (color_from_form or (variant.color or "")),
	})
	_save_cart(cart)
	return redirect(url_for("main.checkout") if buy_now else url_for("cart.view_cart"))


@cart_bp.post("/cart/update")
def update_cart():
	variant_id = int(request.form.get("variant_id", "0"))
	qty = max(0, int(request.form.get("quantity", "1")))
	cart = _get_cart()
	new_items = []
	for it in cart["items"]:
		if it["variant_id"] == variant_id:
			if qty > 0:
				it["quantity"] = qty
				new_items.append(it)
		else:
			new_items.append(it)
	cart["items"] = new_items
	_save_cart(cart)
	return redirect(url_for("cart.view_cart"))


@cart_bp.post("/cart/remove")
def remove_from_cart():
	variant_id = int(request.form.get("variant_id", "0"))
	cart = _get_cart()
	cart["items"] = [it for it in cart["items"] if it["variant_id"] != variant_id]
	_save_cart(cart)
	return redirect(url_for("cart.view_cart"))


@cart_bp.post("/cart/clear")
def clear_cart():
	cart = _get_cart()
	cart["items"] = []
	# Do not clear applied coupon on clear
	_save_cart(cart)
	return redirect(url_for("cart.view_cart"))


@cart_bp.post("/cart/apply-coupon")
def apply_coupon():
	"""Apply a coupon code to the cart (hardcoded: 5off => 5% off)."""
	code = (request.form.get("coupon") or "").strip().lower()
	cart = _get_cart()
	if code == "5off":
		cart["coupon"] = {"code": code, "percent": 5}
	else:
		# Remove coupon if invalid/empty
		cart.pop("coupon", None)
	_save_cart(cart)
	# Return user to the page they came from (checkout or cart)
	return redirect(request.referrer or url_for("cart.view_cart"))


@cart_bp.get("/cart")
def view_cart():
	cart = _get_cart()
	# compute totals
	subtotal = Decimal("0.00")
	for it in cart["items"]:
		subtotal += Decimal(str(it["price"])) * it["quantity"]
	discount = Decimal("0.00")
	coupon = cart.get("coupon") or {}
	try:
		pct = Decimal(str(coupon.get("percent", 0)))
		discount = (subtotal * pct) / Decimal("100") if pct else Decimal("0.00")
	except Exception:
		discount = Decimal("0.00")
	total = (subtotal - discount).quantize(Decimal("0.01"))
	return render_template("cart.html", cart=cart, subtotal=subtotal, discount=discount, total=total, currency="USD")

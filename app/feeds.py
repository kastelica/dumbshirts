from flask import Response, current_app
from xml.etree.ElementTree import Element, SubElement, tostring
import hashlib
import csv
import io


def _feed_base_url() -> str:
	"""Return the canonical public base URL for feed metadata."""
	base = str(current_app.config.get("BASE_URL", "https://roastcotton.com")).strip()
	if not base:
		base = "https://roastcotton.com"
	base = base.replace("http://dumbshirts.store", "https://roastcotton.com")
	base = base.replace("https://dumbshirts.store", "https://roastcotton.com")
	return base.rstrip("/")


def render_google_shopping_feed(items):
	rss = Element("rss", attrib={"version": "2.0", "xmlns:g": "http://base.google.com/ns/1.0"})
	channel = SubElement(rss, "channel")
	base_url = _feed_base_url()
	SubElement(channel, "title").text = "Roast Cotton Products"
	SubElement(channel, "link").text = base_url
	SubElement(channel, "description").text = "Roast Cotton trending POD products"

	for item in items:
		it = SubElement(channel, "item")
		SubElement(it, "title").text = item.get("title", "")
		SubElement(it, "link").text = item.get("link", "")
		item_description = (item.get("description") or "").strip()
		if not item_description:
			item_description = f"{item.get('title', 'Product')} — available at Roast Cotton."
		SubElement(it, "description").text = item_description
		SubElement(it, "g:id").text = str(item.get("id", ""))
		# Manufacturer Part Number - use our item id as requested
		SubElement(it, "g:mpn").text = str(item.get("id", ""))
		SubElement(it, "g:price").text = f"{item.get('price', '0.00')} USD"
		sp = item.get("sale_price")
		if sp:
			SubElement(it, "g:sale_price").text = f"{sp} USD"
		# Cost of goods sold
		cogs = item.get("cost_of_goods_sold")
		if cogs:
			SubElement(it, "g:cost_of_goods_sold").text = f"{cogs} USD"
		# Auto pricing minimum price
		min_price = item.get("auto_pricing_min_price")
		if min_price:
			SubElement(it, "g:auto_pricing_min_price").text = f"{min_price} USD"
		SubElement(it, "g:availability").text = item.get("availability", "in stock")
		SubElement(it, "g:condition").text = "new"
		SubElement(it, "g:identifier_exists").text = "FALSE"
		img = item.get("image")
		if img:
			SubElement(it, "g:image_link").text = img
		# Additional images (repeat up to 10)
		adds = item.get("additional_images") or []
		try:
			for a in adds[:10]:
				if a:
					SubElement(it, "g:additional_image_link").text = a
		except Exception:
			pass
		# Non-standard but useful: include product video link if present
		video = item.get("video")
		if video:
			SubElement(it, "g:video_link").text = video
		# Google Shopping category and product type
		gcat = item.get("google_product_category")
		if gcat:
			SubElement(it, "g:google_product_category").text = gcat
		ptype = item.get("product_type")
		if ptype:
			SubElement(it, "g:product_type").text = ptype
		# Checkout URL (account/product level). Not an official tag; expose for account ingestion or debugging
		chk = item.get("checkout_link_template")
		if chk:
			SubElement(it, "g:checkout_link_template").text = chk
		# US-only shipping
		ship = item.get("shipping") or {}
		country = ship.get("country")
		if country:
			ship_el = SubElement(it, "g:shipping")
			SubElement(ship_el, "g:country").text = country
		brand = item.get("brand")
		if brand:
			SubElement(it, "g:brand").text = brand
		age = item.get("age_group")
		if age:
			SubElement(it, "g:age_group").text = age
		color = item.get("color")
		if color:
			SubElement(it, "g:color").text = color
		# Material (constant for tees)
		SubElement(it, "g:material").text = "100% cotton (preshrunk)"
		gender = item.get("gender")
		if gender:
			SubElement(it, "g:gender").text = gender
		size = item.get("size")
		if size:
			SubElement(it, "g:size").text = size
		# Subscription cost (for subscription landing page items only)
		sub = item.get("subscription_cost")
		if sub:
			# Format as "month:12:35.00 EUR" per Google requirements
			period = sub.get("period", "month")
			period_length = sub.get("period_length", 1)
			amount = sub.get("amount", "15.00 USD")
			# Extract currency from amount if present, default to USD
			currency = "USD"
			if " " in amount:
				currency = amount.split(" ")[-1]
				amount_value = amount.split(" ")[0]
			else:
				amount_value = amount
			subscription_cost_text = f"{period}:{period_length}:{amount_value} {currency}"
			SubElement(it, "g:subscription_cost").text = subscription_cost_text

	xml_bytes = tostring(rss, encoding="utf-8", xml_declaration=True)
	return Response(xml_bytes, content_type="application/xml; charset=utf-8")


def render_google_promotions_feed(promotions: list) -> Response:
	"""Render Google Promotions as Atom feed with g: namespace, per Google examples."""
	# Atom root with Google namespace
	root = Element("feed", attrib={
		"xmlns": "http://www.w3.org/2005/Atom",
		"xmlns:g": "http://base.google.com/ns/1.0",
	})
	SubElement(root, "title").text = "Promotion Feed"
	# Self link
	base = _feed_base_url()
	SubElement(root, "link", attrib={
		"rel": "self",
		"href": f"{base}/feeds/promotions.xml",
	})
	# Updated timestamp in Zulu time
	from datetime import datetime
	SubElement(root, "updated").text = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

	# Use configurable timezone offset (e.g., -08:00) for date windows
	tz_offset = str(current_app.config.get("PROMOTION_TZ_OFFSET", "-08:00"))

	for p in promotions:
		entry = SubElement(root, "entry")
		# Core required fields
		SubElement(entry, "g:promotion_id").text = str(p.get("promotion_id", ""))
		SubElement(entry, "g:long_title").text = p.get("long_title", "")

		# Effective dates
		ped = p.get("promotion_effective_dates")
		if not ped:
			start = (p.get("start_date") or "").strip()
			end = (p.get("end_date") or start).strip()
			if start:
				start_iso = f"{start}T00:00:00{tz_offset}"
				end_iso = f"{end}T23:59:59{tz_offset}" if end else f"{start}T23:59:59{tz_offset}"
				ped = f"{start_iso}/{end_iso}"
		SubElement(entry, "g:promotion_effective_dates").text = ped or ""

		# Display dates
		pdd = p.get("promotion_display_dates")
		if not pdd:
			ds = (p.get("display_start_date") or "").strip()
			de = (p.get("display_end_date") or ds).strip()
			if ds:
				ds_iso = f"{ds}T00:00:00{tz_offset}"
				de_iso = f"{de}T23:59:59{tz_offset}" if de else f"{ds}T23:59:59{tz_offset}"
				pdd = f"{ds_iso}/{de_iso}"
		if pdd:
			SubElement(entry, "g:promotion_display_dates").text = pdd

		# Offer type: always treat as generic_code promotions with a code
		percent_off = (p.get("percent_off") or "").strip()
		code = (p.get("generic_redemption_code") or "").strip()
		SubElement(entry, "g:offer_type").text = "generic_code"
		if percent_off:
			SubElement(entry, "g:coupon_value_type").text = "percent_off"
			# Google expects 'percent_off', not 'percentage_off'
			SubElement(entry, "g:percent_off").text = str(percent_off)
		# Coupon code (generic code for all customers)
		if code:
			SubElement(entry, "g:generic_redemption_code").text = code

		# Destinations
		dests = p.get("promotion_destination") or ["Shopping_ads", "Free_listings"]
		if isinstance(dests, str):
			dests = [dests]
		for d in dests:
			SubElement(entry, "g:promotion_destination").text = d

		# Applicability (always all products) and redemption channel
		SubElement(entry, "g:product_applicability").text = "all_products"
		SubElement(entry, "g:redemption_channel").text = p.get("redemption_channel") or "online"

		# (generic code handled above); no product-level filtering for promotions

		# Optional: promotion URL, audience
		if p.get("promotion_url"):
			SubElement(entry, "g:promotion_url").text = str(p.get("promotion_url"))
		if p.get("audience"):
			SubElement(entry, "g:audience").text = str(p.get("audience"))

	xml_bytes = tostring(root, encoding="utf-8", xml_declaration=True)
	return Response(xml_bytes, content_type="application/atom+xml; charset=utf-8")


def render_google_customer_match_feed(customers: list) -> Response:
	"""Render Google Ads Customer Match CSV feed.
	
	Format: Email (SHA-256), Phone (SHA-256), First Name (SHA-256), 
	Last Name (SHA-256), Country Code, Zip Code
	
	All PII fields are hashed with SHA-256. Email and names are lowercased and trimmed.
	Phone numbers are digits only.
	"""
	output = io.StringIO()
	writer = csv.writer(output)
	
	# Write CSV header
	writer.writerow([
		"Email", "Phone", "First Name", "Last Name", "Country Code", "Zip Code"
	])
	
	# Helper function to hash with SHA-256
	def hash_sha256(value: str) -> str:
		if not value:
			return ""
		return hashlib.sha256(value.encode('utf-8')).hexdigest()
	
	# Helper function to normalize phone (digits only)
	def normalize_phone(phone: str) -> str:
		if not phone:
			return ""
		# Remove all non-digit characters
		return ''.join(filter(str.isdigit, phone))
	
	# Write customer rows
	for customer in customers:
		email = customer.get("email", "").strip().lower()
		phone = normalize_phone(customer.get("phone", ""))
		first_name = customer.get("first_name", "").strip().lower()
		last_name = customer.get("last_name", "").strip().lower()
		country = customer.get("country", "").strip().upper()[:2]  # ISO 3166-1 alpha-2
		zip_code = customer.get("zip_code", "").strip()
		
		# Only include rows with at least email or phone
		if not email and not phone:
			continue
		
		# Hash PII fields
		hashed_email = hash_sha256(email) if email else ""
		hashed_phone = hash_sha256(phone) if phone else ""
		hashed_first_name = hash_sha256(first_name) if first_name else ""
		hashed_last_name = hash_sha256(last_name) if last_name else ""
		
		writer.writerow([
			hashed_email,
			hashed_phone,
			hashed_first_name,
			hashed_last_name,
			country,
			zip_code
		])
	
	csv_content = output.getvalue()
	output.close()
	
	return Response(
		csv_content,
		mimetype="text/csv",
		headers={"Content-Disposition": "attachment; filename=customer_match.csv"}
	)

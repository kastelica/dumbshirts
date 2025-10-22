from flask import Response, current_app
from xml.etree.ElementTree import Element, SubElement, tostring


def render_google_shopping_feed(items):
	rss = Element("rss", attrib={"version": "2.0", "xmlns:g": "http://base.google.com/ns/1.0"})
	channel = SubElement(rss, "channel")
	SubElement(channel, "title").text = "TrendMerch Products"
	# Use configured BASE_URL for channel link
	SubElement(channel, "link").text = current_app.config.get("BASE_URL", "http://localhost:5000")
	SubElement(channel, "description").text = "Trending POD products"

	for item in items:
		it = SubElement(channel, "item")
		SubElement(it, "title").text = item.get("title", "")
		SubElement(it, "link").text = item.get("link", "")
		SubElement(it, "description").text = item.get("description", "")
		SubElement(it, "g:id").text = str(item.get("id", ""))
		# Manufacturer Part Number - use our item id as requested
		SubElement(it, "g:mpn").text = str(item.get("id", ""))
		SubElement(it, "g:price").text = f"{item.get('price', '0.00')} USD"
		sp = item.get("sale_price")
		if sp:
			SubElement(it, "g:sale_price").text = f"{sp} USD"
		SubElement(it, "g:availability").text = item.get("availability", "in stock")
		SubElement(it, "g:condition").text = "new"
		SubElement(it, "g:identifier_exists").text = "FALSE"
		img = item.get("image")
		if img:
			SubElement(it, "g:image_link").text = img
		# Google Shopping category and product type
		gcat = item.get("google_product_category")
		if gcat:
			SubElement(it, "g:google_product_category").text = gcat
		ptype = item.get("product_type")
		if ptype:
			SubElement(it, "g:product_type").text = ptype
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
	base = current_app.config.get("BASE_URL", "http://localhost:5000").rstrip("/")
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

		# Offer type and value
		percent_off = (p.get("percent_off") or "").strip()
		code = (p.get("generic_redemption_code") or p.get("coupon_code") or "").strip()
		if code:
			SubElement(entry, "g:offer_type").text = "generic_code"
			SubElement(entry, "g:redemption_code_type").text = "GENERIC_CODE"
			SubElement(entry, "g:generic_redemption_code").text = code
		else:
			SubElement(entry, "g:offer_type").text = "no_code"
		if percent_off:
			SubElement(entry, "g:coupon_value_type").text = "percent_off"
			SubElement(entry, "g:percent_off").text = str(percent_off)

		# Destinations
		dests = p.get("promotion_destination") or ["Shopping_ads", "Free_listings"]
		if isinstance(dests, str):
			dests = [dests]
		for d in dests:
			SubElement(entry, "g:promotion_destination").text = d

		# Applicability and redemption channel
		SubElement(entry, "g:product_applicability").text = p.get("product_applicability") or ("specific_products" if p.get("product_ids") else "all_products")
		SubElement(entry, "g:redemption_channel").text = p.get("redemption_channel") or "online"

		# (generic code handled above)

		# Product filters
		ids_raw = p.get("product_ids") or ""
		if isinstance(ids_raw, str):
			parts = [s.strip() for s in ids_raw.split(",") if s.strip()]
		else:
			parts = ids_raw or []
		for pid in parts:
			pf = SubElement(entry, "g:product_filter")
			SubElement(pf, "g:item_id").text = str(pid)

		# Optional: promotion URL, audience
		if p.get("promotion_url"):
			SubElement(entry, "g:promotion_url").text = str(p.get("promotion_url"))
		if p.get("audience"):
			SubElement(entry, "g:audience").text = str(p.get("audience"))

	xml_bytes = tostring(root, encoding="utf-8", xml_declaration=True)
	return Response(xml_bytes, content_type="application/atom+xml; charset=utf-8")
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

	xml_bytes = tostring(rss)
	return Response(xml_bytes, content_type="application/xml")

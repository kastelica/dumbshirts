from flask import Response
from xml.etree.ElementTree import Element, SubElement, tostring


def render_google_shopping_feed(items):
	rss = Element("rss", attrib={"version": "2.0", "xmlns:g": "http://base.google.com/ns/1.0"})
	channel = SubElement(rss, "channel")
	SubElement(channel, "title").text = "TrendMerch Products"
	SubElement(channel, "link").text = "https://example.com"
	SubElement(channel, "description").text = "Trending POD products"

	for item in items:
		it = SubElement(channel, "item")
		SubElement(it, "title").text = item.get("title", "")
		SubElement(it, "link").text = item.get("link", "")
		SubElement(it, "description").text = item.get("description", "")
		SubElement(it, "g:id").text = str(item.get("id", ""))
		SubElement(it, "g:price").text = f"{item.get('price', '0.00')} USD"
		SubElement(it, "g:availability").text = item.get("availability", "in stock")
		SubElement(it, "g:condition").text = "new"
		SubElement(it, "g:identifier_exists").text = "FALSE"
		img = item.get("image")
		if img:
			SubElement(it, "g:image_link").text = img
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

	xml_bytes = tostring(rss)
	return Response(xml_bytes, content_type="application/xml")

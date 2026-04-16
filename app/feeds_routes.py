from flask import Blueprint, url_for, current_app, request, Response
from urllib.parse import urljoin
from .feeds import render_google_shopping_feed, render_google_promotions_feed, render_google_customer_match_feed
import os
import json
import re
from .models import Product, Promotion, Order, Address
from decimal import Decimal
import datetime
import csv
import io

feeds_bp = Blueprint("feeds", __name__)


@feeds_bp.get("/feeds/google.xml")
def google_feed():
	products = Product.query.filter_by(status="active").all()
	items = []

	def _absolute_url(u: str) -> str:
		if not u:
			return ""
		if u.startswith("http://") or u.startswith("https://"):
			return u
		base = current_app.config.get("BASE_URL", "http://localhost:5000")
		return urljoin(base, u)

	def _optimize_title(product_title: str, brand: str = "Roast Cotton") -> str:
		"""Optimize product title for Google Shopping per best practices.
		
		Principles:
		- Use all 150 characters when possible
		- Put most important details first (first 70 chars visible)
		- Include keywords: product name, brand, specific details
		- Be specific and clear
		- Professional grammar, no promotional text
		"""
		if not product_title:
			return "T-Shirt"
		
		# Clean up title: remove "T-Shirt" suffix if present (we'll add it properly)
		title_clean = product_title.strip()
		title_clean = re.sub(r'\s+T-Shirt\s*$', '', title_clean, flags=re.IGNORECASE)
		title_clean = title_clean.strip()
		
		# Extract core product name (remove any trailing metadata)
		# Limit to reasonable length for the core name
		core_name = title_clean[:80] if len(title_clean) > 80 else title_clean
		
		# Build optimized title with important keywords first
		# Format: Core Product Name - Brand T-Shirt - Product Type Details
		# Target: Put most searchable terms in first 70 characters
		
		parts = []
		
		# 1. Core product name (most important for search matching)
		parts.append(core_name)
		
		# 2. Brand name (helps recognition)
		if brand and brand not in core_name:
			parts.append(brand)
		
		# 3. Product type and details
		product_details = ["Unisex T-Shirt", "100% Cotton", "Crewneck"]
		parts.extend(product_details)
		
		# Join with proper spacing
		optimized = " - ".join(parts)
		
		# Truncate to 150 characters (Google's limit)
		if len(optimized) > 150:
			# Prioritize keeping the core name and brand
			# Try to keep as much of core name as possible
			max_core = min(80, len(core_name))
			available_for_details = 150 - max_core - len(f" - {brand} - ") - 30
			if available_for_details > 0:
				truncated_details = "Unisex T-Shirt - 100% Cotton - Crewneck"[:available_for_details]
				optimized = f"{core_name[:max_core]} - {brand} - {truncated_details}"
			else:
				# If still too long, just use core name + brand + minimal details
				optimized = f"{core_name[:100]} - {brand} - T-Shirt"
			optimized = optimized[:150]
		
		# Clean up: remove extra spaces, ensure proper capitalization
		optimized = re.sub(r'\s+', ' ', optimized).strip()
		
		# Ensure first letter is capitalized, rest follows title case rules
		if optimized:
			optimized = optimized[0].upper() + optimized[1:] if len(optimized) > 1 else optimized.upper()
		
		return optimized
	
	for p in products:
		# Compute 15% off sale price
		try:
			sale = (Decimal(str(p.price)) * Decimal('0.85')).quantize(Decimal('0.01'))
		except Exception:
			sale = p.price
		
		# Image handling:
		# - Main image: white t-shirt mockup from preview_url (should be mockup)
		# - Additional images: design-only (image_url) as first, then extra_image1_url and extra_image2_url if they exist and are different
		main_image = ""
		add_imgs = []
		
		if p.design:
			# Main image: white mockup from preview_url
			preview_url = p.design.preview_url or ""
			design_url_raw = p.design.image_url or ""
			
			# Check if preview_url is actually a mockup (contains "mockup" or is different from design)
			# For Cloudinary URLs, mockups typically have "_mockup" in the public_id
			# For local files, they have "mockup" in the filename
			preview_is_mockup = False
			if preview_url:
				preview_lower = preview_url.lower()
				# Check if URL contains "mockup" indicator (most reliable)
				if "mockup" in preview_lower or "_mockup" in preview_lower:
					preview_is_mockup = True
					current_app.logger.debug(f"[feed] Product {p.id}: preview_url contains 'mockup', using as main image")
				# Also check if preview_url is different from image_url (likely a mockup)
				elif preview_url != design_url_raw and design_url_raw:
					preview_is_mockup = True
					current_app.logger.debug(f"[feed] Product {p.id}: preview_url differs from design_url, assuming mockup")
			
			if preview_is_mockup:
				# preview_url is confirmed to be a mockup, use it
				main_image = _absolute_url(preview_url)
			else:
				# preview_url is not a mockup (same as design or empty)
				# Skip products without valid mockups - don't construct URLs that might not exist
				current_app.logger.warning(f"[feed] Product {p.id}: No valid mockup (preview_url={preview_url}, design_url={design_url_raw}), skipping from feed")
				continue  # Skip this product, don't add to items
			
			if not main_image:
				# Still no main image, skip this product
				current_app.logger.warning(f"[feed] Product {p.id}: No main image available, skipping from feed")
				continue
			
			# First additional image: design-only square PNG from image_url
			design_url = _absolute_url(design_url_raw)
			if design_url and design_url != main_image:
				add_imgs.append(design_url)
			
			# Additional extra images (only if different from design)
			extra1 = _absolute_url(p.design.extra_image1_url or "") if getattr(p.design, 'extra_image1_url', None) else ""
			extra2 = _absolute_url(p.design.extra_image2_url or "") if getattr(p.design, 'extra_image2_url', None) else ""
			
			# Only add extra images if they're different from design and main
			if extra1 and extra1 != design_url and extra1 != main_image:
				add_imgs.append(extra1)
			if extra2 and extra2 != design_url and extra2 != main_image and extra2 != extra1:
				add_imgs.append(extra2)
		else:
			# No design, skip this product
			current_app.logger.warning(f"[feed] Product {p.id}: No design, skipping from feed")
			continue

		checkout_url = url_for('main.checkout', item_id=p.id, _external=True)
		
		# Optimize title for Google Shopping
		optimized_title = _optimize_title(p.title, "Roast Cotton")
		
		items.append({
			"id": p.id,
			"title": optimized_title,
			"link": url_for('main.product_detail', slug=p.slug, _external=True),
			"description": p.description or "",
			"price": f"{p.price}",
			"sale_price": f"{sale}",
			"cost_of_goods_sold": "8.64",
			"auto_pricing_min_price": "15.99",
			"availability": "in stock",
			"image": main_image,
			"additional_images": add_imgs,
			"video": _absolute_url(getattr(p, "video_url", "") or ""),
			"brand": "Roast Cotton",
			"age_group": "adult",
			"color": "white",
			"gender": "unisex",
			"size": "Large",
			"checkout_link_template": checkout_url,
			# Google Shopping
			"google_product_category": "Apparel & Accessories > Clothing > Shirts & Tops",
			"product_type": "t-shirt",
			"shipping": {
				"country": "US",
				"service": "Standard",
				"price": "0.00",
				"currency": "USD",
			},
		})
		# Removed monthly subscription items from Shopping feed
	return render_google_shopping_feed(items)


@feeds_bp.get("/feeds/promotions.xml")
def promotions_feed():
    # Read promotions from DB so they persist across deploys; fail soft if table missing
    rows = []
    try:
        for p in Promotion.query.order_by(Promotion.created_at.desc()).all():
            rows.append({
                "promotion_id": p.promotion_id,
                "long_title": p.long_title,
                "percent_off": p.percent_off,
                "generic_redemption_code": p.generic_redemption_code,
                "start_date": p.start_date,
                "end_date": p.end_date,
                "display_start_date": p.display_start_date,
                "display_end_date": p.display_end_date,
                "promotion_url": p.promotion_url,
                "promotion_destination": (p.promotion_destination.split(',') if p.promotion_destination else ["Shopping_ads", "Free_listings"]),
                "redemption_channel": p.redemption_channel or "online",
            })
    except Exception as _e:
        current_app.logger.warning(f"[promotions] feed fallback, table missing: {_e}")
    return render_google_promotions_feed(rows)


@feeds_bp.get("/feeds/reviews.xml")
def reviews_feed():
    """Google Product Review Feed following the official schema 2.4.
    
    Implements the complete Google Product Review Feed schema as defined in:
    http://www.google.com/shopping/reviews/schema/product/2.4/product_reviews.xsd
    """
    # Load reviews from data JSON managed via admin
    try:
        data_path = os.path.join(os.path.dirname(__file__), "data", "reviews.json")
        with open(data_path, "r", encoding="utf-8") as f:
            reviews = json.load(f) or []
    except Exception:
        reviews = []

    # Build XML following Google Product Review Feed schema
    from xml.etree.ElementTree import Element, SubElement, tostring
    root = Element("feed")
    
    # Required top-level elements in order
    SubElement(root, "version").text = "2.4"
    
    # Publisher (required)
    publisher = SubElement(root, "publisher")
    SubElement(publisher, "name").text = "Roast Cotton"
    base = current_app.config.get("BASE_URL", "http://localhost:5000").rstrip("/")
    SubElement(publisher, "favicon").text = f"{base}/static/uploads/brand.png"
    
    # Reviews container
    reviews_container = SubElement(root, "reviews")
    
    # Map products to ensure stable references
    prods = {p.id: p for p in Product.query.all()}

    for r in reviews:
        # Skip reviews without product_id
        pid = r.get("product_id")
        if not pid:
            continue
            
        p = prods.get(int(pid)) if pid else None
        if not p:
            continue
            
        # Individual review
        review = SubElement(reviews_container, "review")
        
        # Required fields
        SubElement(review, "review_id").text = str(r.get("review_id", f"R-{r.get('product_id', 'unknown')}"))
        
        # Reviewer (required)
        reviewer = SubElement(review, "reviewer")
        reviewer_name = SubElement(reviewer, "name")
        reviewer_name.text = str(r.get("reviewer_name", "Customer"))
        
        # Review timestamp (required) - convert to proper format
        review_timestamp = r.get("created_at", "")
        if not review_timestamp:
            review_timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        SubElement(review, "review_timestamp").text = review_timestamp
        
        # Content (required)
        SubElement(review, "content").text = str(r.get("content", ""))
        
        # Review URL (required) - use product URL if no specific review URL
        review_url = r.get("review_url", "")
        if not review_url and p:
            review_url = url_for('main.product_detail', slug=p.slug, _external=True)
        if review_url:
            review_url_elem = SubElement(review, "review_url")
            review_url_elem.text = review_url
            review_url_elem.set("type", "singleton")
        
        # Ratings (required)
        ratings = SubElement(review, "ratings")
        overall = SubElement(ratings, "overall")
        overall.text = str(r.get("rating", "5"))
        overall.set("min", "1")
        overall.set("max", "5")
        
        # Products (required)
        products = SubElement(review, "products")
        product = SubElement(products, "product")
        
        # Product name
        SubElement(product, "product_name").text = p.title
        
        # Product URL (required)
        SubElement(product, "product_url").text = url_for('main.product_detail', slug=p.slug, _external=True)
        
        # Product IDs (required for matching)
        product_ids = SubElement(product, "product_ids")
        
        # SKUs (required for products with known SKU)
        skus = SubElement(product_ids, "skus")
        SubElement(skus, "sku").text = str(p.id)
        
        # MPNs (Manufacturer Part Numbers) - use product ID as MPN
        mpns = SubElement(product_ids, "mpns")
        SubElement(mpns, "mpn").text = str(p.id)
        
        # Brands (required for products with known brand)
        brands = SubElement(product_ids, "brands")
        SubElement(brands, "brand").text = "Roast Cotton"
        
        # Optional fields
        if r.get("title"):
            SubElement(review, "title").text = str(r.get("title"))
        
        # Mark as verified purchase (optional)
        SubElement(review, "is_verified_purchase").text = "true"
        
        # Mark as not incentivized (optional)
        SubElement(review, "is_incentivized_review").text = "false"

    xml_bytes = tostring(root, encoding="utf-8", xml_declaration=True)
    return Response(xml_bytes, content_type="application/xml; charset=utf-8")


@feeds_bp.get("/feeds/customer-match.csv")
def customer_match_feed():
    """Google Ads Customer Match feed (HTTPS pull).
    
    Requires HTTP Basic Authentication via environment variables:
    - GOOGLE_CUSTOMER_MATCH_USERNAME
    - GOOGLE_CUSTOMER_MATCH_PASSWORD
    
    Returns CSV with hashed customer data from completed orders.
    """
    # HTTP Basic Auth
    auth = request.authorization
    if not auth:
        # Request authorization
        return Response(
            "Authentication required",
            401,
            {"WWW-Authenticate": 'Basic realm="Customer Match Feed"'}
        )
    
    expected_username = os.getenv("GOOGLE_CUSTOMER_MATCH_USERNAME", "").strip()
    expected_password = os.getenv("GOOGLE_CUSTOMER_MATCH_PASSWORD", "").strip()
    
    if not expected_username or not expected_password:
        current_app.logger.error("[customer-match] Auth credentials not configured")
        return Response("Feed not configured", 500)
    
    if auth.username != expected_username or auth.password != expected_password:
        return Response("Invalid credentials", 401)
    
    # Query completed orders with shipping addresses
    orders = Order.query.filter(
        Order.status.in_(["paid", "submitted", "fulfilled"])
    ).join(
        Address, Order.shipping_address_id == Address.id
    ).all()
    
    # Build customer list (deduplicate by email to send one row per unique customer)
    customers = []
    seen_emails = set()  # Track seen emails for deduplication
    
    # Sort orders by created_at descending to keep most recent data for duplicates
    orders_sorted = sorted(orders, key=lambda o: o.created_at or datetime.datetime.min, reverse=True)
    
    for order in orders_sorted:
        addr = order.shipping_address
        if not addr:
            continue
        
        email = (addr.email or "").strip().lower()
        
        # Skip if we've already seen this email (one row per unique customer)
        if email and email in seen_emails:
            continue
        
        # Need at least email or phone to include in feed
        if not email and not (addr.phone and addr.phone.strip()):
            continue
        
        if email:
            seen_emails.add(email)
        
        customers.append({
            "email": email,
            "phone": addr.phone or "",
            "first_name": addr.first_name or "",
            "last_name": addr.last_name or "",
            "country": addr.country or "US",
            "zip_code": addr.post_code or ""
        })
    
    return render_google_customer_match_feed(customers)


@feeds_bp.get("/feeds/tiktok.csv")
def tiktok_feed():
	"""TikTok Shop CSV export with required columns and reasonable defaults."""
	products = Product.query.filter_by(status="active").all()
	
	def _absolute_url(u: str) -> str:
		if not u:
			return ""
		if u.startswith("http://") or u.startswith("https://"):
			return u
		base = current_app.config.get("BASE_URL", "http://localhost:5000")
		return urljoin(base, u)
	
	# Defaults (override via config)
	default_brand = current_app.config.get("STORE_BRAND", "Roast Cotton")
	def_w = float(current_app.config.get("DEFAULT_PACKAGE_WEIGHT_LB", 0.5))
	def_l = float(current_app.config.get("DEFAULT_PACKAGE_LENGTH_IN", 12))
	def_wd = float(current_app.config.get("DEFAULT_PACKAGE_WIDTH_IN", 9))
	def_h = float(current_app.config.get("DEFAULT_PACKAGE_HEIGHT_IN", 1))
	def_qty = int(current_app.config.get("DEFAULT_STOCK_QTY", 999))
	size_chart_url = urljoin(current_app.config.get("BASE_URL", "http://localhost:5000"), "/size_guide")
	material_text = current_app.config.get("DEFAULT_MATERIALS", "100% Cotton")
	delivery_opts = current_app.config.get("DEFAULT_DELIVERY_OPTS", "")
	
	# CSV header per TikTok template - exact format match
	header = [
		"Category",
		"Brand",
		"Product Name",
		"Product Description",
		"Main Product Image",
		"Product Image 2",
		"Product Image 3",
		"Product Image 4",
		"Product Image 5",
		"Product Image 6",
		"Product Image 7",
		"Product Image 8",
		"Product Image 9",
		"Identifier Code Type",
		"Identifier Code",
		"Primary variation name",
		"Primary variation value",
		"Primary variation image 1",
		"Primary variation image 2",
		"Primary variation image 3",
		"Primary variation image 4",
		"Primary variation image 5",
		"Primary variation image 6",
		"Primary variation image 7",
		"Primary variation image 8",
		"Primary variation image 9",
		"Secondary variation name",
		"Secondary variation value",
		"Package Weight(lb)",
		"Package Length(inch)",
		"Package Width(inch)",
		"Package Height(inch)",
		"Delivery options",
		"Retail Price (Local Currency)",
		"Quantity",
		"Seller SKU",
		"Size Chart",
		"Materials",
		"Pattern",
		"Neckline",
		"Sleeve Length",
		"Season",
		"Style",
		"Fit",
		"Stretch",
		"Washing Instructions",
		"Waist Height",
		"Dangerous Goods Or Hazardous Materials",
		"Organic Textile",
		"CA Prop 65: Repro. Chems",
		"Reprotoxic Chemicals",
		"CA Prop 65: Carcinogens",
		"Carcinogen",
		"Safety Data Sheet (SDS) for other dangerous goods or hazardous materials",
		"Product Status",
	]
	
	output = io.StringIO()
	writer = csv.writer(output)
	writer.writerow(header)
	
	for p in products:
		# Category: use more specific format if available, otherwise default
		category_name = "Men's Tops/Shirts/Men's Casual Shirts/Short-sleeve Causal Shirts"
		if p.categories:
			cat_name = p.categories[0].name
			# If category is more specific, use it; otherwise use default
			if cat_name and cat_name.lower() not in ["t-shirts", "shirts", "tshirts"]:
				category_name = cat_name
		brand = ""  # Empty per format example
		name = p.title or ""
		desc = p.description or ""
		
		# Images: main = mockup/preview; then design + extras
		main_img = ""
		img2 = ""
		img3 = ""
		img4 = ""
		img5 = ""
		img6 = ""
		img7 = ""
		img8 = ""
		img9 = ""
		if p.design:
			main_img = _absolute_url(p.design.preview_url or "")
			images = []
			if p.design.image_url:
				images.append(_absolute_url(p.design.image_url))
			if getattr(p.design, "extra_image1_url", None):
				images.append(_absolute_url(p.design.extra_image1_url))
			if getattr(p.design, "extra_image2_url", None):
				images.append(_absolute_url(p.design.extra_image2_url))
			# assign into img2..9
			imgs = (images + [""] * 8)[:8]
			if imgs:
				img2 = imgs[0]
			if len(imgs) > 1:
				img3 = imgs[1]
			if len(imgs) > 2:
				img4 = imgs[2]
			if len(imgs) > 3:
				img5 = imgs[3]
			if len(imgs) > 4:
				img6 = imgs[4]
			if len(imgs) > 5:
				img7 = imgs[5]
			if len(imgs) > 6:
				img8 = imgs[6]
			if len(imgs) > 7:
				img9 = imgs[7]
		
		# Variation settings: primary Size, secondary Color
		primary_name = "Size"
		secondary_name = "Color"
		
		# Build rows per variant; if none, one generic row
		variants = p.variants or []
		if not variants:
			row = [
				category_name,
				brand,
				name,
				desc,
				main_img, img2, img3, img4, img5, img6, img7, img8, img9,
				"", "",  # Identifier Code Type, Identifier Code (empty per format)
				primary_name, "", "", "", "", "", "", "", "", "",  # Primary variation name, value, images 1-9
				secondary_name, "",
				f"{def_w:.2f}", f"{def_l:.2f}", f"{def_wd:.2f}", f"{def_h:.2f}",
				delivery_opts,
				f"{p.price}",
				str(def_qty),
				str(p.id),  # Seller SKU: use product ID (matching example format)
				size_chart_url,
				material_text,
				"", "", "", "", "", "", "", "", "",  # Pattern, Neckline, Sleeve Length, Season, Style, Fit, Stretch, Washing Instructions, Waist Height
				"No",  # Dangerous Goods Or Hazardous Materials
				"",  # Organic Textile
				"No",  # CA Prop 65: Repro. Chems
				"",  # Reprotoxic Chemicals
				"",  # CA Prop 65: Carcinogens
				"",  # Carcinogen
				"",  # Safety Data Sheet (SDS)
				"",  # Product Status
			]
			writer.writerow(row)
			continue
		
		for v in variants:
			primary_value = v.size or ""
			# Capitalize color (e.g., "white" -> "White")
			color_raw = (v.color or "").strip()
			secondary_value = color_raw.capitalize() if color_raw else ""
			# Variant-specific SKU and price
			# Use gelato_sku if available, otherwise use product ID (matching example format)
			seller_sku = v.gelato_sku or str(p.id)
			price_val = v.price or p.price
			row = [
				category_name,
				brand,
				name,
				desc,
				main_img, img2, img3, img4, img5, img6, img7, img8, img9,
				"", "",  # Identifier Code Type, Identifier Code (empty per format)
				primary_name, primary_value, "", "", "", "", "", "", "", "", "",  # Primary variation name, value, images 1-9
				secondary_name, secondary_value,
				f"{def_w:.2f}", f"{def_l:.2f}", f"{def_wd:.2f}", f"{def_h:.2f}",
				delivery_opts,
				f"{price_val}",
				str(def_qty),
				seller_sku,
				size_chart_url,
				material_text,
				"", "", "", "", "", "", "", "", "",  # Pattern, Neckline, Sleeve Length, Season, Style, Fit, Stretch, Washing Instructions, Waist Height
				"No",  # Dangerous Goods Or Hazardous Materials
				"",  # Organic Textile
				"No",  # CA Prop 65: Repro. Chems
				"",  # Reprotoxic Chemicals
				"",  # CA Prop 65: Carcinogens
				"",  # Carcinogen
				"",  # Safety Data Sheet (SDS)
				"",  # Product Status
			]
			writer.writerow(row)
	
	csv_content = output.getvalue()
	output.close()
	return Response(
		csv_content,
		mimetype="text/csv",
		headers={"Content-Disposition": "attachment; filename=tiktok.csv"}
	)

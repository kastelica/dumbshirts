from flask import Blueprint, url_for, current_app, request, Response
from urllib.parse import urljoin
from .feeds import render_google_shopping_feed, render_google_promotions_feed, render_google_customer_match_feed
import os
import json
import re
from .models import Product, Promotion, Order, Address
from decimal import Decimal
import datetime

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

	def _optimize_title(product_title: str, brand: str = "Dumbshirts.store") -> str:
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
		optimized_title = _optimize_title(p.title, "Dumbshirts.store")
		
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
			"brand": "Dumbshirts.store",
			"age_group": "adult",
			"color": "white",
			"gender": "unisex",
			"size": "Large",
			"checkout_link_template": checkout_url,
			# Google Shopping
			"google_product_category": "Apparel & Accessories > Clothing > Shirts & Tops",
			"product_type": "t-shirt",
			"shipping": {"country": "US"},
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
    SubElement(publisher, "name").text = "Dumbshirts.store"
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
        SubElement(brands, "brand").text = "Dumbshirts.store"
        
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

#!/usr/bin/env python3
"""
Standalone script to generate mockups for products that have designs but no mockups.

Usage:
    python scripts/generate_missing_mockups.py

This script will:
1. Find all products with design.image_url but missing mockups (preview_url is empty or same as image_url)
2. Download the design image
3. Generate mockup using _compose_design_on_blank_tee()
4. Upload mockup to Cloudinary (or save locally)
5. Update design.preview_url with the mockup URL

Only processes active products by default. Use --include-draft to include draft products.
"""

import sys
import os
import requests
from io import BytesIO
from PIL import Image

# Ensure project root is on sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app import create_app
from app.extensions import db
from app.models import Product, Design
from app.utils import slugify

# Import the mockup composition function from admin
# We need to copy it since it uses current_app which we'll have in app context
def _compose_design_on_blank_tee(design_png_bytes: bytes, app) -> bytes | None:
    """Composite the design PNG onto a blank white t-shirt image and return PNG bytes.
    
    Uses BLANK_TEE_URL from config if set; otherwise falls back to
    `https://dumbshirts.store/static/uploads/whitetshirt.png` and finally to local `/static/uploads/whitetshirt.png`.
    """
    try:
        if not design_png_bytes or len(design_png_bytes) == 0:
            print(f"  [ERROR] Design bytes are empty")
            return None
        
        print(f"  [INFO] Starting composition, design size: {len(design_png_bytes)} bytes")
        
        # Load base tee image
        base_url = (app.config.get("BLANK_TEE_URL") or "").strip() or "https://dumbshirts.store/static/uploads/whitetshirt.png"
        base_bytes = None
        if base_url.startswith("http://") or base_url.startswith("https://"):
            print(f"  [INFO] Loading base tee from URL: {base_url}")
            resp = requests.get(base_url, timeout=10)
            resp.raise_for_status()
            base_bytes = resp.content
            print(f"  [INFO] Base tee loaded from URL, size: {len(base_bytes)} bytes")
        else:
            # Try local path - first try white t-shirt, then fallback to 2600.png
            white_tshirt_path = os.path.join(BASE_DIR, "app", "static", "uploads", "whitetshirt.png")
            if os.path.exists(white_tshirt_path):
                print(f"  [INFO] Loading base tee from local path: {white_tshirt_path}")
                with open(white_tshirt_path, "rb") as f:
                    base_bytes = f.read()
                print(f"  [INFO] Base tee loaded from local, size: {len(base_bytes)} bytes")
            else:
                # Fallback to old filename
                fallback_path = os.path.join(BASE_DIR, "app", "static", "uploads", "2600.png")
                if os.path.exists(fallback_path):
                    print(f"  [INFO] Loading base tee from fallback path: {fallback_path}")
                    with open(fallback_path, "rb") as f:
                        base_bytes = f.read()
                    print(f"  [INFO] Base tee loaded from fallback, size: {len(base_bytes)} bytes")
                else:
                    print(f"  [ERROR] Base tee file not found at {white_tshirt_path} or {fallback_path}")
                    return None
        
        if not base_bytes or len(base_bytes) == 0:
            print(f"  [ERROR] Base tee bytes are empty")
            return None
        
        base_img = Image.open(BytesIO(base_bytes)).convert("RGBA")
        print(f"  [INFO] Base image loaded: {base_img.size}, mode: {base_img.mode}")
        
        design_img = Image.open(BytesIO(design_png_bytes)).convert("RGBA")
        print(f"  [INFO] Design image loaded: {design_img.size}, mode: {design_img.mode}")
        
        bw, bh = base_img.size
        # Target box ~35% of base width/height while preserving aspect ratio
        max_w = int(bw * 0.35)
        max_h = int(bh * 0.35)
        dw, dh = design_img.size
        scale = min(max_w / max(dw, 1), max_h / max(dh, 1))
        sw, sh = max(1, int(dw * scale)), max(1, int(dh * scale))
        print(f"  [INFO] Scaling design from {dw}x{dh} to {sw}x{sh} (scale: {scale:.2f})")
        
        design_resized = design_img.resize((sw, sh), Image.LANCZOS)
        # Center placement on chest, then shift up by ~5% of shirt height
        x = (bw - sw) // 2
        y = (bh - sh) // 2 - int(bh * 0.05)
        if y < 0:
            y = 0
        print(f"  [INFO] Positioning design at ({x}, {y})")
        
        composite = base_img.copy()
        composite.alpha_composite(design_resized, dest=(x, y))
        buf = BytesIO()
        composite.save(buf, format="PNG")
        result_bytes = buf.getvalue()
        print(f"  [INFO] Composition complete, output size: {len(result_bytes)} bytes")
        return result_bytes
    except Exception as e:
        print(f"  [ERROR] Composition failed: {e}")
        import traceback
        print(f"  [ERROR] Traceback: {traceback.format_exc()}")
        return None


def is_mockup_url(url: str, design_url: str) -> bool:
    """Check if a URL is a mockup (contains 'mockup' or is different from design)."""
    if not url:
        return False
    url_lower = url.lower()
    if "mockup" in url_lower or "_mockup" in url_lower:
        return True
    if url != design_url:
        return True
    return False


def main():
    """Main function to generate missing mockups."""
    import argparse
    parser = argparse.ArgumentParser(description="Generate mockups for products missing them")
    parser.add_argument("--include-draft", action="store_true", help="Include draft products (default: only active)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
    args = parser.parse_args()
    
    app = create_app()
    
    with app.app_context():
        # First, get total product count for diagnostics
        total_products = Product.query.count()
        print(f"Total products in database: {total_products}")
        
        # Find products with designs that have image_url
        # Use outer join to include products even if they don't have designs yet
        from sqlalchemy import or_
        query = Product.query.join(Design, Product.design_id == Design.id).filter(
            Design.image_url.isnot(None),
            Design.image_url != ""
        )
        
        if not args.include_draft:
            query = query.filter(Product.status == "active")
            print(f"Filtering for active products only")
        else:
            print(f"Including all products (active and draft)")
        
        products = query.all()
        
        print(f"Found {len(products)} products with designs")
        
        if len(products) == 0:
            print("\nChecking why no products found...")
            # Diagnostic queries
            all_products = Product.query.count()
            products_with_designs = Product.query.join(Design).count()
            designs_with_images = Design.query.filter(
                Design.image_url.isnot(None),
                Design.image_url != ""
            ).count()
            active_products = Product.query.filter(Product.status == "active").count()
            
            print(f"  Total products: {all_products}")
            print(f"  Products with designs (any): {products_with_designs}")
            print(f"  Designs with image_url: {designs_with_images}")
            print(f"  Active products: {active_products}")
            
            # Show sample products
            sample = Product.query.limit(5).all()
            if sample:
                print(f"\nSample products (first 5):")
                for p in sample:
                    has_design = p.design is not None
                    has_image = p.design and p.design.image_url if has_design else False
                    print(f"  Product {p.id}: {p.title[:50]}... (status: {p.status}, has_design: {has_design}, has_image_url: {has_image})")
        
        print("=" * 60)
        
        missing_mockups = []
        for p in products:
            if not p.design or not p.design.image_url:
                continue
            
            design_url = p.design.image_url
            preview_url = p.design.preview_url or ""
            
            # Check if mockup exists
            if is_mockup_url(preview_url, design_url):
                print(f"✓ Product {p.id} ({p.title[:50]}...): Has mockup")
                continue
            
            missing_mockups.append(p)
            print(f"✗ Product {p.id} ({p.title[:50]}...): Missing mockup")
        
        print("=" * 60)
        print(f"Products needing mockups: {len(missing_mockups)}")
        
        if not missing_mockups:
            print("No products need mockups!")
            return 0
        
        if args.dry_run:
            print("\n[DRY RUN] Would generate mockups for the above products")
            return 0
        
        print("\nStarting mockup generation...")
        print("=" * 60)
        
        cloud_url = app.config.get("CLOUDINARY_URL", "").strip()
        success_count = 0
        error_count = 0
        
        for i, p in enumerate(missing_mockups, 1):
            print(f"\n[{i}/{len(missing_mockups)}] Processing Product {p.id}: {p.title}")
            
            try:
                design_url = p.design.image_url
                
                # Download design image
                print(f"  [INFO] Downloading design from: {design_url}")
                if design_url.startswith("http://") or design_url.startswith("https://"):
                    resp = requests.get(design_url, timeout=30)
                    resp.raise_for_status()
                    design_bytes = resp.content
                elif design_url.startswith("/"):
                    # Local file
                    local_path = os.path.join(BASE_DIR, design_url.lstrip("/"))
                    if os.path.exists(local_path):
                        with open(local_path, "rb") as f:
                            design_bytes = f.read()
                    else:
                        print(f"  [ERROR] Local file not found: {local_path}")
                        error_count += 1
                        continue
                else:
                    print(f"  [ERROR] Invalid design URL format: {design_url}")
                    error_count += 1
                    continue
                
                print(f"  [INFO] Design downloaded, size: {len(design_bytes)} bytes")
                
                # Generate mockup
                mock_bytes = _compose_design_on_blank_tee(design_bytes, app)
                if not mock_bytes:
                    print(f"  [ERROR] Failed to generate mockup")
                    error_count += 1
                    continue
                
                # Upload mockup
                if cloud_url:
                    import cloudinary.uploader as cu
                    public_id = slugify(p.title or "design") or "design"
                    # Ensure unique public_id by appending product ID
                    public_id = f"{public_id}_{p.id}"
                    
                    print(f"  [INFO] Uploading mockup to Cloudinary (public_id: {public_id}_mockup)")
                    res_mock = cu.upload(mock_bytes, folder="products", public_id=public_id + "_mockup", overwrite=True, resource_type="image")
                    mock_url = res_mock.get("secure_url") or res_mock.get("url")
                    print(f"  [INFO] Mockup uploaded: {mock_url}")
                else:
                    # Save locally
                    upload_dir = os.path.join(BASE_DIR, "app", "static", "uploads")
                    os.makedirs(upload_dir, exist_ok=True)
                    fname = f"mockup_{p.id}_{slugify(p.title or 'design')}.png"
                    path_mock = os.path.join(upload_dir, fname)
                    with open(path_mock, "wb") as f:
                        f.write(mock_bytes)
                    mock_url = f"/static/uploads/{fname}"
                    print(f"  [INFO] Mockup saved locally: {mock_url}")
                
                # Update database
                p.design.preview_url = mock_url
                db.session.commit()
                print(f"  [SUCCESS] Mockup saved to preview_url")
                success_count += 1
                
            except Exception as e:
                print(f"  [ERROR] Failed to process product {p.id}: {e}")
                import traceback
                print(f"  [ERROR] Traceback: {traceback.format_exc()}")
                error_count += 1
                db.session.rollback()
        
        print("\n" + "=" * 60)
        print(f"Summary:")
        print(f"  Success: {success_count}")
        print(f"  Errors: {error_count}")
        print(f"  Total processed: {len(missing_mockups)}")
        
        return 0 if error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())


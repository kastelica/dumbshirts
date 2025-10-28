#!/usr/bin/env python3
"""
Alternative script to create draft products from a text file.

Usage:
    python scripts/create_products_from_file.py terms.txt

Or create a terms.txt file with one search term per line:
cia shirt
charles tyrwhitt linen shirt
chinese frog costume
frog costume adult
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app import create_app
from app.models import Product, Design, Category, db
from app.utils import slugify
from decimal import Decimal

def get_or_create_category(name: str, slug: str) -> Category:
    """Get or create a category."""
    cat = Category.query.filter_by(slug=slug).first()
    if not cat:
        cat = Category(name=name, slug=slug)
        db.session.add(cat)
        db.session.flush()
    return cat

def create_product_from_term(term: str) -> Product:
    """Create a draft product from a search term."""
    term = term.strip()
    if not term:
        return None
    
    # Generate slug
    slug = slugify(term)
    
    # Check if product already exists
    existing = Product.query.filter_by(slug=slug).first()
    if existing:
        print(f"⚠️  Product already exists: {term} (slug: {slug})")
        return existing
    
    # Determine category based on term content
    category_name = "t-shirt"  # default
    category_slug = "tshirt"
    
    if any(word in term.lower() for word in ["shirt", "tee", "t-shirt", "tshirt"]):
        category_name = "t-shirt"
        category_slug = "tshirt"
    elif any(word in term.lower() for word in ["hoodie", "sweatshirt", "pullover"]):
        category_name = "hoodie"
        category_slug = "hoodie"
    elif any(word in term.lower() for word in ["mug", "cup", "coffee"]):
        category_name = "mug"
        category_slug = "mug"
    elif any(word in term.lower() for word in ["costume", "dress", "outfit"]):
        category_name = "costume"
        category_slug = "costume"
    
    # Get or create category
    category = get_or_create_category(category_name, category_slug)
    
    # Create design
    design = Design(
        type="text",
        text=term,
        approved=True,
        preview_url="",  # Will be generated later
        image_url=""     # Will be generated later
    )
    db.session.add(design)
    db.session.flush()
    
    # Create product
    product = Product(
        slug=slug,
        title=term.title(),
        description=f"Fun {term.lower()} design. Perfect for anyone who loves {term.lower()}!",
        status="draft",  # Start as draft
        base_cost=Decimal("8.00"),  # Default base cost
        price=Decimal("24.99"),      # Default price
        currency="USD",
        design_id=design.id
    )
    
    # Add category
    product.categories = [category]
    
    db.session.add(product)
    db.session.flush()
    
    print(f"✅ Created draft product: {term}")
    print(f"   - Slug: {slug}")
    print(f"   - Category: {category_name}")
    print(f"   - Price: ${product.price}")
    print(f"   - Status: {product.status}")
    print()
    
    return product

def main():
    """Main function to process search terms from file."""
    if len(sys.argv) != 2:
        print("Usage: python scripts/create_products_from_file.py <terms_file>")
        print("\nExample:")
        print("  python scripts/create_products_from_file.py terms.txt")
        print("\nCreate a terms.txt file with one search term per line:")
        print("  cia shirt")
        print("  charles tyrwhitt linen shirt")
        print("  chinese frog costume")
        print("  frog costume adult")
        return
    
    terms_file = sys.argv[1]
    
    if not os.path.exists(terms_file):
        print(f"❌ File not found: {terms_file}")
        return
    
    app = create_app()
    
    with app.app_context():
        print(f"🎨 Product Creator from File: {terms_file}")
        print("=" * 50)
        
        try:
            with open(terms_file, 'r', encoding='utf-8') as f:
                terms = [line.strip() for line in f if line.strip()]
        except Exception as e:
            print(f"❌ Error reading file: {e}")
            return
        
        if not terms:
            print("❌ No terms found in file. Exiting.")
            return
        
        print(f"📝 Processing {len(terms)} terms from file...")
        print("-" * 30)
        
        created_count = 0
        skipped_count = 0
        
        try:
            for term in terms:
                product = create_product_from_term(term)
                if product and product.status == "draft":
                    created_count += 1
                elif product and product.status != "draft":
                    skipped_count += 1
            
            # Commit all changes
            db.session.commit()
            
            print("-" * 30)
            print(f"🎉 Summary:")
            print(f"   - Created: {created_count} new draft products")
            print(f"   - Skipped: {skipped_count} existing products")
            print(f"   - Total processed: {len(terms)} terms")
            print()
            print("💡 Next steps:")
            print("   - Review products in admin: /admin/products")
            print("   - Generate images for designs")
            print("   - Set final pricing")
            print("   - Change status to 'active' when ready")
            
        except Exception as e:
            print(f"❌ Error: {e}")
            db.session.rollback()
            return

if __name__ == "__main__":
    main()

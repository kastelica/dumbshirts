#!/usr/bin/env python3
"""
Standalone script to create draft products from a text file of shirt ideas.

Usage:
    python scripts/create_products_from_file.py <input_file.txt>

The script reads shirt ideas from a text file, one per line, and creates draft products.

Example input file (shirt_ideas.txt):
f ck around and find out
play stupid games
lets circle back
hold my beer
that's what she said

Example usage:
    python scripts/create_products_from_file.py shirt_ideas.txt
"""

import sys
import os
import argparse
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

def create_product_from_idea(idea: str) -> Product:
    """Create a draft product from a shirt idea."""
    idea = idea.strip()
    if not idea:
        return None
    
    # Generate slug from the idea
    slug = slugify(idea)
    
    # Check if product already exists
    existing = Product.query.filter_by(slug=slug).first()
    if existing:
        print(f"⚠️  Product already exists: {idea} (slug: {slug})")
        return existing
    
    # Default to t-shirt category
    category = get_or_create_category("t-shirt", "tshirt")
    
    # Create design with the idea as text
    design = Design(
        type="text",
        text=idea,
        approved=True,
        preview_url="",  # Will be generated later
        image_url=""     # Will be generated later
    )
    db.session.add(design)
    db.session.flush()
    
    # Create product title (capitalize first letter of each word)
    title = idea.title()
    
    # Create product
    product = Product(
        slug=slug,
        title=title,
        description=f"Free Shipping! {title}. 100% Cotton, Crewneck, Unisex. Perfect for anyone who loves this design!",
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
    
    print(f"✅ Created draft product: {idea}")
    print(f"   - Slug: {slug}")
    print(f"   - Title: {title}")
    print(f"   - Category: t-shirt")
    print(f"   - Price: ${product.price}")
    print(f"   - Status: {product.status}")
    print()
    
    return product

def main():
    """Main function to process shirt ideas from file."""
    parser = argparse.ArgumentParser(
        description="Create draft products from a text file of shirt ideas",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example:
    python scripts/create_products_from_file.py shirt_ideas.txt

Input file format (one idea per line):
    f ck around and find out
    play stupid games
    lets circle back
        """
    )
    parser.add_argument(
        'input_file',
        type=str,
        help='Path to text file containing shirt ideas (one per line)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be created without actually creating products'
    )
    
    args = parser.parse_args()
    
    # Check if file exists
    if not os.path.exists(args.input_file):
        print(f"❌ Error: File '{args.input_file}' not found.")
        sys.exit(1)
    
    # Read ideas from file
    ideas = []
    try:
        with open(args.input_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):  # Skip empty lines and comments
                    ideas.append(line)
    except Exception as e:
        print(f"❌ Error reading file: {e}")
        sys.exit(1)
    
    if not ideas:
        print("❌ No ideas found in file. Exiting.")
        sys.exit(1)
    
    app = create_app()
    
    with app.app_context():
        print("🎨 Product Creator from Shirt Ideas File")
        print("=" * 50)
        print(f"📄 Reading from: {args.input_file}")
        print(f"📝 Found {len(ideas)} ideas")
        print()
        
        if args.dry_run:
            print("🔍 DRY RUN MODE - No products will be created")
            print("-" * 50)
            for i, idea in enumerate(ideas, 1):
                slug = slugify(idea)
                title = idea.title()
                existing = Product.query.filter_by(slug=slug).first()
                status = "⚠️  EXISTS" if existing else "✅ NEW"
                print(f"{i}. {status} - {title} (slug: {slug})")
            print("-" * 50)
            print(f"📊 Summary: {len(ideas)} ideas would be processed")
            return
        
        print(f"📝 Processing {len(ideas)} ideas...")
        print("-" * 30)
        
        created_count = 0
        skipped_count = 0
        
        try:
            for idea in ideas:
                product = create_product_from_idea(idea)
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
            print(f"   - Total processed: {len(ideas)} ideas")
            print()
            print("💡 Next steps:")
            print("   - Review products in admin: /admin/products")
            print("   - Generate images for designs")
            print("   - Set final pricing")
            print("   - Change status to 'active' when ready")
            
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
            db.session.rollback()
            return

if __name__ == "__main__":
    main()

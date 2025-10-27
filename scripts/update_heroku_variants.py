#!/usr/bin/env python3
"""
Script to add missing color variants to Heroku Postgres database.
This will connect to the production database and add all missing color variants.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.models import Product, Variant
from decimal import Decimal

def main():
    # Use production config for Heroku
    app = create_app()
    
    with app.app_context():
        from app.extensions import db
        
        print("🔍 Checking current variants in Heroku database...")
        
        # All colors we want to support
        all_colors = ["White", "Black", "Heather", "Red", "Blue"]
        all_sizes = ["S", "M", "L", "XL"]
        
        products = Product.query.all()
        print(f"Found {len(products)} products in Heroku database")
        
        total_added = 0
        
        for product in products:
            print(f"\nProcessing: {product.title}")
            
            # Get existing variants for this product
            existing_variants = {(v.size, v.color) for v in product.variants}
            print(f"  Existing variants: {len(existing_variants)}")
            for variant in existing_variants:
                print(f"    {variant[0]} / {variant[1]}")
            
            # Add missing variants
            added_count = 0
            for size in all_sizes:
                for color in all_colors:
                    if (size, color) not in existing_variants:
                        variant = Variant(
                            product_id=product.id,
                            name=f"{size} / {color} / Front",
                            color=color,
                            size=size,
                            print_area="front",
                            price=product.price,
                            base_cost=product.base_cost,
                        )
                        db.session.add(variant)
                        added_count += 1
                        print(f"    ➕ Adding: {size} / {color}")
            
            if added_count > 0:
                print(f"  ✅ Added {added_count} new variants")
                total_added += added_count
            else:
                print(f"  ℹ️  All variants already exist")
        
        # Commit all changes to Heroku database
        print(f"\n💾 Committing {total_added} new variants to Heroku database...")
        db.session.commit()
        print(f"✅ Successfully added {total_added} new color variants to Heroku!")
        
        # Show final summary
        print("\n📊 Final Summary:")
        for product in products:
            variant_count = len(product.variants)
            print(f"  {product.title}: {variant_count} variants")

if __name__ == "__main__":
    main()

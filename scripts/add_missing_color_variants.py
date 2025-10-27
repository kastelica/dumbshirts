#!/usr/bin/env python3
"""
Script to add missing color variants to all existing products.
Currently products only have Black/White variants, but we want all 5 colors.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.models import Product, Variant
from decimal import Decimal

def main():
    app = create_app()
    with app.app_context():
        from app.extensions import db
        
        # All colors we want to support
        all_colors = ["White", "Black", "Heather", "Red", "Blue"]
        all_sizes = ["S", "M", "L", "XL"]
        
        products = Product.query.all()
        print(f"Found {len(products)} products to process")
        
        total_added = 0
        
        for product in products:
            print(f"\nProcessing: {product.title}")
            
            # Get existing variants for this product
            existing_variants = {(v.size, v.color) for v in product.variants}
            print(f"  Existing variants: {existing_variants}")
            
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
                        print(f"    Added: {size} / {color}")
            
            if added_count > 0:
                print(f"  Added {added_count} new variants")
                total_added += added_count
            else:
                print(f"  No new variants needed")
        
        # Commit all changes
        db.session.commit()
        print(f"\n✅ Successfully added {total_added} new color variants across all products!")
        
        # Show summary
        print("\n📊 Summary:")
        for product in products:
            variant_count = len(product.variants)
            print(f"  {product.title}: {variant_count} variants")

if __name__ == "__main__":
    main()

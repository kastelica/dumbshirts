#!/usr/bin/env python3
"""
Script to update product prices in the database.
Sets all product prices to $21.07 so they display as $20.02 with the new discount.
"""

import os
import sys
from decimal import Decimal

# Add the app directory to the path
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app import create_app
from app.models import Product, db

def update_product_prices():
    """Update all product prices to $21.07."""
    app = create_app()
    
    with app.app_context():
        print("💰 Product Price Update Script")
        print("=" * 50)
        
        # Get all products
        products = Product.query.all()
        
        if not products:
            print("❌ No products found in database")
            return
        
        print(f"📊 Found {len(products)} products to update")
        print()
        
        # New price: $21.07 (will show as $20.02 with 95.02% discount)
        new_price = Decimal("21.07")
        
        updated_count = 0
        
        try:
            for product in products:
                old_price = product.price
                product.price = new_price
                
                print(f"✅ Updated: {product.title}")
                print(f"   - Old price: ${old_price}")
                print(f"   - New price: ${new_price}")
                print(f"   - Sale price: ${(new_price * Decimal('95.02') / Decimal('100')).quantize(Decimal('0.01'))}")
                print()
                
                updated_count += 1
            
            # Commit all changes
            db.session.commit()
            
            print("=" * 50)
            print(f"🎉 Successfully updated {updated_count} products!")
            print(f"💰 All products now priced at ${new_price}")
            print(f"🏷️  Sale price displays as $20.02")
            print()
            print("💡 Next steps:")
            print("   - Check your website to verify pricing")
            print("   - Update any hardcoded prices if needed")
            
        except Exception as e:
            print(f"❌ Error updating prices: {e}")
            db.session.rollback()
            return

def main():
    """Main function."""
    print("This script will update ALL product prices to $21.07")
    print("(so they display as $20.02 with the new discount)")
    print()
    
    response = input("Continue? (y/N): ").strip().lower()
    if response != 'y':
        print("❌ Cancelled")
        return
    
    update_product_prices()

if __name__ == "__main__":
    main()

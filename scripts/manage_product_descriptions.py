#!/usr/bin/env python3
"""
Script to view, update, and standardize product descriptions.

Usage:
    python scripts/manage_product_descriptions.py --list
    python scripts/manage_product_descriptions.py --export output.csv
    python scripts/manage_product_descriptions.py --standardize
    python scripts/manage_product_descriptions.py --update product_id new_description
    python scripts/manage_product_descriptions.py --interactive
"""

import sys
import os
import csv
import argparse
from typing import List, Optional

# Ensure project root is on sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app import create_app
from app.extensions import db
from app.models import Product


def standardize_description(product: Product, template: Optional[str] = None) -> str:
    """
    Generate a standardized description for a product.
    
    If template is provided, use it with {title} placeholder.
    Otherwise, use default template.
    """
    if template:
        return template.format(title=product.title)
    
    # Default standardized template
    return f"Free Shipping! {product.title}. 100% Cotton, Crewneck, Unisex. Perfect for anyone who loves this design!"


def list_products(include_draft: bool = False, limit: Optional[int] = None):
    """List all products with their descriptions."""
    query = Product.query
    if not include_draft:
        query = query.filter(Product.status == "active")
    
    if limit:
        query = query.limit(limit)
    
    products = query.order_by(Product.id).all()
    
    print(f"\n{'ID':<6} {'Title':<50} {'Status':<10} {'Description':<80}")
    print("=" * 150)
    
    for p in products:
        desc = (p.description or "(empty)")[:80]
        if len(p.description or "") > 80:
            desc += "..."
        print(f"{p.id:<6} {p.title[:48]:<50} {p.status:<10} {desc}")
    
    print(f"\nTotal: {len(products)} products")
    return products


def export_to_csv(filename: str, include_draft: bool = False):
    """Export products and descriptions to CSV."""
    query = Product.query
    if not include_draft:
        query = query.filter(Product.status == "active")
    
    products = query.order_by(Product.id).all()
    
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['ID', 'Title', 'Status', 'Description', 'Slug'])
        
        for p in products:
            writer.writerow([
                p.id,
                p.title,
                p.status,
                p.description or "",
                p.slug
            ])
    
    print(f"Exported {len(products)} products to {filename}")


def import_from_csv(filename: str, dry_run: bool = False):
    """Import descriptions from CSV. CSV should have ID and Description columns."""
    updated = 0
    errors = 0
    
    with open(filename, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        
        for row in reader:
            try:
                product_id = int(row.get('ID', row.get('id', '')))
                new_description = row.get('Description', row.get('description', '')).strip()
                
                product = Product.query.get(product_id)
                if not product:
                    print(f"  [ERROR] Product {product_id} not found")
                    errors += 1
                    continue
                
                if dry_run:
                    print(f"  [DRY RUN] Would update product {product_id} ({product.title[:50]}...):")
                    print(f"    Old: {product.description or '(empty)'}")
                    print(f"    New: {new_description}")
                else:
                    product.description = new_description
                    db.session.add(product)
                    updated += 1
                    
            except Exception as e:
                print(f"  [ERROR] Row error: {e}")
                errors += 1
                continue
    
    if not dry_run:
        db.session.commit()
        print(f"\nUpdated {updated} products")
    else:
        print(f"\n[DRY RUN] Would update {updated} products")
    
    if errors > 0:
        print(f"Errors: {errors}")


def update_product(product_id: int, new_description: str, dry_run: bool = False):
    """Update a single product's description."""
    product = Product.query.get(product_id)
    if not product:
        print(f"Product {product_id} not found")
        return False
    
    print(f"Product {product_id}: {product.title}")
    print(f"Current description: {product.description or '(empty)'}")
    print(f"New description: {new_description}")
    
    if dry_run:
        print("\n[DRY RUN] Would update this product")
        return True
    
    product.description = new_description
    db.session.add(product)
    db.session.commit()
    print("\n✓ Product updated successfully")
    return True


def standardize_all(template: Optional[str] = None, include_draft: bool = False, 
                   dry_run: bool = False, limit: Optional[int] = None):
    """Standardize all product descriptions using a template."""
    query = Product.query
    if not include_draft:
        query = query.filter(Product.status == "active")
    
    if limit:
        query = query.limit(limit)
    
    products = query.all()
    
    updated = 0
    skipped = 0
    
    print(f"\nStandardizing descriptions for {len(products)} products...")
    if template:
        print(f"Using template: {template}")
    print("=" * 100)
    
    for p in products:
        new_desc = standardize_description(p, template)
        
        if p.description == new_desc:
            skipped += 1
            continue
        
        print(f"\nProduct {p.id}: {p.title[:60]}")
        print(f"  Old: {p.description or '(empty)'}")
        print(f"  New: {new_desc}")
        
        if not dry_run:
            p.description = new_desc
            db.session.add(p)
            updated += 1
        else:
            print("  [DRY RUN]")
    
    if not dry_run:
        db.session.commit()
        print(f"\n✓ Updated {updated} products, skipped {skipped} (already standardized)")
    else:
        print(f"\n[DRY RUN] Would update {updated} products, skip {skipped}")
    
    return updated, skipped


def interactive_mode():
    """Interactive mode to browse and edit descriptions."""
    print("\n=== Interactive Product Description Editor ===")
    print("Commands:")
    print("  list [all|active] - List products")
    print("  view <id> - View product details")
    print("  edit <id> - Edit product description")
    print("  search <term> - Search products by title")
    print("  quit - Exit")
    print()
    
    while True:
        try:
            cmd = input("> ").strip().split()
            if not cmd:
                continue
            
            action = cmd[0].lower()
            
            if action == "quit" or action == "exit" or action == "q":
                break
            
            elif action == "list":
                include_draft = len(cmd) > 1 and cmd[1].lower() == "all"
                list_products(include_draft=include_draft)
            
            elif action == "view" or action == "v":
                if len(cmd) < 2:
                    print("Usage: view <product_id>")
                    continue
                try:
                    product_id = int(cmd[1])
                    product = Product.query.get(product_id)
                    if not product:
                        print(f"Product {product_id} not found")
                        continue
                    
                    print(f"\nProduct ID: {product.id}")
                    print(f"Title: {product.title}")
                    print(f"Status: {product.status}")
                    print(f"Slug: {product.slug}")
                    print(f"Description: {product.description or '(empty)'}")
                    print(f"Price: ${product.price}")
                    print()
                except ValueError:
                    print("Invalid product ID")
            
            elif action == "edit" or action == "e":
                if len(cmd) < 2:
                    print("Usage: edit <product_id>")
                    continue
                try:
                    product_id = int(cmd[1])
                    product = Product.query.get(product_id)
                    if not product:
                        print(f"Product {product_id} not found")
                        continue
                    
                    print(f"\nEditing Product {product_id}: {product.title}")
                    print(f"Current description: {product.description or '(empty)'}")
                    print("\nEnter new description (or 'cancel' to abort):")
                    new_desc = input("> ").strip()
                    
                    if new_desc.lower() == "cancel":
                        print("Cancelled")
                        continue
                    
                    if not new_desc:
                        print("Description cannot be empty. Use 'cancel' to abort.")
                        continue
                    
                    confirm = input(f"\nUpdate product {product_id}? (yes/no): ").strip().lower()
                    if confirm in ["yes", "y"]:
                        product.description = new_desc
                        db.session.add(product)
                        db.session.commit()
                        print("✓ Updated successfully")
                    else:
                        print("Cancelled")
                except ValueError:
                    print("Invalid product ID")
            
            elif action == "search" or action == "s":
                if len(cmd) < 2:
                    print("Usage: search <term>")
                    continue
                
                search_term = " ".join(cmd[1:])
                products = Product.query.filter(Product.title.ilike(f"%{search_term}%")).limit(20).all()
                
                if not products:
                    print(f"No products found matching '{search_term}'")
                    continue
                
                print(f"\nFound {len(products)} products:")
                for p in products:
                    desc_preview = (p.description or "(empty)")[:60]
                    print(f"  {p.id}: {p.title[:50]} - {desc_preview}...")
            
            else:
                print(f"Unknown command: {action}")
        
        except KeyboardInterrupt:
            print("\nExiting...")
            break
        except Exception as e:
            print(f"Error: {e}")


def main():
    parser = argparse.ArgumentParser(description="Manage product descriptions")
    parser.add_argument("--list", action="store_true", help="List all products with descriptions")
    parser.add_argument("--export", type=str, metavar="FILE", help="Export to CSV file")
    parser.add_argument("--import", dest="import_file", type=str, metavar="FILE", help="Import from CSV file")
    parser.add_argument("--standardize", action="store_true", help="Standardize all descriptions")
    parser.add_argument("--template", type=str, help="Template for standardization (use {title} placeholder)")
    parser.add_argument("--update", nargs=2, metavar=("ID", "DESC"), help="Update a single product description")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive mode")
    parser.add_argument("--include-draft", action="store_true", help="Include draft products")
    parser.add_argument("--limit", type=int, help="Limit number of products to process")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
    
    args = parser.parse_args()
    
    app = create_app()
    
    with app.app_context():
        if args.list:
            list_products(include_draft=args.include_draft, limit=args.limit)
        
        elif args.export:
            export_to_csv(args.export, include_draft=args.include_draft)
        
        elif args.import_file:
            import_from_csv(args.import_file, dry_run=args.dry_run)
        
        elif args.standardize:
            standardize_all(template=args.template, include_draft=args.include_draft, 
                          dry_run=args.dry_run, limit=args.limit)
        
        elif args.update:
            product_id = int(args.update[0])
            new_description = args.update[1]
            update_product(product_id, new_description, dry_run=args.dry_run)
        
        elif args.interactive:
            interactive_mode()
        
        else:
            parser.print_help()


if __name__ == "__main__":
    sys.exit(main() or 0)


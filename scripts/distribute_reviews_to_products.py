#!/usr/bin/env python3
"""
Standalone script to read product IDs from Heroku database and update reviews.json
to distribute product IDs across reviews.

Usage:
    python scripts/distribute_reviews_to_products.py [--dry-run] [--force]

This script will:
1. Read all active products from the database
2. Read current reviews.json
3. Distribute product IDs across reviews (ensuring each product gets some reviews)
4. Update reviews.json with the new product_id assignments
5. Verify that all reviews have valid product_ids

Options:
    --dry-run: Show what would be changed without actually updating reviews.json
    --force: Force update even if distribution looks good
"""

import sys
import os
import json
import argparse
from collections import defaultdict

# Ensure project root is on sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app import create_app
from app.extensions import db
from app.models import Product


def get_reviews_path():
    """Get the path to reviews.json."""
    return os.path.join(BASE_DIR, "app", "data", "reviews.json")


def load_reviews():
    """Load reviews from reviews.json."""
    path = get_reviews_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or []
    except FileNotFoundError:
        print(f"❌ Error: reviews.json not found at {path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"❌ Error: Invalid JSON in reviews.json: {e}")
        sys.exit(1)


def save_reviews(reviews):
    """Save reviews to reviews.json."""
    path = get_reviews_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(reviews, f, indent=2, ensure_ascii=False)
        print(f"✅ Saved {len(reviews)} reviews to {path}")
        return True
    except Exception as e:
        print(f"❌ Error saving reviews.json: {e}")
        return False


def get_product_ids(app):
    """Get all active product IDs from the database."""
    with app.app_context():
        products = Product.query.filter_by(status="active").order_by(Product.id).all()
        product_ids = [str(p.id) for p in products]
        print(f"📦 Found {len(product_ids)} active products: {product_ids[:10]}{'...' if len(product_ids) > 10 else ''}")
        return product_ids


def distribute_reviews(reviews, product_ids, dry_run=False):
    """
    Distribute product IDs across reviews.
    
    Strategy:
    1. Keep existing valid product_ids (if they match a product)
    2. For reviews without product_id or with invalid product_id, assign one
    3. Try to distribute evenly so each product gets roughly the same number of reviews
    4. Prioritize products with fewer reviews
    """
    if not product_ids:
        print("⚠️  No products found in database. Cannot distribute reviews.")
        return reviews
    
    # Count current distribution
    current_distribution = defaultdict(int)
    valid_product_ids = set(product_ids)
    
    # First pass: validate existing product_ids and count distribution
    for review in reviews:
        pid = str(review.get("product_id", "")).strip()
        if pid and pid in valid_product_ids:
            current_distribution[pid] += 1
        else:
            # Mark as needing assignment
            review["_needs_assignment"] = True
    
    print(f"\n📊 Current review distribution:")
    for pid, count in sorted(current_distribution.items(), key=lambda x: int(x[0])):
        print(f"   Product {pid}: {count} reviews")
    
    # Count reviews needing assignment
    needs_assignment = sum(1 for r in reviews if r.get("_needs_assignment", False))
    print(f"\n📝 Reviews needing product_id assignment: {needs_assignment}")
    
    if needs_assignment == 0 and not dry_run:
        print("✅ All reviews already have valid product_ids!")
        return reviews
    
    # Calculate target distribution (roughly even)
    total_reviews = len(reviews)
    reviews_per_product = total_reviews // len(product_ids)
    extra_reviews = total_reviews % len(product_ids)
    
    print(f"\n🎯 Target distribution: ~{reviews_per_product} reviews per product")
    
    # Create a priority queue: products sorted by current review count (ascending)
    # This ensures we assign reviews to products with fewer reviews first
    product_priority = sorted(product_ids, key=lambda pid: current_distribution.get(pid, 0))
    
    # For dry-run, create a copy to update for validation
    if dry_run:
        import copy
        reviews_for_validation = copy.deepcopy(reviews)
    else:
        reviews_for_validation = reviews
    
    # Track changes for summary
    changes = []
    
    # Second pass: assign product_ids to reviews that need them
    assigned_count = 0
    product_index = 0
    
    for i, review in enumerate(reviews):
        if review.get("_needs_assignment", False):
            # Assign next product in priority queue
            if product_index >= len(product_priority):
                product_index = 0  # Cycle through if we run out
            
            new_pid = product_priority[product_index]
            old_pid = review.get("product_id", "") or "(empty)"
            
            # Track this change
            changes.append({
                "review_id": review.get("review_id", "unknown"),
                "old_pid": old_pid,
                "new_pid": new_pid
            })
            
            if not dry_run:
                review["product_id"] = new_pid
                review.pop("_needs_assignment", None)
            else:
                print(f"   Would assign product_id '{new_pid}' to review '{review.get('review_id', 'unknown')}' (was: '{old_pid}')")
                # Update the copy for validation
                reviews_for_validation[i]["product_id"] = new_pid
                reviews_for_validation[i].pop("_needs_assignment", None)
            
            current_distribution[new_pid] = current_distribution.get(new_pid, 0) + 1
            assigned_count += 1
            
            # Move to next product, cycling through for even distribution
            product_index = (product_index + 1) % len(product_priority)
    
    if dry_run:
        print(f"\n📋 Would assign {assigned_count} reviews to products")
    else:
        print(f"\n✅ Assigned {assigned_count} reviews to products")
        
        # Show summary of changes
        if changes:
            print(f"\n📝 Summary of changes:")
            for change in changes:
                print(f"   Review {change['review_id']}: {change['old_pid']} → {change['new_pid']}")
            
            # Group by old_pid to show mapping
            print(f"\n🗺️  Product ID mapping (invalid → valid):")
            old_to_new = defaultdict(set)
            for change in changes:
                old_to_new[change['old_pid']].add(change['new_pid'])
            for old_pid, new_pids in sorted(old_to_new.items()):
                new_pids_str = ", ".join(sorted(new_pids, key=int))
                print(f"   {old_pid} → {new_pids_str}")
    
    # Show final distribution (use validation copy in dry-run)
    final_distribution = defaultdict(int)
    for review in reviews_for_validation:
        pid = str(review.get("product_id", "")).strip()
        if pid in valid_product_ids:
            final_distribution[pid] += 1
    
    print(f"\n📊 Final review distribution:")
    for pid, count in sorted(final_distribution.items(), key=lambda x: int(x[0])):
        print(f"   Product {pid}: {count} reviews")
    
    # Return the appropriate list (updated original or validation copy)
    return reviews_for_validation if dry_run else reviews


def validate_reviews(reviews, product_ids):
    """Validate that all reviews have valid product_ids."""
    valid_product_ids = set(product_ids)
    invalid_count = 0
    missing_count = 0
    
    for review in reviews:
        pid = str(review.get("product_id", "")).strip()
        if not pid:
            missing_count += 1
            print(f"   ⚠️  Review '{review.get('review_id', 'unknown')}' has no product_id")
        elif pid not in valid_product_ids:
            invalid_count += 1
            print(f"   ⚠️  Review '{review.get('review_id', 'unknown')}' has invalid product_id: {pid}")
    
    if missing_count == 0 and invalid_count == 0:
        print("✅ All reviews have valid product_ids!")
        return True
    else:
        print(f"⚠️  Found {missing_count} reviews without product_id and {invalid_count} with invalid product_id")
        return False


def main():
    parser = argparse.ArgumentParser(description="Distribute product IDs across reviews")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be changed without updating")
    parser.add_argument("--force", action="store_true", help="Force update even if distribution looks good")
    args = parser.parse_args()
    
    print("🚀 Starting review distribution script...\n")
    
    # Create Flask app
    app = create_app()
    
    # Load reviews
    print("📖 Loading reviews from reviews.json...")
    reviews = load_reviews()
    print(f"✅ Loaded {len(reviews)} reviews\n")
    
    # Get product IDs from database
    print("🔍 Fetching product IDs from database...")
    product_ids = get_product_ids(app)
    
    if not product_ids:
        print("❌ No products found. Cannot distribute reviews.")
        sys.exit(1)
    
    # Validate current reviews
    print("\n🔍 Validating current reviews...")
    is_valid = validate_reviews(reviews, product_ids)
    
    if is_valid and not args.force:
        print("\n✅ All reviews already have valid product_ids. Use --force to redistribute anyway.")
        if not args.dry_run:
            sys.exit(0)
    
    # Distribute reviews
    print("\n🔄 Distributing product IDs across reviews...")
    updated_reviews = distribute_reviews(reviews, product_ids, dry_run=args.dry_run)
    
    # Validate final state
    print("\n🔍 Validating final reviews...")
    final_is_valid = validate_reviews(updated_reviews, product_ids)
    
    if not final_is_valid:
        print("❌ Validation failed after distribution!")
        sys.exit(1)
    
    # Save if not dry run
    if not args.dry_run:
        if save_reviews(updated_reviews):
            print("\n✅ Successfully updated reviews.json!")
        else:
            print("\n❌ Failed to save reviews.json")
            sys.exit(1)
    else:
        print("\n🔍 Dry run complete. Use without --dry-run to apply changes.")
    
    print("\n✨ Done!")


if __name__ == "__main__":
    main()


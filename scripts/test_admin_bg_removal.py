#!/usr/bin/env python3
"""
Test script to verify the updated admin background removal function works.
"""

import os
import sys
import requests
from io import BytesIO
from PIL import Image

# Add the app directory to the path
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

def download_image(url: str) -> bytes | None:
    """Download image from URL and return bytes."""
    try:
        print(f"📥 Downloading image from: {url}")
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        print(f"✅ Downloaded {len(response.content)} bytes")
        return response.content
        
    except Exception as e:
        print(f"❌ Failed to download image: {e}")
        return None

def convert_to_png(image_bytes: bytes) -> bytes | None:
    """Convert any image format to PNG bytes."""
    try:
        image = Image.open(BytesIO(image_bytes))
        
        # Convert to RGBA to support transparency
        if image.mode != 'RGBA':
            image = image.convert('RGBA')
        
        # Save as PNG
        output = BytesIO()
        image.save(output, format='PNG')
        return output.getvalue()
        
    except Exception as e:
        print(f"❌ Failed to convert image to PNG: {e}")
        return None

def test_admin_bg_removal():
    """Test the updated admin background removal function."""
    try:
        # Import the updated function
        from app.admin import _remove_bg_hf
        
        print("🎨 Testing Updated Admin Background Removal")
        print("=" * 50)
        
        # Get image URL
        url = input("Enter image URL (or press Enter for sample): ").strip()
        if not url:
            url = "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=400&h=400&fit=crop"
            print(f"🖼️  Using sample image: {url}")
        
        # Download image
        image_bytes = download_image(url)
        if not image_bytes:
            return
        
        # Convert to PNG
        png_bytes = convert_to_png(image_bytes)
        if not png_bytes:
            return
        
        print(f"🔄 Converting to PNG: {len(png_bytes)} bytes")
        
        # Test the admin function
        print("🧹 Testing admin background removal...")
        transparent_bytes = _remove_bg_hf(png_bytes)
        
        if not transparent_bytes:
            print("❌ Admin background removal failed")
            return
        
        print(f"✅ Admin background removal successful! Result: {len(transparent_bytes)} bytes")
        
        # Save the result
        with open("admin_bg_test_output.png", "wb") as f:
            f.write(transparent_bytes)
        
        print("💾 Saved result to: admin_bg_test_output.png")
        print("🎉 Admin background removal is working correctly!")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")

if __name__ == "__main__":
    test_admin_bg_removal()

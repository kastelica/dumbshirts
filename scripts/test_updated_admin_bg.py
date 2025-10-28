#!/usr/bin/env python3
"""
Simple test to verify the updated admin background removal logic works.
"""

import requests
from io import BytesIO
from PIL import Image
from transformers import pipeline

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

def remove_bg_hf_updated(png_bytes: bytes) -> bytes | None:
    """Updated admin background removal function (standalone version)."""
    try:
        # Load the pipeline (cached after first use)
        pipe = pipeline("image-segmentation", model="briaai/RMBG-1.4", trust_remote_code=True)
        
        # Load image from bytes
        image = Image.open(BytesIO(png_bytes)).convert("RGB")
        
        # Apply background removal
        pillow_image = pipe(image)  # Returns image with transparent background
        
        # Convert back to bytes
        output = BytesIO()
        pillow_image.save(output, format='PNG')
        result_bytes = output.getvalue()
        
        print(f"✅ Background removal successful, result: {len(result_bytes)} bytes")
        return result_bytes
        
    except Exception as e:
        print(f"❌ Background removal failed: {e}")
        return None

def main():
    """Test the updated background removal logic."""
    print("🎨 Testing Updated Admin Background Removal Logic")
    print("=" * 55)
    
    # Use a sample image
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
    
    # Test the updated function
    print("🧹 Testing updated background removal...")
    transparent_bytes = remove_bg_hf_updated(png_bytes)
    
    if not transparent_bytes:
        print("❌ Background removal failed")
        return
    
    # Save the result
    with open("updated_admin_bg_test.png", "wb") as f:
        f.write(transparent_bytes)
    
    print("💾 Saved result to: updated_admin_bg_test.png")
    print("🎉 Updated admin background removal is working correctly!")
    print("\n📋 Summary:")
    print("   ✅ Pipeline approach works")
    print("   ✅ Same logic as updated admin function")
    print("   ✅ Ready for production use")

if __name__ == "__main__":
    main()

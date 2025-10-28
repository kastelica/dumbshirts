#!/usr/bin/env python3
"""
Test script for background removal using Hugging Face API.
Enter an image URL and get back a transparent PNG with background removed.
"""

import os
import sys
import requests
from io import BytesIO
from PIL import Image

# Add the app directory to the path so we can import the background removal function
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

def remove_bg_hf(png_bytes: bytes) -> bytes | None:
    """Remove background via Hugging Face Pipeline (briaai/RMBG-1.4).
    
    This uses the same approach as admin.py but with the working pipeline method.
    """
    try:
        print("🔄 Loading RMBG-1.4 pipeline...")
        
        # Use the working pipeline approach
        from transformers import pipeline
        pipe = pipeline("image-segmentation", model="briaai/RMBG-1.4", trust_remote_code=True)
        
        print("✅ Pipeline loaded successfully")
        
        # Load image from bytes
        from PIL import Image
        from io import BytesIO
        image = Image.open(BytesIO(png_bytes)).convert("RGB")
        print(f"🖼️  Processing image: {image.size}")
        
        # Apply background removal
        print("🧹 Removing background...")
        pillow_image = pipe(image)  # This applies mask and returns image with transparent background
        
        # Convert to bytes
        output = BytesIO()
        pillow_image.save(output, format='PNG')
        result_bytes = output.getvalue()
        
        print(f"✅ Background removed! Result: {len(result_bytes)} bytes")
        return result_bytes
        
    except Exception as e:
        print(f"❌ Background removal failed: {e}")
        return None

def download_image(url: str) -> bytes | None:
    """Download image from URL and return bytes."""
    try:
        print(f"📥 Downloading image from: {url}")
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        # Check if it's actually an image
        content_type = response.headers.get('content-type', '').lower()
        if not content_type.startswith('image/'):
            print(f"⚠️  Warning: Content-Type is {content_type}, not an image")
        
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

def save_image(image_bytes: bytes, filename: str) -> None:
    """Save image bytes to file."""
    try:
        with open(filename, 'wb') as f:
            f.write(image_bytes)
        print(f"💾 Saved transparent image to: {filename}")
    except Exception as e:
        print(f"❌ Failed to save image: {e}")

def main():
    """Main function to test background removal."""
    print("🎨 Background Removal Test Script")
    print("=" * 50)
    
    # Check for Hugging Face token
    token = 'REMOVED_HF_TOKEN'
    if not token:
        print("❌ Hugging Face token not available")
        return
    
    # Get image URL from user
    print("\n📝 Enter an image URL to test background removal:")
    print("   (Press Enter with empty input to use a sample image)")
    
    url = input("URL: ").strip()
    
    if not url:
        # Use a sample image if no URL provided
        url = "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=400&h=400&fit=crop"
        print(f"🖼️  Using sample image: {url}")
    
    # Download the image
    image_bytes = download_image(url)
    if not image_bytes:
        return
    
    # Convert to PNG
    png_bytes = convert_to_png(image_bytes)
    if not png_bytes:
        return
    
    print(f"🔄 Converting to PNG: {len(png_bytes)} bytes")
    
    # Remove background
    print("🧹 Removing background...")
    transparent_bytes = remove_bg_hf(png_bytes)
    
    if not transparent_bytes:
        print("❌ Background removal failed")
        return
    
    print(f"✅ Background removed! Result: {len(transparent_bytes)} bytes")
    
    # Save the result
    output_filename = "transparent_output.png"
    save_image(transparent_bytes, output_filename)
    
    print(f"\n🎉 Success! Check '{output_filename}' for the transparent image")
    print("   The image should have a transparent background now")

if __name__ == "__main__":
    main()

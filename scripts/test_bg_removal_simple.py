#!/usr/bin/env python3
"""
Simple background removal test script using rembg library.
Enter an image URL and get back a transparent PNG with background removed.
"""

import requests
from io import BytesIO
from PIL import Image
from rembg import remove

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

def remove_bg_rembg(image_bytes: bytes) -> bytes | None:
    """Remove background using rembg library."""
    try:
        print("🧹 Removing background using rembg...")
        
        # Use rembg to remove background
        output_bytes = remove(image_bytes)
        
        print(f"✅ Background removed! Result: {len(output_bytes)} bytes")
        return output_bytes
        
    except Exception as e:
        print(f"❌ Background removal failed: {e}")
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
    print("🎨 Background Removal Test Script (rembg)")
    print("=" * 50)
    
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
    
    # Remove background using rembg
    transparent_bytes = remove_bg_rembg(image_bytes)
    
    if not transparent_bytes:
        print("❌ Background removal failed")
        return
    
    # Save the result
    output_filename = "transparent_output_rembg.png"
    save_image(transparent_bytes, output_filename)
    
    print(f"\n🎉 Success! Check '{output_filename}' for the transparent image")
    print("   The image should have a transparent background now")

if __name__ == "__main__":
    main()

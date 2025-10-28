#!/usr/bin/env python3
"""
Alternative background removal test script using transformers library.
This approach loads the model locally instead of using the API.
"""

import os
import sys
import requests
from io import BytesIO
from PIL import Image
import torch

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

def remove_bg_local(image_bytes: bytes) -> bytes | None:
    """Remove background using local transformers model."""
    try:
        print("🔄 Loading RMBG-1.4 model locally...")
        
        # Import transformers
        from transformers import AutoModelForImageSegmentation, AutoProcessor
        
        # Load model and processor
        model_name = "briaai/RMBG-1.4"
        token = 'REMOVED_HF_TOKEN'
        
        model = AutoModelForImageSegmentation.from_pretrained(
            model_name, 
            use_auth_token=token,
            trust_remote_code=True
        )
        processor = AutoProcessor.from_pretrained(
            model_name, 
            use_auth_token=token,
            trust_remote_code=True
        )
        
        print("✅ Model loaded successfully")
        
        # Load and process image
        image = Image.open(BytesIO(image_bytes)).convert("RGB")
        print(f"🖼️  Processing image: {image.size}")
        
        # Preprocess
        inputs = processor(images=image, return_tensors="pt")
        
        # Run inference
        print("🧹 Removing background...")
        with torch.no_grad():
            outputs = model(**inputs)
        
        # Post-process
        mask = outputs.logits.sigmoid().squeeze().cpu().numpy()
        mask = (mask > 0.5).astype("uint8") * 255
        
        # Apply mask to create transparent image
        image_rgba = image.convert("RGBA")
        mask_image = Image.fromarray(mask, mode="L")
        image_rgba.putalpha(mask_image)
        
        # Save to bytes
        output = BytesIO()
        image_rgba.save(output, format='PNG')
        return output.getvalue()
        
    except Exception as e:
        print(f"❌ Local background removal failed: {e}")
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
    """Main function to test local background removal."""
    print("🎨 Local Background Removal Test Script")
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
    
    # Remove background using local model
    transparent_bytes = remove_bg_local(image_bytes)
    
    if not transparent_bytes:
        print("❌ Background removal failed")
        return
    
    print(f"✅ Background removed! Result: {len(transparent_bytes)} bytes")
    
    # Save the result
    output_filename = "transparent_output_local.png"
    save_image(transparent_bytes, output_filename)
    
    print(f"\n🎉 Success! Check '{output_filename}' for the transparent image")
    print("   The image should have a transparent background now")

if __name__ == "__main__":
    main()

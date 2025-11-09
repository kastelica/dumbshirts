import os
import sys
import argparse
import tempfile
from io import BytesIO


def build_mockup_for_product(app, product_id: int) -> bytes:
	from app.extensions import db
	from app.models import Product
	from app.admin import _compose_design_on_blank_tee
	import requests
	
	p = db.session.get(Product, int(product_id))
	if not p or not p.design or not (p.design.image_url or p.design.preview_url):
		raise RuntimeError("Product or product design missing")
	design_url = p.design.image_url or p.design.preview_url
	r = requests.get(design_url, timeout=20)
	r.raise_for_status()
	design_bytes = r.content
	mockup_bytes = _compose_design_on_blank_tee(design_bytes)
	return mockup_bytes or design_bytes


def create_test_video_from_image(image_bytes: bytes, seconds: int = 8, fps: int = 24) -> bytes:
	"""
	Create a simple test MP4 (pan/zoom effect) from a single image.
	Requires moviepy. This function returns the resulting MP4 bytes.
	"""
	try:
		from moviepy.editor import ImageClip
		from moviepy.video.fx.all import resize
	except ImportError:
		raise RuntimeError("moviepy not installed. Try: pip install moviepy imageio-ffmpeg")
	
	with tempfile.TemporaryDirectory() as td:
		img_path = os.path.join(td, "frame.png")
		out_path = os.path.join(td, "out.mp4")
		with open(img_path, "wb") as f:
			f.write(image_bytes)
		
		clip = ImageClip(img_path, duration=seconds)
		# Simple subtle zoom over time
		def zoom(get_frame, t):
			scale = 1.0 + 0.02 * (t / max(0.0001, seconds))  # ~2% over full duration
			return resize(ImageClip(get_frame(t)), scale).get_frame(0)
		
		clip = clip.fl(zoom)
		clip = clip.set_fps(fps)
		clip.write_videofile(out_path, codec="libx264", audio=False, fps=fps, verbose=False, logger=None)
		
		with open(out_path, "rb") as vf:
			return vf.read()


def maybe_upload_to_cloudinary(app, video_bytes: bytes) -> str:
	cloud_url = app.config.get("CLOUDINARY_URL", "").strip()
	if not cloud_url:
		return ""
	import cloudinary.uploader as cu
	pub = f"test_video_{os.getpid()}"
	res = cu.upload(video_bytes, folder="product_videos", public_id=pub, overwrite=True, resource_type="video")
	return res.get("secure_url") or res.get("url") or ""


def main():
	parser = argparse.ArgumentParser(description="Generate a test product video from mockup image.")
	parser.add_argument("--product-id", type=int, required=True, help="Product ID to build mockup from")
	parser.add_argument("--seconds", type=int, default=8, help="Duration seconds (default 8)")
	parser.add_argument("--no-upload", action="store_true", help="Do not upload to Cloudinary; write local file instead")
	args = parser.parse_args()
	
	# Ensure app is importable
	ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
	if ROOT not in sys.path:
		sys.path.insert(0, ROOT)
	
	from app import create_app
	app = create_app()
	
	with app.app_context():
		mockup = build_mockup_for_product(app, args.product_id)
		video = create_test_video_from_image(mockup, seconds=args.seconds, fps=24)
		if args.no_upload:
			out = os.path.abspath(f"test_product_{args.product_id}.mp4")
			with open(out, "wb") as f:
				f.write(video)
			print(f"Wrote local video: {out}")
		else:
			url = maybe_upload_to_cloudinary(app, video)
			if url:
				print(f"Uploaded video URL: {url}")
			else:
				out = os.path.abspath(f"test_product_{args.product_id}.mp4")
				with open(out, "wb") as f:
					f.write(video)
				print(f"Cloudinary not configured. Wrote local video: {out}")


if __name__ == "__main__":
	main()



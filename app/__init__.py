import os
import click
from flask import Flask, session, render_template
from .config import get_config
from .extensions import db, migrate, login_manager
import cloudinary
import cloudinary.uploader


def create_app() -> Flask:
	app = Flask(__name__, instance_relative_config=False)
	app.config.from_object(get_config())

	# Initialize extensions
	db.init_app(app)
	migrate.init_app(app, db)
	login_manager.init_app(app)
	login_manager.login_view = "admin.login_page"

	# Configure Cloudinary if URL is provided
	cloud_url = app.config.get("CLOUDINARY_URL", "").strip()
	if cloud_url:
		cloudinary.config(cloudinary_url=cloud_url)

	# Register blueprints
	from .main import main_bp
	from .stripe_routes import stripe_bp
	from .admin import admin_bp
	from .feeds_routes import feeds_bp
	from .api_routes import api_bp
	from .cart import cart_bp
	app.register_blueprint(main_bp)
	app.register_blueprint(stripe_bp)
	app.register_blueprint(admin_bp)
	app.register_blueprint(feeds_bp)
	app.register_blueprint(api_bp)
	app.register_blueprint(cart_bp)

	# Dev: auto-create tables if using SQLite
	if app.config.get("SQLALCHEMY_DATABASE_URI", "").startswith("sqlite") and app.config.get("FLASK_ENV", "development") == "development":
		with app.app_context():
			from . import models  # ensure models are imported
			db.create_all()
			_backfill_product_slugs()

	# Context processor for cart count
	@app.context_processor
	def inject_cart_count():
		cart = session.get("cart") or {"items": []}
		count = sum(it.get("quantity", 0) for it in cart.get("items", []))
		return {"cart_count": count}

	# Expose Formspree endpoint to templates
	@app.context_processor
	def inject_forms():
		return {"FORMSPREE_ENDPOINT": app.config.get("FORMSPREE_ENDPOINT", "")}

	# Error handlers
	@app.errorhandler(404)
	def not_found_error(error):
		return render_template('404.html'), 404

	@app.errorhandler(500)
	def internal_error(error):
		return render_template('500.html'), 500

	# CLI commands
	register_commands(app)

	return app


def _backfill_product_slugs() -> None:
	from .models import Product
	from .utils import slugify
	for p in Product.query.filter((Product.slug.is_(None)) | (Product.slug == "")).all():
		base = slugify(p.title)
		slug = base
		idx = 2
		while Product.query.filter_by(slug=slug).first():
			slug = f"{base}-{idx}"
			idx += 1
		p.slug = slug
		db.session.add(p)
	db.session.commit()


def register_commands(app: Flask) -> None:
	from .models import Admin

	@app.cli.command("create-admin")
	@click.argument("email")
	@click.argument("password")
	def create_admin(email: str, password: str) -> None:
		"""Create an admin user with EMAIL and PASSWORD."""
		email_norm = email.strip().lower()
		user = Admin.query.filter_by(email=email_norm).first()
		if user:
			click.echo("Admin already exists")
			return
		user = Admin(email=email_norm)
		user.set_password(password)
		db.session.add(user)
		db.session.commit()
		click.echo("Admin created")

	@app.cli.command("seed-example-products")
	def seed_example_products() -> None:
		from decimal import Decimal
		from .models import Category, Design, Product, Variant
		from .utils import slugify

		def get_or_create_category(name: str, slug: str) -> Category:
			cat = Category.query.filter_by(slug=slug).first()
			if not cat:
				cat = Category(name=name, slug=slug)
				db.session.add(cat)
				db.session.commit()
			return cat

		shirts = get_or_create_category("Shirts", "shirts")
		hoodies = get_or_create_category("Hoodies", "hoodies")
		mugs = get_or_create_category("Mugs", "mugs")

		markup_percent = Decimal(str(app.config.get("MARKUP_PERCENT", 35)))

		samples = [
			{"phrase": "AI Over Everything", "base_cost": Decimal("10.00"), "cat": shirts},
			{"phrase": "No Meetings Just Shipping", "base_cost": Decimal("12.00"), "cat": shirts},
			{"phrase": "Coffee Then Code", "base_cost": Decimal("8.00"), "cat": mugs},
			{"phrase": "Ship It Hoodie", "base_cost": Decimal("20.00"), "cat": hoodies},
		]

		created_count = 0
		for s in samples:
			d = Design.query.filter_by(text=s["phrase"]).first()
			if not d:
				d = Design(type="text", text=s["phrase"], approved=True)
				db.session.add(d)
				db.session.commit()

			price = (s["base_cost"] * (Decimal(1) + markup_percent / Decimal(100))).quantize(Decimal("0.01"))
			base_title = f"Trending '{s['phrase']}' { 'Tee' if s['cat'] == shirts else ('Hoodie' if s['cat'] == hoodies else 'Mug') }"
			title = base_title
			slug = slugify(title)
			idx = 2
			from .models import Product as P
			while P.query.filter_by(slug=slug).first():
				slug = f"{slugify(base_title)}-{idx}"
				idx += 1
			p = P.query.filter_by(slug=slug).first()
			if not p:
				p = P(
					slug=slug,
					title=title,
					description=f"Text design: {s['phrase']}",
					status="active",
					base_cost=s["base_cost"],
					price=price,
					currency=app.config.get("STORE_CURRENCY", "USD"),
					design=d,
				)
				db.session.add(p)
				p.categories.append(s["cat"])
				db.session.commit()
				created_count += 1

			if not p.variants:
				for size in ["S", "M", "L", "XL"]:
					for color in ["Black", "White"]:
						v = Variant(
							product_id=p.id,
							name=f"{size} / {color} / Front",
							color=color,
							size=size,
							print_area="front",
							price=p.price,
							base_cost=p.base_cost,
						)
						db.session.add(v)
				db.session.commit()

		click.echo(f"Seeded {created_count} example products (and variants).")


# Allow `flask --app app run`
app = create_app()

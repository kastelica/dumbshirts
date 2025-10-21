from datetime import datetime
from typing import Optional
from flask_login import UserMixin
from passlib.hash import pbkdf2_sha256
from .extensions import db, login_manager


class TimestampMixin:
	created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
	updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class Admin(UserMixin, db.Model, TimestampMixin):
	id = db.Column(db.Integer, primary_key=True)
	email = db.Column(db.String(255), unique=True, nullable=False)
	password_hash = db.Column(db.String(255), nullable=False)
	is_active = db.Column(db.Boolean, default=True, nullable=False)

	def set_password(self, password: str) -> None:
		self.password_hash = pbkdf2_sha256.hash(password)

	def check_password(self, password: str) -> bool:
		return pbkdf2_sha256.verify(password, self.password_hash)


@login_manager.user_loader
def load_user(user_id: str) -> Optional["Admin"]:
	return db.session.get(Admin, int(user_id))


product_category = db.Table(
	"product_category",
	db.Column("product_id", db.Integer, db.ForeignKey("product.id"), primary_key=True),
	db.Column("category_id", db.Integer, db.ForeignKey("category.id"), primary_key=True),
)

# Link products to trends (tags)
product_trend = db.Table(
	"product_trend",
	db.Column("product_id", db.Integer, db.ForeignKey("product.id"), primary_key=True),
	db.Column("trend_id", db.Integer, db.ForeignKey("trend.id"), primary_key=True),
)


class Category(db.Model, TimestampMixin):
	id = db.Column(db.Integer, primary_key=True)
	name = db.Column(db.String(120), unique=True, nullable=False)
	slug = db.Column(db.String(160), unique=True, nullable=False)


class Design(db.Model, TimestampMixin):
	id = db.Column(db.Integer, primary_key=True)
	type = db.Column(db.String(32), nullable=False)  # 'text' or 'image'
	text = db.Column(db.String(255))
	image_url = db.Column(db.String(500))
	approved = db.Column(db.Boolean, default=False, nullable=False)
	preview_url = db.Column(db.String(500))
	# Optional extra images for galleries
	extra_image1_url = db.Column(db.String(500))
	extra_image2_url = db.Column(db.String(500))


class Trend(db.Model, TimestampMixin):
	id = db.Column(db.Integer, primary_key=True)
	term = db.Column(db.String(255), nullable=False)
	normalized = db.Column(db.String(255), unique=True, index=True, nullable=False)
	slug = db.Column(db.String(200), unique=True, index=True)
	source = db.Column(db.String(50))
	geo = db.Column(db.String(10), default="US")
	status = db.Column(db.String(20), default="new", index=True)  # new|approved|ignored
	primary_image_url = db.Column(db.String(500))
	notes = db.Column(db.Text)
	# backrefs
	products = db.relationship("Product", secondary=product_trend, backref=db.backref("trends", lazy=True))


class Product(db.Model, TimestampMixin):
	id = db.Column(db.Integer, primary_key=True)
	slug = db.Column(db.String(200), unique=True, index=True)
	title = db.Column(db.String(255), nullable=False)
	description = db.Column(db.Text)
	status = db.Column(db.String(32), default="draft", nullable=False)  # draft|active|archived
	base_cost = db.Column(db.Numeric(10, 2), nullable=False, default=0)
	price = db.Column(db.Numeric(10, 2), nullable=False, default=0)
	currency = db.Column(db.String(3), nullable=False, default="USD")
	gelato_product_id = db.Column(db.String(120))

	design_id = db.Column(db.Integer, db.ForeignKey("design.id"))
	design = db.relationship("Design", backref=db.backref("products", lazy=True))

	categories = db.relationship("Category", secondary=product_category, backref=db.backref("products", lazy=True))
	variants = db.relationship("Variant", backref="product", cascade="all, delete-orphan", lazy=True)


class Variant(db.Model, TimestampMixin):
	id = db.Column(db.Integer, primary_key=True)
	product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
	name = db.Column(db.String(120), nullable=False)  # e.g., "S / Black / Front"
	color = db.Column(db.String(60))
	size = db.Column(db.String(20))
	print_area = db.Column(db.String(20), default="front")
	gelato_sku = db.Column(db.String(120))  # store Gelato productUid here
	inventory_policy = db.Column(db.String(20), default="pod")  # pod|stock
	price = db.Column(db.Numeric(10, 2), nullable=False, default=0)
	base_cost = db.Column(db.Numeric(10, 2), nullable=False, default=0)


class Address(db.Model, TimestampMixin):
	id = db.Column(db.Integer, primary_key=True)
	company_name = db.Column(db.String(120))
	first_name = db.Column(db.String(60))
	last_name = db.Column(db.String(60))
	address_line1 = db.Column(db.String(120))
	address_line2 = db.Column(db.String(120))
	city = db.Column(db.String(60))
	state = db.Column(db.String(60))
	post_code = db.Column(db.String(20))
	country = db.Column(db.String(2))
	email = db.Column(db.String(120))
	phone = db.Column(db.String(30))


class Order(db.Model, TimestampMixin):
	id = db.Column(db.Integer, primary_key=True)
	status = db.Column(db.String(32), default="pending", nullable=False)  # pending|paid|submitted|fulfilled|failed|cancelled
	currency = db.Column(db.String(3), nullable=False, default="USD")
	total_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0)
	stripe_payment_intent_id = db.Column(db.String(120), index=True)
	gelato_order_id = db.Column(db.String(120), index=True)
	shipment_method_uid = db.Column(db.String(80))

	shipping_address_id = db.Column(db.Integer, db.ForeignKey("address.id"))
	shipping_address = db.relationship("Address", foreign_keys=[shipping_address_id])

	items = db.relationship("OrderItem", backref="order", cascade="all, delete-orphan", lazy=True)


class OrderItem(db.Model, TimestampMixin):
	id = db.Column(db.Integer, primary_key=True)
	order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False)
	product_id = db.Column(db.Integer, db.ForeignKey("product.id"))
	variant_id = db.Column(db.Integer, db.ForeignKey("variant.id"))
	title = db.Column(db.String(255))
	quantity = db.Column(db.Integer, nullable=False, default=1)
	unit_price = db.Column(db.Numeric(10, 2), nullable=False, default=0)
	product_uid = db.Column(db.String(160))  # cached Gelato productUid used

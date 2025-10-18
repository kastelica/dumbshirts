import os
from typing import Type


class BaseConfig:
	SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
	SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///trendmerch.db")
	SQLALCHEMY_TRACK_MODIFICATIONS = False

	# Payments / Integrations
	STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
	STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
	STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
	GELATO_API_KEY = os.getenv("GELATO_API_KEY", "")
	OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
	FORMSPREE_ENDPOINT = os.getenv("FORMSPREE_ENDPOINT", "")
	# Auto mode controls
	AUTO_MODE = os.getenv("AUTO_MODE", "false").lower() == "true"
	AUTO_MODE_GENERATE_IMAGES = os.getenv("AUTO_MODE_GENERATE_IMAGES", "false").lower() == "true"

	# Store
	MARKUP_PERCENT = float(os.getenv("MARKUP_PERCENT", "35"))
	STORE_CURRENCY = os.getenv("STORE_CURRENCY", "USD")
	BASE_URL = os.getenv("BASE_URL", "http://localhost:5000")
	DEFAULT_SHIPMENT_METHOD = os.getenv("DEFAULT_SHIPMENT_METHOD", "express")
	# Default tee productUid (placeholder; override in env if needed)
	DEFAULT_TEE_UID = os.getenv(
		"DEFAULT_TEE_UID",
		"apparel_product_gca_t-shirt_gsc_crewneck_gcu_unisex_gqa_classic_gsi_s_gco_white_gpr_4-4",
	)


class DevelopmentConfig(BaseConfig):
	DEBUG = True


class ProductionConfig(BaseConfig):
	DEBUG = False


def get_config() -> Type[BaseConfig]:
	env = os.getenv("FLASK_ENV", "development").lower()
	if env == "production":
		return ProductionConfig
	return DevelopmentConfig

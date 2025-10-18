import re


def slugify(value: str) -> str:
	value = value.strip().lower()
	# replace non-alphanumeric with hyphens
	value = re.sub(r"[^a-z0-9]+", "-", value)
	# collapse multiple hyphens
	value = re.sub(r"-+", "-", value)
	return value.strip("-")


def normalize_trend_term(term: str) -> str:
	"""Create a normalized key for trends (lowercase, alnum/space, max 5 words)."""
	if not term:
		return ""
	text = term.strip().lower()
	# allow letters/numbers/spaces only
	text = re.sub(r"[^a-z0-9\s]", "", text)
	# collapse whitespace
	text = re.sub(r"\s+", " ", text).strip()
	# limit to first 5 words
	parts = text.split(" ")
	limited = " ".join(parts[:5])
	return limited

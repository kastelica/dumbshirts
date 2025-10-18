import re
from typing import List


_NEGATIVE_VERBS = [
	"rejects", "blocks", "bans", "halts", "ends", "kills", "axes", "scraps", "stops",
]
_POSITIVE_VERBS = [
	"wins", "holds", "edges", "beats", "leads", "clinches", "secures", "dominates", "stuns",
]
_BRAND_TERMS = [
	"windows 10", "iphone", "android", "tiktok", "ai", "comet", "nasa", "moonship",
]
_PREP_WORDS = ["on", "over", "of", "to", "for", "against", "about"]
_STOPWORDS = set(
	[
		"the", "a", "an", "and", "or", "in", "at", "is", "are", "now", "with", "from",
		"this", "that", "after", "before", "last", "first", "new", "next", "then", "than",
	]
)


def _strip_meme_words(text: str) -> str:
	"""Remove standalone 'meme'/'memes' tokens and tidy whitespace/punctuation."""
	no_meme = re.sub(r"\bmemes?\b", "", text, flags=re.IGNORECASE)
	# collapse extra spaces and stray punctuation spacing
	no_meme = re.sub(r"\s{2,}", " ", no_meme).strip()
	no_meme = re.sub(r"\s+([!?.,])", r"\1", no_meme)
	return no_meme


def _pluralize_simple(word: str) -> str:
	if not word:
		return word
	if word.endswith("s"):
		return word
	return word + "s"


def _extract_object_phrase(title: str) -> str:
	# Try to capture phrase after a preposition following a negative verb
	lower = title.lower()
	for v in _NEGATIVE_VERBS:
		if v in lower:
			for p in _PREP_WORDS:
				m = re.search(rf"\b{v}\b.*\b{p}\b\s+(.+)$", lower)
				if m:
					obj = m.group(1)
					# Keep capitalized words or nouns-looking tokens
					parts = [w for w in re.split(r"[^a-z0-9\-']+", obj) if w and w not in _STOPWORDS]
					if parts:
						# Prefer last meaningful token
						candidate = parts[-1]
						return candidate
	# Fallback: take notable capitalized word in the title
	cap_words = re.findall(r"\b([A-Z][a-zA-Z0-9]+)\b", title)
	if cap_words:
		return cap_words[-1]
	return ""


def _extract_person_name(title: str) -> str:
	m = re.match(r"^([A-Z][a-z]+\s+[A-Z][a-z]+)\b", title)
	return m.group(1) if m else ""


def generate_candidates_from_title(title: str, max_candidates: int = 2) -> List[str]:
	title = _strip_meme_words(title.strip())
	candidates: List[str] = []
	lower = title.lower()

	# Pattern 1: negative verbs -> "No <object>"
	if any(v in lower for v in _NEGATIVE_VERBS):
		obj = _extract_object_phrase(title)
		if obj:
			candidates.append(_strip_meme_words(f"No {_pluralize_simple(obj.capitalize())}"))

	# Pattern 2: sports/achievement verbs with leading person -> "Go <Name>"
	if not candidates and any(v in lower for v in _POSITIVE_VERBS):
		name = _extract_person_name(title)
		if name:
			candidates.append(_strip_meme_words(f"Go {name}"))

	# Pattern 3: brand/tech terms -> "I love <Term>"
	for term in _BRAND_TERMS:
		if term in lower:
			candidates.append(_strip_meme_words(f"I love {term.title()}"))
			break

	# Fallback: pick the first two capitalized words -> "Go X Y"
	if not candidates:
		caps = re.findall(r"\b([A-Z][a-zA-Z0-9']+)\b", title)
		if len(caps) >= 1:
			candidates.append(_strip_meme_words("Go " + " ".join(caps[:2])))

	# Deduplicate and limit
	seen = set()
	unique = []
	for c in candidates:
		c = _strip_meme_words(c)
		if c and c.lower() not in seen:
			seen.add(c.lower())
			unique.append(c)
			if len(unique) >= max_candidates:
				break
	return unique


def memeify_term(term: str, max_candidates: int = 3) -> List[str]:
	"""Generate merch-friendly phrases from a short term/keyword.
	Examples: "Tomahawk missiles" -> ["No Tomahawk Missiles", "I love Tomahawk Missiles"]
	"""
	clean = _strip_meme_words(term.strip().strip('\"\''))
	# Title-case words but keep ALL-CAPS acronyms
	words = [w.upper() if w.isupper() else w.capitalize() for w in re.split(r"\s+", clean) if w]
	nice = _strip_meme_words(" ".join(words))

	suggestions: List[str] = []
	if nice:
		suggestions.append(_strip_meme_words(f"I love {nice}"))
		suggestions.append(_strip_meme_words(f"No {_pluralize_simple(nice)}"))
		suggestions.append(_strip_meme_words(f"Go {nice}"))

	# Deduplicate
	seen = set()
	ordered = []
	for s in suggestions:
		s = _strip_meme_words(s)
		ls = s.lower()
		if s and ls not in seen:
			seen.add(ls)
			ordered.append(s)
			if len(ordered) >= max_candidates:
				break
	return ordered

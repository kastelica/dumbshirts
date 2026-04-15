import argparse
import json
import time
from typing import Dict, List, Tuple, Set
from urllib.parse import urlencode
import os
import sys

# Ensure project root is on path for importing scripts.scrape_kym_memes
try:
	from scripts.scrape_kym_memes import fetch_html, parse_listing, parse_detail_image, BASE
except Exception:
	ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
	if ROOT not in sys.path:
		sys.path.insert(0, ROOT)
	from scripts.scrape_kym_memes import fetch_html, parse_listing, parse_detail_image, BASE


def normalize(text: str) -> str:
	"""Lowercase, trimmed text for matching."""
	return (text or "").strip().lower()


def tokenize(text: str) -> List[str]:
	"""Split on whitespace and basic punctuation; keep alphanumerics."""
	t = normalize(text)
	tok: List[str] = []
	word = []
	for ch in t:
		if ch.isalnum():
			word.append(ch)
		else:
			if word:
				tok.append("".join(word))
				word = []
	if word:
		tok.append("".join(word))
	return tok


def singularize(word: str) -> str:
	"""Very naive singularization: drop trailing 's' if present."""
	w = (word or "").strip().lower()
	if len(w) > 3 and w.endswith("s"):
		return w[:-1]
	return w


def build_query_terms(query: str) -> Set[str]:
	base_tokens = set(tokenize(query))
	variants: Set[str] = set()
	for t in base_tokens:
		variants.add(t)
		variants.add(singularize(t))
		variants.add(f"{t}s")
	# Basic synonyms for common categories (expandable)
	synonyms: Dict[str, List[str]] = {
		"cat": ["cats", "kitty", "kitties", "kitten", "kittens", "feline", "nyan", "grumpy", "neko", "catgirl"],
		"dog": ["dogs", "puppy", "pup", "doge", "canine"],
	}
	for t in list(variants):
		if t in synonyms:
			for s in synonyms[t]:
				variants.add(s)
	return {v for v in variants if v}


def fuzzy_match(title: str, query_terms: Set[str]) -> Tuple[bool, int]:
	"""
	Heuristic matcher:
	- Direct substring of query term in title -> strong match
	- Token overlap (including singular/plural) -> medium match
	- Prefix match of tokens -> weak match
	Returns (matched, score).
	"""
	t = normalize(title)
	if not t:
		return False, 0
	title_tokens = set(tokenize(t))
	title_tokens_singular = {singularize(x) for x in title_tokens}

	score = 0
	# Direct substring bonus
	for q in query_terms:
		# Only count substring if reasonably long to avoid false positives (e.g., 'mao' in 'lmao')
		if len(q) >= 4 and q in t:
			score += 5
	# Token overlap
	overlap = title_tokens & query_terms
	if overlap:
		score += 3 * len(overlap)
	# Singular/plural token overlap
	sp_overlap = title_tokens_singular & {singularize(x) for x in query_terms}
	if sp_overlap:
		score += 2 * len(sp_overlap)
	# Prefix matches
	for q in query_terms:
		for tok in title_tokens:
			if tok.startswith(q) or q.startswith(tok):
				score += 1

	return (score > 0), score


def fetch_listings_across_pages(pages: int = 3) -> List[Dict[str, str]]:
	"""
	Fetch multiple listing pages to broaden the candidate pool.
	We use 'sort=views' pages 1..N.
	"""
	all_entries: List[Dict[str, str]] = []
	seen: Set[Tuple[str, str]] = set()
	base_url = f"{BASE}/memes?kind=all&sort=views"
	for page in range(1, pages + 1):
		url = f"{base_url}&{urlencode({'page': page})}"
		try:
			html = fetch_html(url)
			entries = parse_listing(html)
			for e in entries:
				key = (e.get("title", ""), e.get("slug", ""))
				if key in seen:
					continue
				seen.add(key)
				all_entries.append(e)
			# Be polite
			time.sleep(0.2)
		except Exception:
			continue
	return all_entries


def fetch_search_results(query: str, pages: int = 3, limit: int = 50) -> List[Dict[str, str]]:
	"""
	Broad KYM search using listing pages + fuzzy match on titles,
	then enrich with canonical image from the detail page.
	"""
	query_terms = build_query_terms(query)
	candidates = fetch_listings_across_pages(pages=pages)

	# Score and filter
	scored: List[Tuple[int, Dict[str, str]]] = []
	for e in candidates:
		title = e.get("title", "")
		matched, score = fuzzy_match(title, query_terms)
		if matched:
			scored.append((score, e))
	# Sort by score desc, then keep top N
	scored.sort(key=lambda x: x[0], reverse=True)
	shortlist = [e for _, e in scored[:limit]]

	# Enrich with image
	results: List[Dict[str, str]] = []
	for e in shortlist:
		try:
			dhtml = fetch_html(e["url"])
			img = parse_detail_image(dhtml)
		except Exception:
			img = ""
		results.append({"title": e.get("title", ""), "slug": e.get("slug", ""), "url": e.get("url", ""), "image": img})
		# Be polite
		time.sleep(0.15)
	return results


def main():
	parser = argparse.ArgumentParser(description="Test KYM search with fuzzy matching and detail image extraction.")
	parser.add_argument("query", nargs="?", default="cat", help="Search term (default: cat)")
	parser.add_argument("--pages", type=int, default=3, help="Number of listing pages to scan (default: 3)")
	parser.add_argument("--limit", type=int, default=50, help="Max number of results to return (default: 50)")
	args = parser.parse_args()

	results = fetch_search_results(args.query, pages=args.pages, limit=args.limit)
	print(json.dumps({"query": args.query, "count": len(results), "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
	main()



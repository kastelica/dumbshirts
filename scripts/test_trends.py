import argparse
from pprint import pprint
import os
import sys

# Ensure project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.trends import (
	fetch_trending_phrases_debug,
	fetch_news_trending_phrases_debug,
	fetch_trending_phrases_any,
	fetch_serpapi_trending_phrases_debug,
)


def main() -> int:
	parser = argparse.ArgumentParser(description="Test trend sources")
	parser.add_argument("--geo", default="US", help="Region code, e.g., US, GB, CA")
	parser.add_argument("--limit", type=int, default=10, help="Max phrases to return")
	parser.add_argument("--source", choices=["serpapi", "trendspy", "news", "any"], default="any", help="Which source to use")
	args = parser.parse_args()

	if args.source == "serpapi":
		phrases, debug = fetch_serpapi_trending_phrases_debug(geo=args.geo, limit=args.limit)
	elif args.source == "trendspy":
		phrases, debug = fetch_trending_phrases_debug(geo=args.geo, limit=args.limit)
	elif args.source == "news":
		phrases, debug = fetch_news_trending_phrases_debug(geo=args.geo, limit=args.limit)
	else:
		phrases, debug = fetch_trending_phrases_any(geo=args.geo, limit=args.limit)

	print("Source:", args.source)
	print("Geo:", args.geo)
	print("Limit:", args.limit)
	print("Count:", len(phrases))
	print("Debug:")
	pprint(debug)
	print("\nPhrases:")
	for p in phrases:
		print("-", p)

	return 0


if __name__ == "__main__":
	raise SystemExit(main())

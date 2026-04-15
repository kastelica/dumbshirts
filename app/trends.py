from typing import List, Tuple, Dict
from datetime import datetime
import requests
import re
import os
from xml.etree.ElementTree import fromstring


_DEF_HL_GL = {
	"US": ("en-US", "US"),
	"GB": ("en-GB", "GB"),
	"UK": ("en-GB", "GB"),
	"CA": ("en-CA", "CA"),
	"AU": ("en-AU", "AU"),
}

SERPAPI_ENDPOINT = "https://serpapi.com/search"


def fetch_serpapi_trending_phrases_debug(geo: str = "US", limit: int = 10) -> Tuple[List[str], Dict[str, str]]:
	api_key = os.getenv("SERPAPI_API_KEY", "").strip()
	dbg: Dict[str, str] = {"geo": geo, "limit": str(limit), "endpoint": "serpapi.google_trends"}
	if not api_key:
		dbg["error"] = "missing_api_key"
		return [], dbg

	# Use a broader seed list to increase unique candidates per single SerpAPI call batch
	seeds = [
		"meme", "funny", "tshirt", "hoodie", "gift",
		"viral", "trend", "pop culture", "internet", "slang",
	]
	phrases: List[str] = []
	seen = set()
	for seed in seeds:
		params = {
			"engine": "google_trends",
			"data_type": "RELATED_QUERIES",
			"q": seed,
			"geo": geo,
			"date": "now 7-d",
			"output": "json",
			"api_key": api_key,
			"no_cache": "true",
		}
		try:
			resp = requests.get(SERPAPI_ENDPOINT, params=params, timeout=20)
			dbg_key = f"seed_{seed}_status"
			dbg[dbg_key] = str(resp.status_code)
			resp.raise_for_status()
			data = resp.json()
			# Heuristic extraction of strings
			items = []
			if isinstance(data, dict):
				# Common fields pattern
				for key in ("related_queries", "related_topics", "results", "data"):
					val = data.get(key)
					if isinstance(val, list):
						items.extend(val)
					elif isinstance(val, dict):
						for v in val.values():
							if isinstance(v, list):
								items.extend(v)
			
			candidates: List[str] = []
			for it in items:
				if not isinstance(it, dict):
					continue
				for field in ("query", "title", "name", "topic"):
					val = it.get(field)
					if isinstance(val, str) and val.strip():
						candidates.append(val.strip())
			# Fallback: try nested paths
			if not candidates and isinstance(data, dict):
				for v in data.values():
					if isinstance(v, list):
						for it in v:
							if isinstance(it, dict):
								q = it.get("query") or it.get("title")
								if isinstance(q, str) and q.strip():
									candidates.append(q.strip())
			for c in candidates:
				lc = c.lower()
				if lc not in seen:
					seen.add(lc)
					phrases.append(c)
					if len(phrases) >= limit:
						break
			if len(phrases) >= limit:
				break
		except Exception as e:
			dbg[f"seed_{seed}_error"] = str(e)

	dbg["count"] = str(len(phrases))
	return phrases[:limit], dbg


def fetch_trending_phrases_debug(geo: str = "US", limit: int = 10) -> Tuple[List[str], Dict[str, str]]:
    # Backward-compat shim: now delegates to SerpAPI primary
    phrases, dbg = fetch_serpapi_trending_phrases_debug(geo=geo, limit=limit)
    if phrases:
        return phrases, {**dbg, "via": "serpapi"}
    # Fallback to Google News
    news, news_dbg = fetch_news_trending_phrases_debug(geo=geo, limit=limit)
    return news, {**news_dbg, "via": "news"}


def fetch_news_trending_phrases_debug(geo: str = "US", limit: int = 10) -> Tuple[List[str], Dict[str, str]]:
	hl, gl = _DEF_HL_GL.get(geo.upper(), ("en-US", "US"))
	url = f"https://news.google.com/rss?hl={hl}&gl={gl}&ceid={gl}:{hl.split('-')[0]}"
	dbg = {"news_url": url}
	try:
		resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
		dbg["news_status"] = str(resp.status_code)
		resp.raise_for_status()
		root = fromstring(resp.content)
		titles: List[str] = []
		seen = set()
		scanned = 0
		for item in root.iterfind('.//item/title'):
			scanned += 1
			text = (item.text or '').strip()
			text = text.split(' - ')[0]
			text = re.sub(r"[\u2018\u2019\u201C\u201D]", "'", text)
			text = re.sub(r"[^A-Za-z0-9\s'!?:.,]", "", text)
			if 3 <= len(text) <= 60:
				key = text.lower()
				if key not in seen:
					seen.add(key)
					titles.append(text)
					if len(titles) >= limit:
						break
		dbg["news_scanned"] = str(scanned)
		dbg["news_accepted"] = str(len(titles))
		return titles, dbg
	except Exception as e:
		dbg["news_error"] = str(e)
		return [], dbg


def fetch_trending_phrases_any(geo: str = "US", limit: int = 10) -> Tuple[List[str], Dict[str, str]]:
    # 1) SerpAPI primary
    phrases, debug = fetch_serpapi_trending_phrases_debug(geo=geo, limit=limit)
    if phrases:
        d = {**debug, "source": "serpapi"}
        return phrases, d
    # 2) Google News fallback
    news_phrases, news_debug = fetch_news_trending_phrases_debug(geo=geo, limit=limit)
    merged_debug = {**debug, **{f"news_{k}": v for k, v in news_debug.items()}, "source": "news" if news_phrases else "none"}
    return news_phrases, merged_debug


def fetch_trending_phrases(geo: str = "US", limit: int = 10) -> List[str]:
	phrases, _ = fetch_trending_phrases_any(geo=geo, limit=limit)
	return phrases

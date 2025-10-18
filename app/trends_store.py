import json
import os
from datetime import datetime
from typing import Any, Dict, Optional


_CACHE_DIR = os.path.join(os.path.dirname(__file__), "data")
_CACHE_FILE = os.path.join(_CACHE_DIR, "trends_cache.json")


def _ensure_dir() -> None:
	os.makedirs(_CACHE_DIR, exist_ok=True)


def load_cache(geo: str) -> Optional[Dict[str, Any]]:
	try:
		with open(_CACHE_FILE, "r", encoding="utf-8") as f:
			data = json.load(f)
		return data.get(geo.upper())
	except FileNotFoundError:
		return None
	except Exception:
		return None


def save_cache(geo: str, phrases: list, debug: dict) -> None:
	_ensure_dir()
	blob: Dict[str, Any] = {}
	try:
		with open(_CACHE_FILE, "r", encoding="utf-8") as f:
			blob = json.load(f)
	except Exception:
		blob = {}
	blob[geo.upper()] = {
		"phrases": phrases,
		"debug": debug,
		"ts": datetime.utcnow().isoformat() + "Z",
	}
	with open(_CACHE_FILE, "w", encoding="utf-8") as f:
		json.dump(blob, f, ensure_ascii=False, indent=2)

import os
import sys
import json
import re
from typing import Any, Dict, List, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.gelato_client import GelatoClient  # noqa: E402


def find_color_like_entries(obj: Any, path: str = "") -> List[Tuple[str, Any]]:
    results: List[Tuple[str, Any]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_path = f"{path}.{k}" if path else k
            if re.search(r"color|colour|swatch", k, re.IGNORECASE):
                results.append((new_path, v))
            results.extend(find_color_like_entries(v, new_path))
    elif isinstance(obj, list):
        for idx, v in enumerate(obj):
            results.extend(find_color_like_entries(v, f"{path}[{idx}]"))
    return results


def extract_image_urls(obj: Any) -> List[str]:
    urls: List[str] = []
    if isinstance(obj, dict):
        for v in obj.values():
            urls.extend(extract_image_urls(v))
    elif isinstance(obj, list):
        for v in obj:
            urls.extend(extract_image_urls(v))
    elif isinstance(obj, str):
        if obj.startswith("http://") or obj.startswith("https://"):
            if re.search(r"\.(png|jpg|jpeg|webp)(\?|$)", obj, re.IGNORECASE):
                urls.append(obj)
    return urls


def main() -> None:
    api_key = os.getenv("GELATO_API_KEY", "").strip()
    if not api_key:
        print("Missing GELATO_API_KEY in environment", file=sys.stderr)
        sys.exit(1)

    default_uid = (
        "apparel_product_gca_t-shirt_gsc_crewneck_gcu_unisex_"
        "gqa_heavy-weight_gsi_l_gco_white_gpr_4-0_gildan_5000"
    )
    product_uid = sys.argv[1] if len(sys.argv) > 1 else default_uid

    client = GelatoClient(api_key=api_key)
    data: Dict[str, Any] = client.get_product_v3(product_uid)

    print("=== Raw keys ===")
    print(sorted(list(data.keys())))

    attrs = data.get("attributes") or {}
    print("\n=== Attributes (top-level) ===")
    print(json.dumps(attrs, indent=2, ensure_ascii=False))

    print("\n=== Color-like entries (any depth) ===")
    for path, val in find_color_like_entries(data):
        snippet = val
        try:
            snippet = json.dumps(val, ensure_ascii=False)[:400]
        except Exception:
            snippet = str(val)[:400]
        print(f"- {path}: {snippet}")

    print("\n=== Image URLs discovered ===")
    urls = extract_image_urls(data)
    for u in urls:
        print(u)

    # Heuristic: print whether we see color choices
    color_candidates = []
    for path, val in find_color_like_entries(data):
        if isinstance(val, list) and all(isinstance(x, str) for x in val):
            color_candidates.extend([str(x) for x in val])
        elif isinstance(val, str):
            if len(val) <= 40 and re.search(r"(black|white|red|blue|green|yellow|pink|gray|grey|navy|maroon|orange)", val, re.IGNORECASE):
                color_candidates.append(val)
    uniq = []
    seen = set()
    for c in color_candidates:
        lc = c.lower()
        if lc not in seen:
            seen.add(lc)
            uniq.append(c)
    print("\n=== Color candidates (heuristic) ===")
    for c in uniq:
        print("-", c)


if __name__ == "__main__":
    main()



import re
import sys
import tomllib
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


def load_toml(path: str) -> Dict[str, Any]:
    with open(path, "rb") as f:
        return tomllib.load(f)


def re_space_after_comma(s: str) -> str:
    # turn ",   " into ", "
    parts = [p.strip() for p in s.split(",")]
    return ", ".join(parts)


def normalize(obj):
    """
    Normalize nested structures for stable comparisons:
    - dicts: normalize values
    - lists: sort if possible (strings/dicts), normalize items
    - strings: normalize requires-python commas spacing
    """
    if isinstance(obj, dict):
        return {k: normalize(v) for k, v in obj.items()}

    if isinstance(obj, list):
        items = [normalize(x) for x in obj]
        if all(isinstance(x, str) for x in items):
            return sorted(items)
        if all(isinstance(x, dict) for x in items):
            return sorted(items, key=lambda d: repr(sorted(d.items())))
        return items

    if isinstance(obj, str):
        if "," in obj:
            obj = re_space_after_comma(obj)
        return obj

    return obj

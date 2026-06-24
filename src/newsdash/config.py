"""Load and validate the source config (config/sources.yaml)."""

from typing import Any, Dict, List

import yaml

from . import CONFIG_PATH

_DEFAULTS = {"fetch_interval_seconds": 60, "timeout_seconds": 15}


def load_config() -> Dict[str, Any]:
    """Return the parsed config with defaults filled in. Fails loudly if malformed."""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Source config not found at {CONFIG_PATH}")

    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    defaults = {**_DEFAULTS, **(raw.get("defaults") or {})}
    sources = raw.get("sources") or []
    if not isinstance(sources, list) or not sources:
        raise ValueError(f"No sources defined in {CONFIG_PATH}")

    seen_ids = set()
    cleaned: List[Dict[str, Any]] = []
    for i, src in enumerate(sources):
        for key in ("id", "name", "url"):
            if not src.get(key):
                raise ValueError(f"Source #{i} is missing required field '{key}': {src}")
        if src["id"] in seen_ids:
            raise ValueError(f"Duplicate source id '{src['id']}' in {CONFIG_PATH}")
        seen_ids.add(src["id"])
        cleaned.append(
            {
                "id": src["id"],
                "name": src["name"],
                "url": src["url"],
                "category": src.get("category", "general"),
                "weight": int(src.get("weight", 1)),
                "enabled": bool(src.get("enabled", True)),
            }
        )

    return {"defaults": defaults, "sources": cleaned}


def enabled_sources() -> List[Dict[str, Any]]:
    return [s for s in load_config()["sources"] if s["enabled"]]

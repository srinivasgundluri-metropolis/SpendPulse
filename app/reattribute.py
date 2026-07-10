"""Optional household reattribution rules (local config, not shipped with secrets).

Copy `data/household.example.json` → `data/household.json` and edit.
If no config file exists, reattribution is a no-op.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "household.json"
_cached: dict | None = None
_cached_mtime: float | None = None


def _load_config() -> dict:
    global _cached, _cached_mtime
    if not _CONFIG_PATH.exists():
        _cached = {}
        _cached_mtime = None
        return _cached
    mtime = _CONFIG_PATH.stat().st_mtime
    if _cached is not None and _cached_mtime == mtime:
        return _cached
    try:
        _cached = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        _cached = {}
    _cached_mtime = mtime
    return _cached or {}


def _target_member() -> tuple[str, str]:
    cfg = _load_config()
    name = (cfg.get("reattribute_cardholder") or "").strip()
    card = (cfg.get("reattribute_card_ending") or "").strip()
    return name, card


def _starbucks_store_number(description: str) -> str | None:
    m = re.search(r"STARBUCKS\s+STORE\s+(\d+)", description or "", re.I)
    return m.group(1) if m else None


def is_starbucks_gift_card(description: str) -> bool:
    upper = (description or "").upper()
    return "STARBUCKS" in upper and "GIFT" in upper and "CARD" in upper


def is_uic_area_starbucks(description: str) -> bool:
    """True when description matches configured campus Starbucks stores/cues."""
    cfg = _load_config()
    stores = {str(s) for s in (cfg.get("starbucks_store_numbers") or [])}
    cues = [str(c).upper() for c in (cfg.get("starbucks_location_cues") or [])]
    text = description or ""
    store = _starbucks_store_number(text)
    if store and store in stores:
        return True
    upper = text.upper()
    if "STARBUCKS" in upper and any(cue in upper for cue in cues):
        return True
    return False


def is_jeevitha_starbucks(description: str) -> bool:
    """True when household Starbucks reattribution should apply (requires config)."""
    name, _card = _target_member()
    if not name:
        return False
    return is_starbucks_gift_card(description) or is_uic_area_starbucks(description)


def __getattr__(name: str):
    """Support `from reattribute import JEEVITHA, JEEVITHA_CARD` without hardcoding PII."""
    if name in {"JEEVITHA", "HOUSEHOLD_MEMBER"}:
        return _target_member()[0]
    if name in {"JEEVITHA_CARD", "HOUSEHOLD_CARD"}:
        return _target_member()[1]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def reattribute_transaction(tx: dict) -> dict:
    """Return a copy with cardholder fixed when household Starbucks rules apply."""
    name, card = _target_member()
    if not name or not is_jeevitha_starbucks(tx.get("description") or ""):
        return tx

    out = dict(tx)
    if (tx.get("cardholder") or "").strip() == name:
        if card:
            out["card_ending"] = card
        out["reattributed_reason"] = out.get("reattributed_reason") or "Starbucks → household member"
        return out

    out["cardholder"] = name
    if card:
        out["card_ending"] = card
    if is_starbucks_gift_card(tx.get("description") or ""):
        out["reattributed_reason"] = "Starbucks gift card → household member"
    else:
        out["reattributed_reason"] = "Campus-area Starbucks → household member"
    out["reattributed_from"] = tx.get("cardholder") or "Primary"
    return out


def reattribute_statement(statement: dict) -> dict:
    """Return a copy with cardholder fixed when household Starbucks rules apply."""
    name, _card = _target_member()
    if not name:
        return statement
    out = dict(statement)
    out["transactions"] = [reattribute_transaction(t) for t in statement.get("transactions") or []]
    return out

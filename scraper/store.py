"""data/listings.json、geocache.json、status.json 的讀寫與合併。"""
from __future__ import annotations

import difflib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import Listing

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
LISTINGS = DATA / "listings.json"
GEOCACHE = DATA / "geocache.json"
STATUS = DATA / "status.json"
TZ = timezone(timedelta(hours=8))


def now_iso() -> str:
    return datetime.now(TZ).replace(microsecond=0).isoformat()


def _load(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save(path: Path, obj) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def load_listings() -> dict[str, Listing]:
    doc = _load(LISTINGS, {"listings": []})
    out = {}
    for d in doc.get("listings", []):
        try:
            l = Listing.from_dict(d)
            out[l.id] = l
        except Exception:
            continue
    return out


def save_listings(items: dict[str, Listing]) -> None:
    ordered = sorted(items.values(), key=lambda l: (l.first_seen or "", l.id), reverse=True)
    _save(LISTINGS, {"generated_at": now_iso(), "count": len(ordered), "listings": [l.to_dict() for l in ordered]})


def load_geocache() -> dict:
    return _load(GEOCACHE, {})


def save_geocache(cache: dict) -> None:
    _save(GEOCACHE, cache)


def load_status() -> dict:
    return _load(STATUS, {"sources": {}})


def save_status(status: dict) -> None:
    status["updated_at"] = now_iso()
    _save(STATUS, status)


def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a or "", b or "").ratio()


def merge(existing: dict[str, Listing], fresh: list[Listing], keep_days: int) -> list[Listing]:
    """把這次抓到的併進既有資料，回傳真正新增的物件。"""
    ts = now_iso()
    new_items: list[Listing] = []
    for l in fresh:
        if l.id in existing:
            old = existing[l.id]
            # 刷新可變欄位，保留第一次看到的時間與已有的座標
            for f in ("title", "price", "tags", "subsidy", "subsidy_hits", "image", "floor", "layout", "area_ping", "address", "raw_text"):
                v = getattr(l, f)
                if v not in (None, "", [], {}):
                    setattr(old, f, v)
            if l.lat and l.lng and not old.lat:
                old.lat, old.lng = l.lat, l.lng
            if l.posted_at and not old.posted_at:
                old.posted_at = l.posted_at
            old.last_seen = ts
            continue
        # 跨來源弱去重：同價、同區、標題相近 → 併入既有物件的 sources
        dup = None
        if l.price:
            for old in existing.values():
                if old.source == l.source or old.price != l.price or old.district != l.district:
                    continue
                if _similar(old.title, l.title) >= 0.8:
                    dup = old
                    break
        if dup:
            if not any(s.get("url") == l.url for s in dup.sources):
                dup.sources.append({"source": l.source, "url": l.url})
            dup.last_seen = ts
            continue
        l.first_seen = l.first_seen or ts
        l.last_seen = ts
        existing[l.id] = l
        new_items.append(l)

    cutoff = (datetime.now(TZ) - timedelta(days=keep_days)).isoformat()
    for k in [k for k, v in existing.items() if (v.last_seen or "") < cutoff]:
        del existing[k]
    return new_items

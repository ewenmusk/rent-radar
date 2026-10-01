"""地址 → 座標（Nominatim，結構化查詢＋快取）與最近捷運站。"""
from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
STATIONS: list[dict] = json.loads((HERE / "mrt_stations.json").read_text(encoding="utf-8"))

USER_AGENT = "rent-radar/1.0 (personal rental search; github.com)"
NOMINATIM = "https://nominatim.openstreetmap.org/search"

# 行政區中心點（最後退路）
DISTRICT_CENTER = {
    "萬華": (25.0323, 121.4995),
    "板橋": (25.0118, 121.4620),
    "三重": (25.0616, 121.4871),
    "中和": (24.9994, 121.4990),
    "永和": (24.9994, 121.5152),
}

_last_call = 0.0


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest_station(lat: float, lng: float) -> tuple[str, int]:
    best, best_d = None, 1e12
    for s in STATIONS:
        d = haversine_m(lat, lng, s["lat"], s["lng"])
        if d < best_d:
            best, best_d = s, d
    return best["name"], int(best_d)


_STATION_RE = re.compile(
    "(" + "|".join(re.escape(s["name"]) for s in sorted(STATIONS, key=lambda x: -len(x["name"]))) + r")\s*(?:捷運)?站"
)
_BY_NAME = {s["name"]: s for s in STATIONS}
# 雙北大致範圍，Nominatim 回傳落在外面就當查錯
BBOX = (24.85, 25.30, 121.30, 121.75)


def station_by_name(text: str) -> dict | None:
    """只認「頂溪站」「永安市場捷運站」這種明確寫法，避免路名/區名誤判。"""
    if not text:
        return None
    m = _STATION_RE.search(text)
    return _BY_NAME.get(m.group(1)) if m else None


def in_bbox(lat: float, lng: float) -> bool:
    return BBOX[0] <= lat <= BBOX[1] and BBOX[2] <= lng <= BBOX[3]


def simplify_street(address: str) -> list[str]:
    """把地址切成由細到粗的候選：巷 → 路/街 → 無。"""
    if not address:
        return []
    a = re.sub(r"(台北市|臺北市|新北市)", "", address)
    a = re.sub(r"[一-鿿]{1,3}區[-－\s]*", "", a, count=1)
    a = re.sub(r"\d+\s*(號|之\d+|樓|F).*$", "", a).strip("-－ ,，")
    cands = []
    m = re.search(r"^(.*?(?:路|街|大道)(?:[一二三四五六七八九十\d]+段)?(?:\d+巷)?(?:\d+弄)?)", a)
    if m:
        full = m.group(1)
        cands.append(full)
        road = re.sub(r"\d+巷.*$", "", full)
        if road != full:
            cands.append(road)
    elif a:
        cands.append(a)
    return [c for c in cands if c]


class Geocoder:
    def __init__(self, cache: dict[str, list | None], budget: int = 15):
        self.cache = cache
        self.budget = budget
        self.used = 0

    def _nominatim(self, street: str, city: str) -> tuple[float, float] | None:
        global _last_call
        key = f"{city}|{street}"
        if key in self.cache:
            v = self.cache[key]
            return (v[0], v[1]) if v else None
        if self.used >= self.budget:
            return None
        wait = 1.1 - (time.time() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.time()
        self.used += 1
        try:
            r = requests.get(
                NOMINATIM,
                params={"street": street, "city": city, "countrycodes": "tw", "format": "jsonv2", "limit": 1},
                headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-TW"},
                timeout=20,
            )
            data = r.json() if r.ok else []
        except Exception:
            data = []
        if data:
            lat, lng = float(data[0]["lat"]), float(data[0]["lon"])
            if in_bbox(lat, lng):
                self.cache[key] = [lat, lng]
                return lat, lng
        self.cache[key] = None
        return None

    def locate(self, address: str, city: str, district: str, hint_text: str = "") -> tuple[float, float, str] | None:
        """回傳 (lat, lng, precision)。precision: street / station / district。"""
        for street in simplify_street(address):
            res = self._nominatim(street, city or "")
            if res:
                return res[0], res[1], "street"
        st = station_by_name(address) or station_by_name(hint_text or "")
        if st:
            return st["lat"], st["lng"], "station"
        if district in DISTRICT_CENTER:
            lat, lng = DISTRICT_CENTER[district]
            return lat, lng, "district"
        return None

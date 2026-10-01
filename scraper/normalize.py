"""文字正規化：判區域、抓價格、坪數、租補關鍵字。"""
from __future__ import annotations

import re
from typing import Iterable

PRICE_RE = re.compile(
    r"(?:租金|月租|房租|價格|售價)?[:：]?\s*(?:NT\$?|\$)?\s*"
    r"(\d{1,3}(?:,\d{3})+|\d{4,6}|\d(?:\.\d)?\s*萬)"
    r"\s*(?:元|塊|NTD|NT)?\s*(?:/|／|每)?\s*月?",
)
PING_RE = re.compile(r"(\d{1,3}(?:\.\d{1,2})?)\s*坪")
NUM_RE = re.compile(r"\d{1,3}(?:,\d{3})+|\d{4,6}")

KIND_WORDS = [
    ("整層住家", ["整層", "整層住家", "公寓", "整戶", "兩房", "2房", "三房", "3房", "一房一廳", "1房1廳"]),
    ("獨立套房", ["獨立套房", "獨套", "套房"]),
    ("分租套房", ["分租套房", "分租"]),
    ("雅房", ["雅房"]),
]

CITY_WORDS = {"台北市": ["台北", "臺北", "北市"], "新北市": ["新北", "新北市"]}


def detect_district(text: str, districts: Iterable[dict]) -> dict | None:
    if not text:
        return None
    districts = list(districts)
    # 1) 明確寫「X區」的優先，取最早出現的
    best = None
    for d in districts:
        i = text.find(d["name"] + "區")
        if i >= 0 and (best is None or i < best[0]):
            best = (i, d)
    if best:
        return best[1]
    # 2) 只有區名：排除路名／橋名（中山路、中正路、中和路、中正橋…），取最早出現的
    for d in districts:
        for m in re.finditer(re.escape(d["name"]) + r"(?![路街橋東西南北一二三])", text):
            if best is None or m.start() < best[0]:
                best = (m.start(), d)
            break
    return best[1] if best else None


def parse_price(text: str) -> int | None:
    """抓第一個像月租金的數字（3000–100000）。"""
    if not text:
        return None
    candidates: list[int] = []
    for m in PRICE_RE.finditer(text):
        raw = m.group(1).replace(",", "").replace(" ", "")
        try:
            if raw.endswith("萬"):
                val = int(float(raw[:-1]) * 10000)
            else:
                val = int(raw)
        except ValueError:
            continue
        if 3000 <= val <= 100000:
            candidates.append(val)
    if not candidates:
        return None
    # 優先取有「租金/元/月」語境的；PRICE_RE 已經偏好這類，取第一個
    return candidates[0]


def parse_ping(text: str) -> float | None:
    if not text:
        return None
    m = PING_RE.search(text)
    if not m:
        return None
    try:
        v = float(m.group(1))
    except ValueError:
        return None
    return v if 1 <= v <= 300 else None


def detect_kind(text: str) -> str:
    if not text:
        return ""
    for kind, words in KIND_WORDS:
        if any(w in text for w in words):
            return kind
    return ""


def subsidy_hits(text: str, keywords: Iterable[str]) -> list[str]:
    if not text:
        return []
    hits = [k for k in keywords if k in text]
    # 「租補」是「可租補 / 租金補貼」的子字串，避免重複列出
    if "租補" in hits and any(h != "租補" and "租補" in h for h in hits):
        hits.remove("租補")
    return hits


def has_excluded(text: str, keywords: Iterable[str]) -> bool:
    return bool(text) and any(k in text for k in keywords)


def clean_text(s: str) -> str:
    return re.sub(r"[ \t　]+", " ", re.sub(r"\r\n?|\n{2,}", "\n", s or "")).strip()

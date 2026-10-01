"""591 租屋網：抓 SSR 列表頁，解析 window.__NUXT__（CSS 備援），新物件再抓 detail 取座標。"""
from __future__ import annotations

import json
import random
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Any

from bs4 import BeautifulSoup
from curl_cffi import requests as creq

from ..models import Listing
from ..normalize import detect_district, parse_ping, subsidy_hits
from . import SourceBlocked

BASE = "https://rent.591.com.tw"
TZ = timezone(timedelta(hours=8))
KIND_NAMES = {1: "整層住家", 2: "獨立套房", 3: "分租套房", 4: "雅房", 8: "車位", 24: "其他"}
HEADERS = {
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://rent.591.com.tw/",
}


def _sleep(cfg):
    lo, hi = cfg.get("delay", [2, 5])
    time.sleep(random.uniform(lo, hi))


def _get(session: creq.Session, url: str) -> str:
    r = session.get(url, headers=HEADERS, timeout=40)
    if r.status_code in (403, 419, 429):
        raise SourceBlocked(f"HTTP {r.status_code} for {url}")
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code} for {url}")
    return r.text


# ---------- __NUXT__ 解析 ----------

def extract_nuxt(html: str) -> Any | None:
    m = re.search(r"<script[^>]*>\s*(window\.__NUXT__\s*=.*?)</script>", html, re.S)
    if not m:
        return None
    script = m.group(1)
    try:
        from py_mini_racer import MiniRacer  # type: ignore
    except Exception:
        try:
            from mini_racer import MiniRacer  # type: ignore
        except Exception:
            return None
    try:
        ctx = MiniRacer()
        out = ctx.eval("var window={};var document={};" + script + ";JSON.stringify(window.__NUXT__)")
        return json.loads(out)
    except Exception:
        return None


def _walk(obj: Any):
    yield obj
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def find_listing_array(nuxt: Any) -> list[dict]:
    best: list[dict] = []
    for node in _walk(nuxt):
        if isinstance(node, list) and len(node) > len(best) and node and all(isinstance(x, dict) for x in node):
            keys = set(node[0].keys())
            if {"id", "title"} <= keys and ("price" in keys or "price_unit" in keys):
                best = node
    return best


def _first_str(v: Any) -> str | None:
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        for k in ("url", "photo", "src", "image"):
            if isinstance(v.get(k), str):
                return v[k]
    return None


def _to_int(v: Any) -> int | None:
    if v is None:
        return None
    s = re.sub(r"[^\d]", "", str(v))
    return int(s) if s else None


def item_to_listing(item: dict, districts: list[dict], keywords: list[str]) -> Listing | None:
    hid = _to_int(item.get("id") or item.get("post_id"))
    if not hid:
        return None
    title = str(item.get("title") or "").strip()
    address = str(item.get("address") or item.get("area_name") or "").replace("-", "")
    district = detect_district(address + " " + title + " " + str(item.get("section_name") or ""), districts)
    tags_raw = item.get("tags") or []
    tags = [t if isinstance(t, str) else str(t.get("name") or t.get("txt") or "") for t in tags_raw]
    tags = [t for t in tags if t]
    v = item.get("big_mode_tags")
    if isinstance(v, list):
        tags += [t if isinstance(t, str) else str(t.get("name") or t.get("txt") or "") for t in v]
    tags = [t for t in dict.fromkeys(tags) if t]
    kind = str(item.get("kind_name") or KIND_NAMES.get(_to_int(item.get("kind")) or 0, ""))
    # surrounding: {"type": "metro", "desc": "距新埔", "distance": "197公尺"}
    nearest_mrt, mrt_dist = None, None
    surrounding = ""
    sur = item.get("surrounding")
    if isinstance(sur, dict) and sur.get("desc"):
        surrounding = f"{sur.get('desc')} {sur.get('distance') or ''}".strip()
        if sur.get("type") == "metro":
            nearest_mrt = re.sub(r"^距", "", str(sur["desc"])).replace("捷運", "").replace("站", "").strip() or None
            md = re.search(r"(\d+)\s*(公尺|m)", str(sur.get("distance") or ""))
            if md:
                mrt_dist = int(md.group(1))
            else:
                mk = re.search(r"(\d+(?:\.\d+)?)\s*公里", str(sur.get("distance") or ""))
                if mk:
                    mrt_dist = int(float(mk.group(1)) * 1000)
    text_blob = " ".join([title] + tags + [surrounding] + [str(item.get(k) or "") for k in ("extra_fee_text_big", "linkman", "role_name")])
    ping = None
    for k in ("area_name", "area", "area_str", "areaStr", "space", "sqm"):
        if item.get(k) is not None:
            s = str(item[k])
            ping = parse_ping(s + ("坪" if "坪" not in s else ""))
            if ping:
                break
    if ping is None:
        ping = parse_ping(" ".join(str(v) for v in item.values() if isinstance(v, str)))
    photos = item.get("photoList") or item.get("photo_list") or item.get("photos") or []
    image = _first_str(photos[0]) if isinstance(photos, list) and photos else _first_str(item.get("cover") or item.get("photo"))
    hits = subsidy_hits(text_blob, keywords)
    url = item.get("url") if isinstance(item.get("url"), str) and item["url"].startswith("http") else f"{BASE}/{hid}"
    return Listing(
        id=f"rent591:{hid}",
        source="rent591",
        title=title,
        url=url,
        price=_to_int(item.get("price")),
        kind=kind,
        district=district["name"] if district else "",
        city=district["city"] if district else "",
        address=address,
        area_ping=ping,
        floor=str(item.get("floor_name") or item.get("floorStr") or ""),
        layout=str(item.get("layoutStr") or item.get("layout") or ""),
        tags=tags,
        subsidy=bool(hits),
        subsidy_hits=hits,
        image=image,
        nearest_mrt=nearest_mrt,
        mrt_dist_m=mrt_dist,
        raw_text=text_blob,
        extra={
            "refresh_time": item.get("refresh_time"),
            "role_name": item.get("role_name"),
            "community": item.get("community_name"),
            "surrounding": surrounding,
        },
    )


# ---------- CSS 備援 ----------

def parse_cards_css(html: str, districts: list[dict], keywords: list[str]) -> list[Listing]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for card in soup.select("div.item[data-id]"):
        hid = _to_int(card.get("data-id"))
        if not hid:
            continue
        a = card.select_one(".item-info-title a") or card.select_one("a[href*='rent.591.com.tw/']")
        title = a.get_text(strip=True) if a else ""
        href = a.get("href") if a else None
        price = _to_int((card.select_one(".item-info-price") or card).get_text(" ", strip=True).split("元")[0])
        tags = [t.get_text(strip=True) for t in card.select(".item-info-tag span, .item-info-tag .tag")]
        txts = [t.get_text(" ", strip=True) for t in card.select(".item-info-txt")]
        blob = " ".join([title] + tags + txts)
        addr = next((t for t in txts if "區" in t), "")
        district = detect_district(blob, districts)
        img = card.select_one("img")
        image = (img.get("data-src") or img.get("src")) if img else None
        hits = subsidy_hits(blob, keywords)
        kind = ""
        for k in ("整層住家", "獨立套房", "分租套房", "雅房"):
            if k in blob:
                kind = k
                break
        out.append(Listing(
            id=f"rent591:{hid}", source="rent591", title=title,
            url=href if href and href.startswith("http") else f"{BASE}/{hid}",
            price=price, kind=kind, district=district["name"] if district else "",
            city=district["city"] if district else "", address=addr, area_ping=parse_ping(blob),
            tags=tags, subsidy=bool(hits), subsidy_hits=hits, image=image, raw_text=blob,
        ))
    return out


# ---------- detail ----------

def fetch_detail(session: creq.Session, hid: int) -> dict:
    html = _get(session, f"{BASE}/{hid}")
    info: dict = {}
    nuxt = extract_nuxt(html)
    if nuxt is not None:
        for node in _walk(nuxt):
            if isinstance(node, dict):
                pos = node.get("positionRound") or node.get("position")
                if isinstance(pos, dict) and pos.get("lat") and "lat" not in info:
                    try:
                        info["lat"], info["lng"] = float(pos["lat"]), float(pos["lng"])
                    except (TypeError, ValueError):
                        pass
                    if pos.get("address"):
                        info["address"] = str(pos["address"])
                pt = node.get("posttime")
                if isinstance(pt, (int, float)) and pt > 10**9 and "posted_at" not in info:
                    info["posted_at"] = datetime.fromtimestamp(int(pt), TZ).replace(microsecond=0).isoformat()
                if "lat" in info and "posted_at" in info:
                    break
    if "lat" not in info:
        m = re.search(r"lat[\"']?\s*[:=]\s*[\"']?(2[2-6]\.\d{3,})[\"']?\s*,\s*[\"']?lng[\"']?\s*[:=]\s*[\"']?(12[0-2]\.\d{3,})", html)
        if m:
            info["lat"], info["lng"] = float(m.group(1)), float(m.group(2))
    return info


# ---------- 主入口 ----------

def build_queries(cfg: dict, districts: list[dict], price: dict) -> list[str]:
    """每個 (region, kind) 一組查詢；section 可逗號多值，kind 不行（實測 2026-10）。回傳不含 page 的 URL。"""
    by_region: dict[int, list[int]] = {}
    for d in districts:
        by_region.setdefault(int(d["region"]), []).append(int(d["section"]))
    urls = []
    for region, sections in by_region.items():
        for kind in cfg.get("kinds", [1, 2]):
            urls.append(
                f"{BASE}/list?region={region}&section={','.join(map(str, sections))}&kind={kind}"
                f"&rentprice={price['min']},{price['max']}&order=posttime&orderType=desc"
            )
    return urls


def fetch(ctx: dict) -> list[Listing]:
    cfg = ctx["cfg"]["rent591"]
    districts = ctx["cfg"]["districts"]
    price = ctx["cfg"]["price"]
    keywords = ctx["cfg"]["subsidy_keywords"]
    known: set[str] = ctx["known_ids"]
    session = creq.Session(impersonate="chrome")
    results: dict[str, Listing] = {}
    used_css = False
    first_request = True
    for base_url in build_queries(cfg, districts, price):
        for page in range(1, int(cfg.get("pages", 2)) + 1):
            if not first_request:
                _sleep(cfg)
            html = _get(session, f"{base_url}&page={page}")
            if "驗證" in html[:5000] and "captcha" in html.lower()[:5000]:
                raise SourceBlocked("驗證頁")
            nuxt = extract_nuxt(html)
            items = find_listing_array(nuxt) if nuxt is not None else []
            page_listings: list[Listing] = []
            if items:
                for it in items:
                    l = item_to_listing(it, districts, keywords)
                    if l:
                        page_listings.append(l)
            else:
                used_css = True
                page_listings = parse_cards_css(html, districts, keywords)
            if not page_listings:
                if first_request:
                    raise SourceBlocked("列表頁沒有任何物件（疑似被擋或版面改動）")
                break  # 這組查詢沒有更多頁
            first_request = False
            # 591 被擋時可能回假資料：價格超出查詢區間
            prices = [l.price for l in page_listings if l.price]
            if prices and sum(1 for p in prices if not (price["min"] <= p <= price["max"])) > len(prices) * 0.5:
                raise SourceBlocked("列表價格與查詢區間不符，疑似混淆資料")
            for l in page_listings:
                if l.price and not (price["min"] <= l.price <= price["max"]):
                    continue
                results.setdefault(l.id, l)
            if len(page_listings) < 30:
                break  # 已到最後一頁
    ctx["log"](f"591 列表 {len(results)} 筆（{'CSS 備援' if used_css else '__NUXT__'}）")

    # 新物件、以及之前還沒抓過 detail 的舊物件，抓 detail 取座標與刊登時間
    existing: dict = ctx.get("existing", {})
    need = [l for l in results.values()
            if l.id not in known or not (existing.get(l.id) and existing[l.id].extra.get("detail_done"))]
    budget = int(cfg.get("detail_per_run", 20))
    done = 0
    for l in need[:budget]:
        _sleep(cfg)
        try:
            info = fetch_detail(session, int(l.id.split(":")[1]))
        except SourceBlocked:
            ctx["log"]("591 detail 被擋，剩餘座標下次再補")
            break
        except Exception as e:  # noqa: BLE001
            ctx["log"](f"591 detail {l.id} 失敗: {e}")
            continue
        done += 1
        l.extra["detail_done"] = True
        if info.get("lat") and info.get("lng"):
            l.lat, l.lng = info["lat"], info["lng"]
            l.extra["geo_precision"] = "exact"
            l.nearest_mrt, l.mrt_dist_m = None, None  # 讓 run.py 用精確座標重算
        l.posted_at = info.get("posted_at")
        if info.get("address") and len(info["address"]) > len(l.address):
            l.address = info["address"]
    ctx["log"](f"591 detail 抓了 {done} 筆，待補 {max(0, len(need) - done)} 筆")
    return list(results.values())

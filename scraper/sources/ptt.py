"""PTT Rent_apart / Rent_tao 看板。"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup

from ..models import Listing
from ..normalize import clean_text, detect_district, detect_kind, has_excluded, parse_ping, parse_price, subsidy_hits

BASE = "https://www.ptt.cc"
TZ = timezone(timedelta(hours=8))
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) rent-radar/1.0"}
ADDR_RE = re.compile(r"(?:地址|位置|地點|所在地)\s*[:：]?\s*([^\n]{3,45})")
IMG_RE = re.compile(r"https?://(?:i\.)?imgur\.com/([A-Za-z0-9]+)(?:\.(?:jpe?g|png|gif))?")


class _Client:
    """先用 curl_cffi 模擬 Chrome（PTT 的 Cloudflare 會擋機房 IP 的普通 requests），失敗再退回 requests。"""

    def __init__(self):
        self.mode = "curl_cffi"
        try:
            from curl_cffi import requests as creq
            self.s = creq.Session(impersonate="chrome")
            self.s.cookies.set("over18", "1", domain="www.ptt.cc")
        except Exception:
            self._fallback()

    def _fallback(self):
        self.mode = "requests"
        self.s = requests.Session()
        self.s.headers.update(HEADERS)
        self.s.cookies.set("over18", "1", domain="www.ptt.cc")

    def get(self, url: str):
        r = self.s.get(url, timeout=30, headers={"Accept-Language": "zh-TW,zh;q=0.9", "Referer": BASE + "/bbs/index.html"})
        if r.status_code == 403 and self.mode == "curl_cffi":
            self._fallback()
            r = self.s.get(url, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code} ({self.mode}) for {url}")
        return r


def _session() -> _Client:
    return _Client()


def _index_pages(s: _Client, board: str, pages: int):
    url = f"{BASE}/bbs/{board}/index.html"
    for _ in range(pages):
        r = s.get(url)
        soup = BeautifulSoup(r.text, "lxml")
        yield soup
        prev = next((a for a in soup.select("div.btn-group-paging a.btn") if "上頁" in a.get_text()), None)
        if not prev or not prev.get("href"):
            break
        url = BASE + prev["href"]
        time.sleep(0.5)


def _article(s: _Client, url: str) -> tuple[str, str | None]:
    r = s.get(url)
    soup = BeautifulSoup(r.text, "lxml")
    main = soup.select_one("#main-content")
    if not main:
        return "", None
    for meta in main.select("div.article-metaline, div.article-metaline-right, div.push"):
        meta.decompose()
    text = main.get_text("\n")
    text = re.split(r"\n--\n|※ 發信站", text)[0]
    image = None
    for a in main.select("a[href]"):
        m = IMG_RE.search(a["href"])
        if m:
            image = f"https://i.imgur.com/{m.group(1)}.jpg"
            break
    return clean_text(text), image


def fetch(ctx: dict) -> list[Listing]:
    cfg = ctx["cfg"]["ptt"]
    districts = ctx["cfg"]["districts"]
    price = ctx["cfg"]["price"]
    keywords = ctx["cfg"]["subsidy_keywords"]
    exclude = ctx["cfg"]["exclude_keywords"]
    known: set[str] = ctx["known_ids"]
    s = _session()
    out: list[Listing] = []
    for board in cfg.get("boards", []):
        for soup in _index_pages(s, board, int(cfg.get("pages", 3))):
            for ent in soup.select("div.r-ent"):
                a = ent.select_one("div.title a")
                if not a:
                    continue
                title = a.get_text(strip=True)
                href = a.get("href", "")
                m = re.search(r"/M\.(\d+)\.A\.([0-9A-F]+)\.html", href)
                if not m:
                    continue
                pid = f"{board}.{m.group(1)}.{m.group(2)}"
                lid = f"ptt:{pid}"
                district = detect_district(title, districts)
                if not district or has_excluded(title, exclude) or title.startswith("Re:"):
                    continue
                if lid in known:
                    out.append(Listing(id=lid, source="ptt", title=title, url=BASE + href,
                                       district=district["name"], city=district["city"]))
                    continue
                time.sleep(0.6)
                try:
                    body, image = _article(s, BASE + href)
                except Exception as e:  # noqa: BLE001
                    ctx["log"](f"PTT {href} 讀取失敗: {e}")
                    continue
                blob = title + "\n" + body
                p = parse_price(body) or parse_price(title)
                if p and not (price["min"] <= p <= price["max"]):
                    continue
                am = ADDR_RE.search(body)
                hits = subsidy_hits(blob, keywords)
                posted = datetime.fromtimestamp(int(m.group(1)), TZ).replace(microsecond=0).isoformat()
                out.append(Listing(
                    id=lid, source="ptt", title=title, url=BASE + href, price=p,
                    kind=detect_kind(title) or detect_kind(body) or ("獨立套房" if board == "Rent_tao" else ""),
                    district=district["name"], city=district["city"],
                    address=am.group(1).strip() if am else "", area_ping=parse_ping(body),
                    tags=[board], subsidy=bool(hits), subsidy_hits=hits, image=image,
                    posted_at=posted, raw_text=body,
                ))
    ctx["log"](f"PTT 符合 {len(out)} 筆")
    return out

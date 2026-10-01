"""ntfy 推播：每次執行最多一則摘要。"""
from __future__ import annotations

import os

import requests

from .models import Listing

NTFY_URL = os.environ.get("NTFY_URL", "https://ntfy.sh")


def _fmt(l: Listing) -> str:
    price = f"{l.price:,}" if l.price else "價格未知"
    tag = "🏷️" if l.subsidy else "　"
    kind = l.kind or ""
    mrt = f"・{l.nearest_mrt}站{l.mrt_dist_m}m" if l.nearest_mrt and l.mrt_dist_m is not None and l.mrt_dist_m < 1500 else ""
    return f"{tag}{l.district} {kind} {price}{mrt}｜{l.title[:28]}"


def send(topic: str | None, title: str, message: str, click: str | None = None, priority: int = 3, tags: list[str] | None = None) -> bool:
    if not topic:
        print("[notify] NTFY_TOPIC 未設定，略過推播")
        return False
    body = {"topic": topic, "title": title, "message": message[:3800], "priority": priority}
    if click:
        body["click"] = click
        body["actions"] = [{"action": "view", "label": "開啟網頁", "url": click}]
    if tags:
        body["tags"] = tags
    try:
        r = requests.post(NTFY_URL, json=body, timeout=20)
        if r.status_code == 429:
            print("[notify] ntfy 429，本次略過")
            return False
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"[notify] 推播失敗: {e}")
        return False


def notify_new(topic: str | None, new_items: list[Listing], site_url: str) -> bool:
    if not new_items:
        return False
    items = sorted(new_items, key=lambda l: (not l.subsidy, l.price or 10**9))
    n_sub = sum(1 for l in items if l.subsidy)
    title = f"新物件 {len(items)} 筆" + (f"（可租補 {n_sub} 筆）" if n_sub else "")
    lines = [_fmt(l) for l in items[:8]]
    if len(items) > 8:
        lines.append(f"…還有 {len(items) - 8} 筆，開網頁看全部")
    click = f"{site_url.rstrip('/')}/?new=1" if site_url else None
    return send(topic, title, "\n".join(lines), click=click, priority=4 if n_sub else 3, tags=["house"])

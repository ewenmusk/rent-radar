"""主流程：抓 → 正規化 → 合併去重 → 補座標 → 存檔 → 推播。

用法：
  python -m scraper.run                 # 全部來源
  python -m scraper.run --source ptt    # 只跑某來源
  python -m scraper.run --dry-run       # 不寫檔、不推播，只印結果
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path

import yaml

from . import store
from .geocode import Geocoder, nearest_station, station_by_name
from .models import Listing
from .normalize import subsidy_hits
from .notify import notify_new, send
from .sources import SourceBlocked, SourceSkipped, fb_mail, ptt, rent591

HERE = Path(__file__).resolve().parent
SOURCES = {"rent591": rent591.fetch, "ptt": ptt.fetch, "fb": fb_mail.fetch}


def log(msg: str) -> None:
    print(msg, flush=True)


def load_config() -> dict:
    cfg = yaml.safe_load((HERE / "config.yaml").read_text(encoding="utf-8"))
    if os.environ.get("PRICE_MIN"):
        cfg["price"]["min"] = int(os.environ["PRICE_MIN"])
    if os.environ.get("PRICE_MAX"):
        cfg["price"]["max"] = int(os.environ["PRICE_MAX"])
    return cfg


def finalize(l: Listing, cfg: dict) -> None:
    """統一補齊：租補標示、區域。"""
    blob = " ".join([l.title or "", " ".join(l.tags), l.raw_text or ""])
    hits = subsidy_hits(blob, cfg["subsidy_keywords"])
    if hits:
        l.subsidy, l.subsidy_hits = True, hits


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", nargs="*", choices=list(SOURCES), help="只跑指定來源")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-notify", action="store_true")
    args = ap.parse_args(argv)

    cfg = load_config()
    existing = store.load_listings()
    status = store.load_status()
    status.setdefault("sources", {})
    first_run = not existing
    ctx = {"cfg": cfg, "known_ids": set(existing), "existing": existing, "dry_run": args.dry_run, "log": log}

    fresh: list[Listing] = []
    blocked591 = False
    for name, fn in SOURCES.items():
        if args.source and name not in args.source:
            continue
        st = status["sources"].setdefault(name, {"consecutive_failures": 0})
        try:
            items = fn(ctx)
            for l in items:
                finalize(l, cfg)
            fresh.extend(items)
            st.update(ok=True, last_success=store.now_iso(), last_error=None, consecutive_failures=0, count=len(items))
        except SourceSkipped as e:
            st.update(ok=None, last_error=f"略過：{e}")
            log(f"[{name}] 略過：{e}")
        except SourceBlocked as e:
            if name == "rent591":
                blocked591 = True
            st.update(ok=False, last_error=f"被擋：{e}", consecutive_failures=st.get("consecutive_failures", 0) + 1)
            log(f"[{name}] 被擋：{e}")
        except Exception as e:  # noqa: BLE001
            st.update(ok=False, last_error=f"{type(e).__name__}: {e}"[:300], consecutive_failures=st.get("consecutive_failures", 0) + 1)
            log(f"[{name}] 失敗：{e}")
            traceback.print_exc()
        st["last_run"] = store.now_iso()

    new_items = store.merge(existing, fresh, int(cfg.get("keep_days", 30)))
    log(f"合併後 {len(existing)} 筆，新增 {len(new_items)} 筆")

    # 補座標與最近捷運站
    cache = store.load_geocache()
    geocoder = Geocoder(cache, budget=int(cfg.get("geocode_per_run", 15)))
    # 先補完全沒座標的，再把只有「區中心／站名」等級的升級到路名（Nominatim 快取會記住查失敗的，不耗額度）
    rank = {None: 0, "district": 1, "station": 2}
    for l in sorted(existing.values(), key=lambda x: (rank.get(x.extra.get("geo_precision"), 9), x.first_seen or ""), reverse=False):
        prec_now = l.extra.get("geo_precision")
        needs = l.lat is None or l.lng is None
        upgradable = prec_now in ("district", "station") and bool(l.address)
        if (needs and (l.address or l.district)) or upgradable:
            if upgradable and geocoder.used >= geocoder.budget:
                break
            res = geocoder.locate(l.address, l.city, l.district, hint_text=l.title + " " + (l.raw_text or "")[:300])
            if res and (needs or res[2] == "street"):
                l.lat, l.lng, prec = res
                l.extra["geo_precision"] = prec
                l.nearest_mrt, l.mrt_dist_m = (None, None) if prec == "street" else (l.nearest_mrt, l.mrt_dist_m)
        precise = l.extra.get("geo_precision") in (None, "street", "exact")
        if l.lat is not None and l.lng is not None and l.nearest_mrt is None and precise:
            l.nearest_mrt, l.mrt_dist_m = nearest_station(l.lat, l.lng)
        elif l.nearest_mrt is None and l.extra.get("geo_precision") == "station":
            st = station_by_name(l.address) or station_by_name(l.title + " " + (l.raw_text or "")[:300])
            if st:
                l.nearest_mrt, l.mrt_dist_m = st["name"], None

    if args.dry_run:
        for l in sorted(fresh, key=lambda x: (x.source, x.price or 0)):
            flag = "🏷️" if l.subsidy else "  "
            log(f"{flag} [{l.source}] {l.district} {l.kind} {l.price} {l.area_ping or '-'}坪 {l.title[:40]} | {l.nearest_mrt}({l.mrt_dist_m}) {l.url}")
        log("dry-run：不存檔不推播")
        return 0

    store.save_listings(existing)
    store.save_geocache(cache)
    store.save_status(status)

    topic = os.environ.get("NTFY_TOPIC")
    site_url = os.environ.get("SITE_URL", "")
    if not args.no_notify:
        if first_run and new_items:
            n_sub = sum(1 for l in new_items if l.subsidy)
            send(topic, "租屋雷達啟動", f"初始化完成，收錄 {len(new_items)} 筆（可租補 {n_sub} 筆）。之後只推新物件。", click=site_url or None, tags=["house"])
        else:
            notify_new(topic, new_items, site_url)
        for name, st in status["sources"].items():
            if st.get("consecutive_failures", 0) == 3:
                send(topic, f"來源 {name} 連續失敗 3 次", str(st.get("last_error"))[:300], click=site_url or None, priority=2, tags=["warning"])

    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as f:
            f.write(f"blocked591={'true' if blocked591 else 'false'}\nnew_count={len(new_items)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

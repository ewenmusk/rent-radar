"""FB 社團通知信：用 IMAP 讀小號信箱裡 facebookmail.com 寄來的新貼文通知。"""
from __future__ import annotations

import email
import imaplib
import os
import re
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup

from ..models import Listing
from ..normalize import clean_text, detect_district, detect_kind, has_excluded, parse_ping, parse_price, subsidy_hits
from . import SourceSkipped

TZ = timezone(timedelta(hours=8))
PERMALINK_RE = re.compile(r"facebook\.com/groups/([^/?#]+)/(?:permalink|posts)/(\d+)")
FOOTER_MARKERS = ["此訊息傳送至", "This message was sent to", "若你不想再收到", "取消訂閱", "Unsubscribe", "Meta Platforms", "Facebook, Inc"]
NOISE_LINES = {"查看貼文", "View post", "查看", "回覆", "Reply", "在 Facebook 上查看", "查看更多", "See more", "通知設定", "Notification settings"}


def _decode(h) -> str:
    try:
        return str(make_header(decode_header(h or "")))
    except Exception:
        return str(h or "")


def _body(msg) -> tuple[str, str]:
    html, text = "", ""
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        ctype = part.get_content_type()
        if ctype not in ("text/html", "text/plain"):
            continue
        payload = part.get_payload(decode=True) or b""
        charset = part.get_content_charset() or "utf-8"
        s = payload.decode(charset, errors="replace")
        if ctype == "text/html" and not html:
            html = s
        elif ctype == "text/plain" and not text:
            text = s
    return html, text


def _real_url(href: str) -> str:
    u = urlparse(href)
    if "l.facebook.com" in u.netloc or u.path.startswith("/l.php"):
        target = parse_qs(u.query).get("u", [""])[0]
        if target:
            return unquote(target)
    return href


def _extract(html: str, text: str) -> tuple[str, str | None, str | None]:
    """回傳 (貼文文字, permalink, 第一張圖)。"""
    permalink, image = None, None
    if html:
        soup = BeautifulSoup(html, "lxml")
        for a in soup.select("a[href]"):
            u = _real_url(a["href"])
            if PERMALINK_RE.search(u):
                permalink = u.split("&")[0] if "permalink" in u or "posts" in u else u
                break
        for img in soup.select("img[src]"):
            src = img["src"]
            if "scontent" in src or "fbcdn" in src:
                if int(img.get("width") or 0) >= 100 or "p" in src:
                    image = src
                    break
        body = soup.get_text("\n")
    else:
        body = text
        m = PERMALINK_RE.search(text or "")
        if m:
            permalink = f"https://www.facebook.com/groups/{m.group(1)}/posts/{m.group(2)}/"
    for marker in FOOTER_MARKERS:
        if marker in body:
            body = body.split(marker)[0]
    lines = [ln.strip() for ln in body.splitlines()]
    lines = [ln for ln in lines if ln and ln not in NOISE_LINES and not ln.startswith("http")]
    return clean_text("\n".join(lines)), permalink, image


def fetch(ctx: dict) -> list[Listing]:
    user, pw = os.environ.get("FB_MAIL_USER"), os.environ.get("FB_MAIL_PASS")
    if not user or not pw:
        raise SourceSkipped("未設定 FB_MAIL_USER / FB_MAIL_PASS")
    cfg = ctx["cfg"]["fb_mail"]
    districts = ctx["cfg"]["districts"]
    price = ctx["cfg"]["price"]
    keywords = ctx["cfg"]["subsidy_keywords"]
    exclude = ctx["cfg"]["exclude_keywords"]
    host = os.environ.get("FB_MAIL_HOST") or cfg.get("host", "imap.gmail.com")
    mark_seen = bool(cfg.get("mark_seen", True)) and not ctx.get("dry_run")
    since = (datetime.now(TZ) - timedelta(hours=int(cfg.get("lookback_hours", 48)))).strftime("%d-%b-%Y")

    M = imaplib.IMAP4_SSL(host)
    M.login(user, pw)
    M.select("INBOX")
    crit = f'(FROM "facebookmail.com" SINCE {since}' + (" UNSEEN)" if mark_seen else ")")
    typ, data = M.search(None, crit)
    ids = data[0].split() if typ == "OK" and data and data[0] else []
    ctx["log"](f"FB 通知信 {len(ids)} 封")
    out: list[Listing] = []
    for num in ids[-150:]:
        typ, raw = M.fetch(num, "(RFC822)")
        if typ != "OK" or not raw or not raw[0]:
            continue
        msg = email.message_from_bytes(raw[0][1])
        subject = _decode(msg.get("Subject"))
        html, text = _body(msg)
        body, permalink, image = _extract(html, text)
        if mark_seen:
            M.store(num, "+FLAGS", "\\Seen")
        m = PERMALINK_RE.search(permalink or "")
        if not m:
            continue
        group, post_id = m.group(1), m.group(2)
        blob = subject + "\n" + body
        district = detect_district(blob, districts)
        if not district or has_excluded(subject, exclude):
            continue
        p = parse_price(body)
        if p and not (price["min"] <= p <= price["max"]):
            continue
        gm = re.search(r"在\s*(.+?)\s*(?:中|裡)?發佈", subject) or re.search(r"posted in\s+(.+)", subject)
        group_name = gm.group(1).strip() if gm else group
        try:
            dt = email.utils.parsedate_to_datetime(msg.get("Date"))
            posted = dt.astimezone(TZ).replace(microsecond=0).isoformat()
        except Exception:
            posted = None
        hits = subsidy_hits(blob, keywords)
        first_line = next((ln for ln in body.splitlines() if len(ln) >= 6), subject)
        out.append(Listing(
            id=f"fb:{post_id}", source="fb", title=first_line[:60], url=permalink or "",
            price=p, kind=detect_kind(body), district=district["name"], city=district["city"],
            address="", area_ping=parse_ping(body), tags=[group_name], subsidy=bool(hits), subsidy_hits=hits,
            image=image, posted_at=posted, raw_text=body, extra={"group": group_name, "subject": subject},
        ))
    try:
        M.logout()
    except Exception:
        pass
    ctx["log"](f"FB 符合 {len(out)} 筆")
    return out

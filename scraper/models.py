from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Listing:
    id: str                      # "<source>:<原始id>"
    source: str                  # rent591 / ptt / fb
    title: str
    url: str
    price: int | None = None
    kind: str = ""               # 整層住家 / 獨立套房 / 分租套房 / 雅房 / 未知
    district: str = ""           # 板橋 / 萬華 / ...
    city: str = ""               # 台北市 / 新北市
    address: str = ""
    area_ping: float | None = None
    floor: str = ""
    layout: str = ""
    tags: list[str] = field(default_factory=list)
    subsidy: bool = False
    subsidy_hits: list[str] = field(default_factory=list)
    image: str | None = None
    lat: float | None = None
    lng: float | None = None
    nearest_mrt: str | None = None
    mrt_dist_m: int | None = None
    posted_at: str | None = None     # ISO 8601
    first_seen: str | None = None
    last_seen: str | None = None
    raw_text: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    sources: list[dict[str, str]] = field(default_factory=list)  # 跨來源合併時的其他連結

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["raw_text"] = (self.raw_text or "")[:1500]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Listing":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

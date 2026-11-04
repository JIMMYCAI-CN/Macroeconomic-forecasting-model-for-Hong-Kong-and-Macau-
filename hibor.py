"""
sources/hibor.py —— 港元同業拆息（HIBOR）
=========================================================
HKMA 的公開 API 在本環境會被 WAF 以 HTTP 405 攔截（回 HTML），
因此本模組採取「快取 → 由 10Y 收益率推算 → 內建基準」的順序：

  * 若能讀到快取（使用者曾在可連線的網路抓過），優先用快取；
  * 否則由 10Y 港元政府債收益率按典型期限結構推算 1M／3M，
    狀態標為「衍生計算」——它是一個透明、可覆寫的估計，不是官方報價；
  * 使用者可隨時在 GUI／CLI 以真實 HIBOR 覆寫，覆寫後狀態為「手動輸入」。

把「抓不到」講清楚，比用一個看起來很精確的假數字更有用。
"""

from __future__ import annotations

from typing import Optional, Tuple

from ..models import Observation
from ..net import read_cache, write_cache

CACHE_KEY = "hibor"
#: 10Y 與 1M 的典型期限差（HKD 曲線在常態下約 2.0–2.6pp）
DEFAULT_TERM_GAP = 0.024
DEFAULT_3M_GAP = 0.0015


def _clamp(x: float, lo: float = 0.005, hi: float = 0.060) -> float:
    return max(lo, min(hi, x))


def fetch_hibor(rf: float, offline: bool = False) -> Tuple[Observation, Observation]:
    cached = read_cache(CACHE_KEY)
    if cached and cached.get("hibor_1m"):
        stamp = str(cached.get("fetched_at", ""))
        one = Observation(
            key="hibor", label="HIBOR 1M", value=float(cached["hibor_1m"]),
            period=str(cached.get("period", "")),
            source=f"港元拆息本地快取（{stamp or '時間未知'}）",
            status="cache", fetched_at=stamp,
        )
        three = Observation(
            key="hibor", label="HIBOR 3M", value=float(cached["hibor_3m"]),
            period=str(cached.get("period", "")),
            source=f"港元拆息本地快取（{stamp or '時間未知'}）",
            status="cache", fetched_at=stamp,
        )
        return one, three

    one_val = _clamp(rf - DEFAULT_TERM_GAP)
    three_val = _clamp(one_val + DEFAULT_3M_GAP)
    note = ("HKMA 公開 API 在此網路環境被攔截；以 10Y 收益率按期限結構推算，"
            "僅供流動性刻度，請以 HKMA 公布 HIBOR 覆寫")
    one = Observation(
        key="hibor", label="HIBOR 1M", value=one_val, period="衍生",
        source="衍生計算（10Y − 期限差）", status="derived", note=note,
    )
    three = Observation(
        key="hibor", label="HIBOR 3M", value=three_val, period="衍生",
        source="衍生計算（1M ＋ 期限差）", status="derived", note=note,
    )
    return one, three


def save_manual(hibor_1m: float, hibor_3m: Optional[float] = None, period: str = "") -> None:
    """把使用者覆寫值寫入快取，下次啟動仍可沿用（狀態會是 cache）。"""
    write_cache(CACHE_KEY, {
        "hibor_1m": hibor_1m,
        "hibor_3m": hibor_3m if hibor_3m is not None else hibor_1m + DEFAULT_3M_GAP,
        "period": period or "手動",
    })

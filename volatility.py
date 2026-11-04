"""
volatility.py —— 港股波動率與價格機率區間
=========================================================
規格要求用「HSI VIX 隱含波動率 σ」衡量恐慌情緒，並用 Black-Scholes
計算價格概率區間、調整安全邊際。實務上有兩個坑：

  1. 恆指波幅指數（VHSI）不是每個免費來源都有，且收盤後才更新；
  2. 直接把 VHSI 當成個股 σ 會低估個股風險。

本模組的做法：
  * 有 VHSI 就用 VHSI（手動覆寫或快取）；
  * 沒有就用恆指日回報計算 20 日已實現波動率，並明確標示「代理值」；
  * 兩種來源都帶出 20 日／60 日已實現波動率，讓使用者看得出隱含與實現的差距。

Black-Scholes 只用來做「一年後 95% 價格區間」與「跌破某水平機率」，
不計算個股目標價——那不是本引擎的職責。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

TRADING_DAYS = 252


def realized_volatility(closes: Sequence[float], window: int = 20) -> Optional[float]:
    """由收盤價計算年化已實現波動率（對數回報標準差 × √252）。"""
    prices = [float(c) for c in closes if c and c > 0]
    if len(prices) < window + 1:
        return None
    recent = prices[-(window + 1):]
    returns = [math.log(recent[i] / recent[i - 1]) for i in range(1, len(recent))]
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / max(len(returns) - 1, 1)
    return math.sqrt(var) * math.sqrt(TRADING_DAYS)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


@dataclass
class VolResult:
    available: bool
    sigma: Optional[float] = None
    source: str = ""
    realized_20d: Optional[float] = None
    realized_60d: Optional[float] = None
    level_label: str = "—"
    band_low: Optional[float] = None
    band_high: Optional[float] = None
    prob_below_20pct: Optional[float] = None
    spot: Optional[float] = None
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "sigma": self.sigma, "sigma_source": self.source,
            "realized_20d": self.realized_20d, "realized_60d": self.realized_60d,
            "price_band_low": self.band_low, "price_band_high": self.band_high,
            "prob_below_20pct": self.prob_below_20pct,
        }


def volatility_profile(
    spot: Optional[float],
    sigma: Optional[float],
    rate: float,
    closes: Optional[Sequence[float]] = None,
    source: str = "",
    horizon_years: float = 1.0,
    z: float = 1.96,
) -> VolResult:
    r20 = realized_volatility(closes or [], 20)
    r60 = realized_volatility(closes or [], 60)
    if sigma is None:
        sigma = r20 or r60
        source = "已實現波動率（20 日年化，VHSI 代理）" if r20 else source
    if sigma is None or spot is None:
        return VolResult(
            available=False, realized_20d=r20, realized_60d=r60,
            spot=spot, note="缺少波動率或指數水平",
        )

    if sigma < 0.15:
        label = "低波動"
    elif sigma < 0.25:
        label = "常態"
    elif sigma < 0.40:
        label = "偏高"
    else:
        label = "恐慌"

    t = horizon_years
    drift = (rate - 0.5 * sigma ** 2) * t
    spread = z * sigma * math.sqrt(t)
    low = spot * math.exp(drift - spread)
    high = spot * math.exp(drift + spread)

    strike = spot * 0.80
    d2 = (math.log(spot / strike) + drift) / (sigma * math.sqrt(t))
    prob_below = _norm_cdf(-d2)      # P(S_T < K)

    note = (f"σ {sigma:.1%}（{source or '手動輸入'}）；"
            f"一年 95% 區間 {low:,.0f}–{high:,.0f}")
    if r20 is not None:
        note += f"；20 日已實現 {r20:.1%}"
    if r60 is not None:
        note += f"、60 日 {r60:.1%}"

    return VolResult(
        available=True,
        sigma=sigma,
        source=source,
        realized_20d=r20,
        realized_60d=r60,
        level_label=label,
        band_low=low,
        band_high=high,
        prob_below_20pct=prob_below,
        spot=spot,
        note=note,
    )

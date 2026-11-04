"""
liquidity.py —— 港元銀行體系流動性與流動性溢價
=========================================================
可觀測的代理變量：
  * HIBOR 1M 水平：資金成本本身；偏離常態區間代表體系鬆緊
  * 3M − 1M 拆息差：曲線倒掛（負值）通常是資金緊絀的早期信號

壓力分數 stress ∈ [0, 1]：
    level_stress  = clamp((hibor1m − low) / (high − low))
    curve_stress  = clamp((hibor3m − hibor1m) / 0.005) 反向，倒掛時上升
    stress = 0.8 × level + 0.2 × curve

流動性溢價 = stress × max_premium（預設 0.4pp），
同時把 stress 交給 ERP 因子與風險分數使用，避免重複計算出兩個不一致的數字。

HIBOR 在本環境沒有穩定的免費即時 API（HKMA API 被 WAF 攔截），
因此以「快取 → 內建基準 → 手動覆寫」降級，並逐項標示資料狀態。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

DEFAULT_LOW = 0.010
DEFAULT_HIGH = 0.050
DEFAULT_MAX_PREMIUM = 0.0040
DEFAULT_CURVE_SCALE = 0.0050


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


@dataclass
class LiquidityResult:
    available: bool
    hibor_1m: Optional[float] = None
    hibor_3m: Optional[float] = None
    term_spread: Optional[float] = None
    stress: float = 0.0
    premium: float = 0.0
    label: str = "—"
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "hibor_1m": self.hibor_1m, "hibor_3m": self.hibor_3m,
            "term_spread": self.term_spread, "stress": self.stress,
            "liquidity_premium": self.premium, "label": self.label,
        }


def liquidity_assessment(
    hibor_1m: Optional[float],
    hibor_3m: Optional[float] = None,
    low: float = DEFAULT_LOW,
    high: float = DEFAULT_HIGH,
    max_premium: float = DEFAULT_MAX_PREMIUM,
    curve_scale: float = DEFAULT_CURVE_SCALE,
) -> LiquidityResult:
    if hibor_1m is None:
        return LiquidityResult(available=False, note="缺少 HIBOR 1M")

    level = _clamp((hibor_1m - low) / max(high - low, 1e-9))
    term = None if hibor_3m is None else hibor_3m - hibor_1m
    curve = 0.0 if term is None else _clamp(-term / max(curve_scale, 1e-9))
    stress = _clamp(0.8 * level + 0.2 * curve)

    if stress < 0.25:
        label = "寬鬆"
    elif stress < 0.50:
        label = "中性"
    elif stress < 0.75:
        label = "偏緊"
    else:
        label = "收緊"

    note = f"HIBOR 1M {hibor_1m:.2%}，區間假設 {low:.1%}–{high:.1%}"
    if term is not None:
        note += f"；3M−1M {term * 100:+.2f}pp"
    note += f"；壓力 {stress:.0%}"

    return LiquidityResult(
        available=True,
        hibor_1m=hibor_1m,
        hibor_3m=hibor_3m,
        term_spread=term,
        stress=stress,
        premium=stress * max_premium,
        label=label,
        note=note,
    )

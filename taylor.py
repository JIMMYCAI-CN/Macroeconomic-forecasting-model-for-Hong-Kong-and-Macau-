"""
taylor.py —— 泰勒規則與政策預期
=========================================================
規格要求「輸出的不只是當下即期利率，而是理論均衡政策利率」。
對香港而言這一點特別重要：聯繫匯率下香港利率跟隨美聯儲，
本地 10 年期收益率已經隱含市場對未來政策的定價；
把泰勒規則算出的理論利率與市場利率相比，差距就是「政策預期標籤」的來源。

    i* = r* + π + 0.5(π − π*) + 0.5 · gap

  * r*：均衡實質利率（HK/MO 皆以 1.5% 為預設，可配置）
  * π：當前綜合 CPI 同比
  * π*：通脹目標（2%）
  * gap：GDP 缺口（以小數表示，-0.012 → -1.2%）

標籤邏輯：
    理論利率 − 市場利率 > +25bp  → 加息（市場定價偏鬆）
    < −25bp                      → 減息（市場定價偏緊）
    其餘                          → 維持

注意：10 年期收益率不是政策利率本身，含有期限溢價。因此本模組同時輸出
「期限溢價調整後」的比較值（預設扣 50bp），並在說明中標明這是啟發式比較，
不是對金管局／美聯儲決策的預測。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

#: 10 年期相對政策利率的典型期限溢價（可調）
DEFAULT_TERM_PREMIUM = 0.0050
#: 判定「加息／減息」的最小差距
DEFAULT_TOLERANCE = 0.0025

SIGNAL_LABEL = {"hike": "加息", "hold": "維持", "cut": "減息"}


@dataclass
class TaylorResult:
    available: bool
    theoretical_rate: Optional[float] = None
    market_rate: Optional[float] = None
    market_rate_adjusted: Optional[float] = None
    gap: Optional[float] = None              # 理論 − 市場（調整後）
    signal: str = "hold"
    signal_label: str = "維持"
    r_star: float = 0.015
    cpi: float = 0.0
    cpi_target: float = 0.02
    output_gap: float = 0.0
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "theoretical_rate": self.theoretical_rate,
            "market_rate": self.market_rate,
            "market_rate_adjusted": self.market_rate_adjusted,
            "gap": self.gap,
            "signal": self.signal,
            "signal_label": self.signal_label,
            "r_star": self.r_star,
            "cpi": self.cpi,
            "cpi_target": self.cpi_target,
            "output_gap": self.output_gap,
        }


def taylor_rule(
    rf: float,
    cpi: float,
    output_gap: float = 0.0,
    r_star: float = 0.015,
    cpi_target: float = 0.02,
    term_premium: float = DEFAULT_TERM_PREMIUM,
    tolerance: float = DEFAULT_TOLERANCE,
) -> TaylorResult:
    """計算理論均衡政策利率，並與市場無風險利率比較。"""
    if rf is None or cpi is None:
        return TaylorResult(available=False, note="缺少 rf 或 CPI")

    theoretical = r_star + cpi + 0.5 * (cpi - cpi_target) + 0.5 * output_gap
    adjusted = rf - term_premium
    gap = theoretical - adjusted
    if gap > tolerance:
        signal = "hike"
    elif gap < -tolerance:
        signal = "cut"
    else:
        signal = "hold"

    note = (
        f"i* = r*({r_star:.2%}) + π({cpi:.2%}) + 0.5(π−π*) + 0.5·gap"
        f"({output_gap * 100:+.2f}%) = {theoretical:.2%}；"
        f"市場 10Y {rf:.2%} 扣期限溢價 {term_premium * 100:.1f}pp 後為 {adjusted:.2%}"
    )
    return TaylorResult(
        available=True,
        theoretical_rate=theoretical,
        market_rate=rf,
        market_rate_adjusted=adjusted,
        gap=gap,
        signal=signal,
        signal_label=SIGNAL_LABEL[signal],
        r_star=r_star,
        cpi=cpi,
        cpi_target=cpi_target,
        output_gap=output_gap,
        note=note,
    )

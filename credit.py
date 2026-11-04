"""
credit.py —— 信貸利差與債務成本
=========================================================
rd = 無風險利率 + 對應評級（＋行業）信用利差

本引擎不預測個別債券的成交價，也不做違約模型；它提供的是
「同一套評級／行業假設下，債務成本應該是多少」的可配置基準，
讓下游 WACC 不會出現「股權成本很講究、債務成本隨手填」的落差。

利差矩陣放在 EngineConfig.credit，可由 JSON 或 GUI 修改。
預設值參照亞洲美元債／港元債的常見區間，屬方法論假設。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

DEFAULT_RATING_SPREADS = {
    "AAA": 0.0055, "AA": 0.0085, "A": 0.0120,
    "BBB": 0.0185, "BB": 0.0310, "B": 0.0460,
}


@dataclass
class CreditResult:
    available: bool
    rating: str = "BBB"
    sector: str = "公用事業"
    spread: float = 0.0
    rf: float = 0.0
    cost_of_debt: float = 0.0
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "rating": self.rating, "sector": self.sector,
            "spread": self.spread, "rf": self.rf,
            "cost_of_debt": self.cost_of_debt,
        }


def cost_of_debt(
    rf: float,
    rating: str = "BBB",
    sector: str = "公用事業",
    rating_spreads: Dict[str, float] | None = None,
    sector_spreads: Dict[str, float] | None = None,
) -> CreditResult:
    spreads = rating_spreads or DEFAULT_RATING_SPREADS
    sectors = sector_spreads or {}
    rating = (rating or "BBB").upper()
    base = spreads.get(rating, spreads.get("BBB", 0.0185))
    extra = sectors.get(sector, 0.0)
    spread = base + extra
    return CreditResult(
        available=True,
        rating=rating,
        sector=sector,
        spread=spread,
        rf=rf,
        cost_of_debt=rf + spread,
        note=(f"{rating} 級 {base * 100:.2f}pp ＋ {sector}行業 {extra * 100:.2f}pp"
              f" ＝ {spread * 100:.2f}pp；rd = rf + 利差"),
    )

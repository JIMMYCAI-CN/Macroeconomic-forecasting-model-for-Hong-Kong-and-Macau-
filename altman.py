"""
altman.py —— Altman Z-Score 與企業專屬風險溢價
=========================================================
Z = 1.2·(WC/TA) + 1.4·(RE/TA) + 3.3·(EBIT/TA) + 0.6·(MVE/TL) + 1.0·(Sales/TA)

原始模型針對上市製造業；對港股（地產、金融、博彩）只能作粗略破產風險刻度，
因此本模組：
  * 只在使用者提供完整財務數字時才計算（不猜、不補值）；
  * 輸出的是「企業專屬風險溢價」區間，而不是違約機率；
  * 溢價直接加在 re 上，並在歸因表中單獨列出，避免與宏觀溢價混淆。

分區（原始門檻）：
    Z > 2.99      安全區      → 溢價 0
    1.81–2.99     灰色區      → 溢價 +0.8pp
    Z < 1.81      困境區      → 溢價 +2.0pp
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

ZONE_LABEL = {"safe": "安全區", "grey": "灰色區", "distress": "困境區"}
DEFAULT_PREMIUM = {"safe": 0.0, "grey": 0.008, "distress": 0.020}


@dataclass
class AltmanResult:
    available: bool
    z: Optional[float] = None
    zone: str = ""
    label: str = "—"
    premium: float = 0.0
    components: Dict[str, float] = None  # type: ignore[assignment]
    note: str = ""

    def __post_init__(self) -> None:
        if self.components is None:
            self.components = {}

    def as_dict(self) -> dict:
        return {
            "z_score": self.z, "zone": self.zone,
            "premium": self.premium, "components": self.components,
        }


def altman_z(
    total_assets: Optional[float],
    working_capital: Optional[float],
    retained_earnings: Optional[float],
    ebit: Optional[float],
    sales: Optional[float],
    market_value_equity: Optional[float],
    total_liabilities: Optional[float],
    premiums: Optional[Dict[str, float]] = None,
) -> AltmanResult:
    values = [total_assets, working_capital, retained_earnings, ebit, sales,
              market_value_equity, total_liabilities]
    if any(v is None for v in values) or not total_assets or total_assets <= 0:
        return AltmanResult(available=False, note="未提供完整企業財務數字")
    if not total_liabilities or total_liabilities <= 0:
        return AltmanResult(available=False, note="總負債必須為正數")

    ta = float(total_assets)
    parts = {
        "WC/TA": 1.2 * float(working_capital) / ta,
        "RE/TA": 1.4 * float(retained_earnings) / ta,
        "EBIT/TA": 3.3 * float(ebit) / ta,
        "MVE/TL": 0.6 * float(market_value_equity) / float(total_liabilities),
        "Sales/TA": 1.0 * float(sales) / ta,
    }
    z = sum(parts.values())
    if z > 2.99:
        zone = "safe"
    elif z >= 1.81:
        zone = "grey"
    else:
        zone = "distress"
    table = premiums or DEFAULT_PREMIUM

    return AltmanResult(
        available=True,
        z=z,
        zone=zone,
        label=ZONE_LABEL[zone],
        premium=table.get(zone, 0.0),
        components={k: round(v, 4) for k, v in parts.items()},
        note=(f"Z = {z:.2f}（{ZONE_LABEL[zone]}）；"
              f"企業專屬溢價 {table.get(zone, 0.0) * 100:+.1f}pp"),
    )

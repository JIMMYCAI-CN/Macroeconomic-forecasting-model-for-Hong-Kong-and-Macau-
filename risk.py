"""
risk.py —— 宏觀綜合風險分數（0–100）
=========================================================
把五個壓力來源壓成一個分數，是為了讓「現在到底多危險」有一個
可比較、可回溯的刻度；但單一分數一定會丟失資訊，所以同時輸出
每個分項的分數與貢獻，GUI 與 Excel 都會列出明細。

分項（0 = 無壓力，100 = 極端壓力）：
    rate          利率壓力：rf 相對 1.5%–5.5% 常態區間
    inflation     通脹壓力：CPI 偏離 2% 目標的幅度（3pp 偏離 = 100）
    unemployment  失業壓力：失業率高出自然失業率 2pp = 100
    growth        增長壓力：負 GDP 缺口 3pp = 100（無缺口時用增速低於趨勢）
    liquidity     流動性壓力：來自 liquidity.stress × 100

權重合計自動歸一化；預設沿用 ERP 的四因子權重，另外給利率 15%，
確保「同一個政策觀點」不會在 ERP 與風險分數裡給出互相矛盾的方向。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


@dataclass
class RiskComponent:
    key: str
    label: str
    score: float
    weight: float
    contribution: float
    detail: str

    def as_dict(self) -> dict:
        return {
            "key": self.key, "label": self.label, "score": self.score,
            "weight": self.weight, "contribution": self.contribution,
            "detail": self.detail,
        }


@dataclass
class RiskResult:
    score: float
    band_key: str
    label: str
    components: List[RiskComponent] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "score": self.score,
            "band": self.band_key,
            "label": self.label,
            "components": [c.as_dict() for c in self.components],
        }


def risk_band(score: float) -> tuple[str, str]:
    if score < 30:
        return "low", "低風險"
    if score < 50:
        return "neutral", "中性"
    if score < 70:
        return "elevated", "偏高"
    return "high", "高風險"


def macro_risk_score(
    rf: float,
    cpi: float,
    unemp: float,
    natural_unemp: float,
    trend_gdp: float,
    gdp_yoy: float,
    infl_target: float = 0.02,
    gdp_gap: Optional[float] = None,
    liquidity_stress: float = 0.0,
    weights: Optional[Dict[str, float]] = None,
) -> RiskResult:
    rate = _clamp((rf - 0.015) / (0.055 - 0.015) * 100.0)
    inflation = _clamp(abs(cpi - infl_target) / 0.03 * 100.0)
    unemployment = _clamp((unemp - natural_unemp) / 0.02 * 100.0)
    if gdp_gap is not None:
        growth = _clamp(-gdp_gap / 0.03 * 100.0)
        growth_detail = f"GDP 缺口 {gdp_gap * 100:+.2f}%"
    else:
        growth = _clamp((trend_gdp - gdp_yoy) / 0.04 * 100.0)
        growth_detail = f"GDP 同比 {gdp_yoy:.2%} vs 趨勢 {trend_gdp:.2%}（缺口不可用）"
    liq = _clamp(liquidity_stress * 100.0)

    raw = {
        "rate": (rate, 0.18, f"rf {rf:.2%}"),
        "inflation": (inflation, 0.20, f"CPI {cpi:.2%} vs 目標 {infl_target:.1%}"),
        "unemployment": (unemployment, 0.20, f"失業率 {unemp:.2%} vs 自然 {natural_unemp:.2%}"),
        "growth": (growth, 0.27, growth_detail),
        "liquidity": (liq, 0.15, f"流動性壓力 {liquidity_stress:.0%}"),
    }
    # 若使用者調整了 ERP 權重，這裡按同一比例映射，避免兩套世界觀
    if weights:
        mapped = {
            "growth": weights.get("gdp_gap", 0.27),
            "unemployment": weights.get("unemployment", 0.20),
            "inflation": weights.get("inflation", 0.20),
            "liquidity": weights.get("liquidity", 0.15),
            "rate": 0.15,
        }
        total = sum(mapped.values()) or 1.0
        raw = {k: (raw[k][0], mapped[k] / total, raw[k][2]) for k in raw}

    labels = {
        "rate": "利率壓力", "inflation": "通脹壓力",
        "unemployment": "失業壓力", "growth": "增長壓力",
        "liquidity": "流動性壓力",
    }
    comps: List[RiskComponent] = []
    score = 0.0
    for key, (value, weight, detail) in raw.items():
        contribution = value * weight
        score += contribution
        comps.append(RiskComponent(key, labels[key], value, weight,
                                   contribution, detail))

    band_key, label = risk_band(score)
    return RiskResult(score=score, band_key=band_key, label=label, components=comps)

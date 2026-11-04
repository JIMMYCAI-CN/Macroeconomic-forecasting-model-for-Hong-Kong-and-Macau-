"""
dcf.py —— DCF 專用參數（服務股票估值下游）
=========================================================
本模組只輸出「參數」，不計算 FCF、不計算目標價。三個核心輸出：

1. 長期名義 GDP 增速上限（g_cap）
       g_cap = 長期實質趨勢增速 + 通脹目標
   使用者給的永續增長率 g 會被強制壓在 g_cap 之下，避免「g > 經濟增速」
   造成終值爆炸——這是 DCF 最常見、也最難被察覺的錯誤。

2. 通脹傳導係數（二分類）
       本地業務：服務／零售可部分轉嫁成本，預設 0.65
       內地收入：定價權受內地 CPI、PMI 影響，預設 0.35
   若內地 PMI 低於 50（收縮），再扣一個傳導折扣；這不是預測毛利率，
   而是提醒下游「通脹上行時，哪些企業的毛利會被壓縮」。

3. 安全邊際門檻（股票／項目兩套）
   宏觀風險分數與波動率越高，要求的折價越大。兩套門檻刻意分開：
   股票買賣的估值折扣不應直接套用到資本項目審批。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..config import DcfConfig, RegionProfile


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


@dataclass
class DcfParams:
    available: bool = True
    g_cap: float = 0.0
    g_trend: float = 0.0
    infl_target: float = 0.0
    g_user: Optional[float] = None
    g_effective: Optional[float] = None
    g_capped: bool = False
    g_headroom: Optional[float] = None
    pass_through: float = 0.0
    pass_through_base: float = 0.0
    pass_through_adjust: float = 0.0
    cn_pmi: Optional[float] = None
    cn_cpi: Optional[float] = None
    margin_equity: float = 0.0
    margin_project: float = 0.0
    risk_score: float = 0.0
    sigma: Optional[float] = None
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "g_cap": self.g_cap, "g_trend": self.g_trend,
            "infl_target": self.infl_target, "g_user": self.g_user,
            "g_effective": self.g_effective, "g_capped": self.g_capped,
            "inflation_pass_through": self.pass_through,
            "safety_margin_equity": self.margin_equity,
            "safety_margin_project": self.margin_project,
        }


def build_dcf_params(
    profile: RegionProfile,
    risk_score: float,
    sigma: Optional[float],
    g_user: Optional[float],
    cfg: DcfConfig,
    cn_cpi: Optional[float] = None,
    cn_pmi: Optional[float] = None,
) -> DcfParams:
    g_trend = profile.trend_gdp
    g_cap = g_trend + profile.infl_target

    g_eff = None
    capped = False
    headroom = None
    if g_user is not None:
        g_eff = min(g_user, g_cap)
        capped = g_user > g_cap + 1e-12
        headroom = g_cap - g_user

    # ---- 通脹傳導 ----
    base = profile.pass_through
    adjust = 0.0
    if profile.is_mainland_exposed:
        if cn_pmi is not None and cn_pmi < cfg.pmi_weak_threshold:
            adjust -= cfg.pmi_weak_haircut
        if cn_cpi is not None:
            if cn_cpi < 0.010:
                adjust -= 0.05
            elif cn_cpi > 0.025:
                adjust += 0.05
    pass_through = _clip(base + adjust, 0.0, 1.0)

    # ---- 安全邊際 ----
    vol_extra = max(0.0, (sigma or 0.20) - 0.20)
    margin_eq = (cfg.equity_margin_base + cfg.equity_margin_per_risk * risk_score
                 + cfg.equity_margin_vol * vol_extra)
    margin_eq = _clip(margin_eq, cfg.equity_margin_low, cfg.equity_margin_high)
    margin_pr = _clip(cfg.project_margin_base + cfg.project_margin_per_risk * risk_score,
                      cfg.project_margin_low, cfg.project_margin_high)

    note = (f"g_cap = 趨勢 {g_trend:.2%} + 通脹目標 {profile.infl_target:.2%}"
            f" = {g_cap:.2%}")
    if g_user is not None and capped:
        note += f"；輸入 g {g_user:.2%} 已被壓回上限"
    if adjust:
        note += f"；內地因子調整傳導係數 {adjust:+.2f}"

    return DcfParams(
        available=True,
        g_cap=g_cap,
        g_trend=g_trend,
        infl_target=profile.infl_target,
        g_user=g_user,
        g_effective=g_eff,
        g_capped=capped,
        g_headroom=headroom,
        pass_through=pass_through,
        pass_through_base=base,
        pass_through_adjust=adjust,
        cn_pmi=cn_pmi,
        cn_cpi=cn_cpi,
        margin_equity=margin_eq,
        margin_project=margin_pr,
        risk_score=risk_score,
        sigma=sigma,
        note=note,
    )

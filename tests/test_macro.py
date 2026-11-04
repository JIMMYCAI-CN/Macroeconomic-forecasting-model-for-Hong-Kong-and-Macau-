"""
test_macro.py —— 港澳宏觀折現率引擎的回歸測試
=========================================================
設計原則：
  * 全部純函數／離線解析，不發網路請求（CI 或無網環境都能跑）；
  * 每個週期分類至少一個案例，含「優先次序」與「臨界情境」；
  * 解析器用人工构造的官方格式樣本，確保欄位改動時立刻發現。

執行：
    python tests/test_macro.py
"""

from __future__ import annotations

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from macro_engine import capm, cycle  # noqa: E402
from macro_engine.cli import parse_rate  # noqa: E402
from macro_engine.report import to_dict  # noqa: E402
from macro_engine.sources import censtatd, dsec, hkma  # noqa: E402

PASSED = 0


def check(cond: bool, message: str) -> None:
    global PASSED
    if not cond:
        raise AssertionError(message)
    PASSED += 1


def approx(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol


# ---------------------------------------------------------------- 週期判定
def test_cycles_hk() -> None:
    cases = {
        "overheat": (0.045, 0.032, 0.035),
        "stable": (0.030, 0.038, 0.020),
        "recession": (0.000, 0.048, 0.010),
        "stagflation": (0.002, 0.046, 0.032),
        "neutral": (0.043, 0.041, 0.019),
    }
    for expected, (gdp, unemp, cpi) in cases.items():
        result = cycle.classify("HK", gdp, unemp, cpi)
        check(result.key == expected, f"HK {gdp}/{unemp}/{cpi} 應為 {expected}，實得 {result.key}")


def test_cycles_mo() -> None:
    cases = {
        "overheat": (0.100, 0.020, 0.035),
        "stable": (0.040, 0.020, 0.020),
        "recession": (-0.030, 0.032, 0.010),
        "neutral": (0.001, 0.018, 0.0133),
    }
    for expected, (gdp, unemp, cpi) in cases.items():
        result = cycle.classify("MO", gdp, unemp, cpi)
        check(result.key == expected, f"MO {gdp}/{unemp}/{cpi} 應為 {expected}，實得 {result.key}")


def test_priority_stagflation_over_recession() -> None:
    """CPI 3.2%、GDP 0.2%、失業 4.6% 同時符合滯脹與衰退 → 應判滯脹（優先級較高）。"""
    result = cycle.classify("HK", 0.002, 0.046, 0.032)
    check(result.key == "stagflation", "滯脹應優先於衰退")
    check(result.erp_adjust == 0.028, "滯脹 ERP 上浮應為 2.8pp")


def test_erp_map() -> None:
    check(cycle.CYCLE_META["overheat"][1] == 0.022, "過熱 2.2pp")
    check(cycle.CYCLE_META["stagflation"][1] == 0.028, "滯脹 2.8pp")
    check(cycle.CYCLE_META["recession"][1] == 0.028, "衰退 2.8pp")
    check(cycle.CYCLE_META["stable"][1] == 0.0, "繁榮穩定無調整")
    check(cycle.CYCLE_META["neutral"][1] == 0.010, "中性 1.0pp")


def test_thresholds_differ_by_region() -> None:
    """港澳門檻必須不同，否則等於套用同一套標準。"""
    hk, mo = cycle.THRESHOLDS["HK"], cycle.THRESHOLDS["MO"]
    check(hk["overheat_gdp"] != mo["overheat_gdp"], "兩地過熱 GDP 門檻不應相同")
    check(mo["stable_unemp"] < hk["stable_unemp"], "澳門失業率門檻應低於香港")
    check(mo["recession_gdp"] < hk["recession_gdp"], "澳門衰退門檻應更寬（GDP 波動大）")


def test_boundary_alternative() -> None:
    """香港失業率 4.10% 距 4.00% 只差 0.1pp → 應提示可能改判繁榮穩定。"""
    result = cycle.classify("HK", 0.043, 0.041, 0.019)
    check(result.alternative is not None, "應偵測到臨界情境")
    check(result.alternative.label == "繁榮穩定", "臨界分類應為繁榮穩定")
    check(result.alternative.erp_adjust == 0.0, "繁榮穩定 ERP 上浮為 0")
    check(result.near_boundary, "boundary_flags 應非空")


def test_no_false_alternative() -> None:
    """澳門 CPI 1.33% 遠低於滯脹的 3%，不應因為 GDP 貼近 0 就提示滯脹。"""
    result = cycle.classify("MO", 0.001, 0.018, 0.0133)
    check(result.alternative is None, "不應出現誤導性的滯脹提示")


def test_trace_covers_all_rules() -> None:
    result = cycle.classify("HK", 0.043, 0.041, 0.019)
    check(len(result.trace) == 5, "判定軌跡應含四個規則 + 預設分類")
    check(result.trace[-1].passed and result.trace[-1].label == "復甦／中性", "最後一步應為預設分類")


# ---------------------------------------------------------------- CAPM
def test_capm() -> None:
    d = capm.cost_of_equity(rf=0.04, beta=1.2, erp_adjust=0.01, cpi=0.02)
    check(approx(d.adjusted_erp, 0.065), "調整後 ERP 應為 6.5%")
    check(approx(d.cost_equity_nominal, 0.04 + 1.2 * 0.065), "名義成本公式錯誤")
    check(approx(d.cost_equity_real, (1.118 / 1.02) - 1), "費雪精確式錯誤")
    check(approx(d.cost_equity_real_approx, 0.098), "近似式應為 re − π")
    check(d.cost_equity_real < d.cost_equity_real_approx, "正通脹下精確式應低於近似式")


def test_capm_negative_inflation() -> None:
    """負通脹（澳門曾出現）下，實質利率應高於名義利率。"""
    d = capm.cost_of_equity(rf=0.04, beta=1.0, erp_adjust=0.0, cpi=-0.01)
    check(d.cost_equity_real > d.cost_equity_nominal, "負通脹下實質 > 名義")


def test_beta_validation() -> None:
    try:
        capm.cost_of_equity(rf=0.04, beta=0.0, erp_adjust=0.0, cpi=0.02)
    except ValueError:
        check(True, "")
    else:
        raise AssertionError("β = 0 應被拒絕")


# ---------------------------------------------------------------- 解析器
def test_parse_rate() -> None:
    check(approx(parse_rate("4.022"), 0.04022), "4.022 應解讀為 4.022%")
    check(approx(parse_rate("4.022%"), 0.04022), "4.022% 應解讀為 4.022%")
    check(approx(parse_rate("0.04022"), 0.04022), "0.04022 應保持小數")
    check(approx(parse_rate("-2.5%"), -0.025), "負數應正確處理")


def test_hkma_parse_api() -> None:
    payload = {
        "header": {"success": True},
        "result": {
            "records": [
                {"end_of_date": "2026-09-29", "closing_ref_rate_10y": 4.010},
                {"end_of_date": "2026-09-30", "closing_ref_rate_10y": 4.022},
                {"end_of_date": "2026-09-28", "closing_ref_rate_10y": "-"},
            ]
        },
    }
    value, when = hkma.parse_api(payload)
    check(approx(value, 0.04022), f"10Y 收益率解析錯誤：{value}")
    check(when == "2026-09-30", "應取最新日期")


def test_hkma_parse_xls() -> None:
    epoch = date(1899, 12, 30)
    serial = (date(2026, 9, 30) - epoch).days

    header = [""] * 16
    header[3:9] = ["3-year", "5-year", "7-year", "10-year", "15-year", "20-year"]
    header[10:16] = ["3-year", "5-year", "7-year", "10-year", "15-year", "20-year"]
    group = [""] * 16
    group[10] = "Closing Reference Pricings"

    rows = [[""] * 16 for _ in range(5)]
    rows.append(group)
    rows.append(header)
    data = [""] * 16
    data[2] = serial
    data[6] = 3.987       # 指示價格 10Y
    data[13] = 4.022      # 收市參考 10Y
    rows.append(data)

    value, when = hkma.parse_xls_table(rows)
    check(approx(value, 0.04022), f"XLS 應取收市參考價 4.022%，實得 {value}")
    check(when == "2026-09-30", f"XLS 日期解析錯誤：{when}")


def test_dsec_parse() -> None:
    page = """
    <div class="weui_cells_title">【更新：2026-11-03】</div>
    <div class="weui_cell">
      <div class="weui_cell_bd weui_cell_primary" style="width:65%">綜合消費物價指數按年變動<br/>(2026年9月)(%)</div>
      <div class="weui_cell_ft" style="width:35%">1.33</div>
    </div>
    <div class="weui_cell">
      <div class="weui_cell_bd weui_cell_primary" style="width:65%">總體失業率<br/>(2026年7月至9月)(%)</div>
      <div class="weui_cell_ft" style="width:35%">1.8</div>
    </div>
    """
    parsed = dsec.parse_key_indicator(page)
    check(approx(parsed["cpi"]["value"], 1.33), "CPI 解析錯誤")
    check(parsed["cpi"]["period"] == "2026-09", "CPI 期間解析錯誤")
    check(approx(parsed["unemp"]["value"], 1.8), "失業率解析錯誤")
    check(parsed["unemp"]["period"] == "2026-07~09", "三個月期間解析錯誤")
    check(parsed["_updated"]["period"] == "2026-11-03", "更新日期解析錯誤")


def test_dsec_period_cross_year() -> None:
    check(dsec._period("(2026年1月)(%)") == "2026-01", "單月期間")
    check(dsec._period("(2025年12月至2026年2月)(%)") == "2025-12~2026-02", "跨年期間應保留年份")


def test_censtatd_period_format() -> None:
    check(censtatd._fmt_quarter("202606") == "2026Q2", "季度格式")
    check(censtatd._fmt_month("202609") == "2026-09", "月份格式")
    check(censtatd._fmt_3m("202601") == "2025-11~01", "跨年三個月格式")


# ---------------------------------------------------------------- 輸出（1.x 相容層）
def test_to_dict_schema() -> None:
    from macro_engine.config import EngineConfig
    from macro_engine.engine import RegionResult
    from macro_engine.models import MacroInputs, Observation

    def obs(key, label, value, period):
        return Observation(key, label, value, period, "test")

    cfg = EngineConfig()
    inputs = MacroInputs(
        "HK", obs("rf", "rf", 0.04, "2026-09"), obs("gdp", "gdp", 0.03, "2026Q2"),
        obs("unemp", "unemp", 0.03, "2026-09"), obs("cpi", "cpi", 0.02, "2026-09"), 1.1,
    )
    cyc = cycle.classify("HK", 0.03, 0.03, 0.02)
    res = RegionResult(inputs, cyc, capm.evaluate(inputs, cyc),
                       cfg.profile("hk_local"))
    payload = to_dict([res], 1.1, 0.055)
    item = payload["results"][0]
    for key in ("region", "macro_cycle", "base_erp", "erp_adjustment",
                "adjusted_erp", "cost_equity_nominal", "cost_equity_real"):
        check(key in item, f"JSON 缺少欄位 {key}")
    check(len(item["inputs"]) == 4, "應包含四項輸入")
    check("不是投資建議" in payload["disclaimer"], "免責聲明缺失")


# ================================================================ 2.0 新模組
import json  # noqa: E402
import math  # noqa: E402
import tempfile  # noqa: E402

from macro_engine import analytics  # noqa: E402
from importlib import import_module  # noqa: E402
iem = import_module("macro_engine.analytics.implied_erp")  # 套件屬性被同名函式遮蔽
from macro_engine.analytics import (  # noqa: E402
    altman as am, credit as cr, dcf as dcfm, hp as hpm,
    liquidity as lq, npv as npvm, ppp as pppm, risk as rkm, taylor as tr,
    volatility as vol, wacc as waccm,
)
from macro_engine.config import EngineConfig  # noqa: E402
from macro_engine.engine import compute, erp_decomposition  # noqa: E402
from macro_engine.history import SnapshotStore  # noqa: E402
from macro_engine.models import (  # noqa: E402
    ChinaInputs, FirmInputs, MarketInputs, Observation, STAGE_LABEL,
)


def _obs(key, label, value, period, status="manual", stage="final"):
    return Observation(key, label, value, period, "測試", status=status, stage=stage)


def _quarters(start_year, start_q, n):
    out = []
    y, q = start_year, start_q
    for _ in range(n):
        out.append(f"{y}Q{q}")
        q += 1
        if q > 4:
            q = 1
            y += 1
    return out


def _months(start, n):
    """start = (year, month)；回傳 'YYYY-MM' 清單。"""
    y, m = start
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


# ---------------------------------------------------------------- 設定檔
def test_config_roundtrip_and_hash() -> None:
    cfg = EngineConfig()
    data = cfg.to_dict()
    cfg2 = EngineConfig.from_dict(json.loads(json.dumps(data)))
    check(cfg2.to_dict() == data, "設定往返序列化應完全一致")
    check(cfg.hash() == cfg2.hash(), "內容相同時雜湊應相同")
    cfg3 = cfg.copy()
    cfg3.erp.base = 0.056
    check(cfg3.hash() != cfg.hash(), "改動參數後雜湊必須改變（回測可比對）")


def test_config_validate() -> None:
    check(EngineConfig().validate() == [], "預設設定應通過驗證")
    bad = EngineConfig().copy()
    bad.erp.lower = 0.09                      # 下限高於基準
    issues = bad.validate()
    check(any("ERP" in i for i in issues), f"應偵測到 ERP 區間錯誤：{issues}")
    bad2 = EngineConfig().copy()
    bad2.erp.weights["gdp_gap"] = -0.5
    check(any("權重" in i for i in bad2.validate()), "應偵測到負權重")


def test_config_profiles_isolated() -> None:
    cfg = EngineConfig()
    check([p.key for p in cfg.profiles_for("HK")] == ["hk_local", "hk_mainland"],
          "HK 應有本地／內地兩個情境")
    check([p.key for p in cfg.profiles_for("MO")] == ["mo_local"], "MO 只有一個情境")
    try:
        cfg.profile("nope")
    except ValueError:
        check(True, "")
    else:
        raise AssertionError("未知情境應拒絕")


# ---------------------------------------------------------------- HP 濾波
def test_hp_filter_tracks_smooth_trend() -> None:
    vals = [100.0 * 1.0025 ** i for i in range(48)]
    trend = hpm.hp_filter(vals)
    check(len(trend) == 48, "趨勢長度應與輸入一致")
    worst = max(abs(trend[i] / vals[i] - 1.0) for i in range(48))
    check(worst < 0.005, f"平滑序列的 HP 趨勢應貼合原序列（最大偏差 {worst:.4%}）")


def test_seasonal_adjust_removes_pattern() -> None:
    raw = []
    for _ in range(12):                        # 12 年 × 4 季，無趨勢
        raw.extend([97.0, 100.0, 104.0, 99.0])
    factors = hpm.seasonal_factors(raw)
    check(len(factors) == 4, "應回傳 4 個季節因子")
    check(abs(sum(factors) - 4.0) < 1e-6, "季節因子平均應約為 1")
    adj = hpm.seasonal_adjust(raw, factors)
    check(max(adj) - min(adj) < 1.5,
          f"季節調整後應近乎水平（極差 {max(adj) - min(adj):.2f}）")


def test_build_gdp_gap_from_levels() -> None:
    qs = _quarters(2018, 1, 34)
    series = [(p, 100.0 * 1.02 ** (i / 4.0) * [0.99, 1.0, 1.02, 0.995][i % 4])
              for i, p in enumerate(qs)]
    res = hpm.build_gdp_gap_from_levels(series)
    check(res.available, f"水平路徑應可用：{res.reason}")
    check(res.gap is not None and abs(res.gap) < 0.03,
          f"平穩序列的缺口應很小，實得 {res.gap}")
    check(res.potential_growth is not None and 0.0 < res.potential_growth < 0.05,
          f"潛在增長應約 2%，實得 {res.potential_growth}")


def test_chain_yoy_no_explosive_distortion() -> None:
    qs = _quarters(2020, 1, 16)
    series = [(p, 0.02) for p in qs]           # 每季同比 +2%
    levels, missing = hpm.chain_yoy(series)
    check(missing == 0 and len(levels) == 16, "無缺季時應全部鏈接")
    check(abs(levels[0][1] - 100.0) < 1e-9, "第一年應錨定在 100")
    growth = levels[-1][1] / levels[0][1] - 1.0
    # 首年平滑錨 + 3 次精確 ×1.02 → 約 +6.6%，絕不能出現連乘爆增
    check(0.05 < growth < 0.08,
          f"16 季 2% 同比的水平增長應約 6.6%，實得 {growth:.2%}")


def test_build_gdp_gap_yoy_fallback_marks_precision() -> None:
    qs = _quarters(2018, 1, 32)
    series = [(p, 0.02 + 0.001 * (i % 4)) for i, p in enumerate(qs)]
    res = hpm.build_gdp_gap(series)
    check(res.available, "同比備援路徑應可用")
    check("精度較低" in (res.source or ""), "備援路徑必須標明精度較低")


# ---------------------------------------------------------------- 泰勒規則
def test_taylor_rule_signals() -> None:
    hike = tr.taylor_rule(rf=0.02, cpi=0.02, output_gap=0.0)
    check(approx(hike.theoretical_rate, 0.035), "理論利率 = r* + π + 0.5(π−π*) + 0.5·gap")
    check(hike.signal == "hike", f"市場利率遠低於理論 → 加息，實得 {hike.signal}")
    cut = tr.taylor_rule(rf=0.06, cpi=0.02, output_gap=0.0)
    check(cut.signal == "cut", "市場利率遠高於理論 → 減息")
    hold = tr.taylor_rule(rf=0.04, cpi=0.02, output_gap=0.0)
    check(hold.signal == "hold", "利率貼合理論 → 維持")
    check(hike.available and len(hike.note) > 10, "說明文字應存在")


# ---------------------------------------------------------------- 信用利差
def test_credit_spread_composition() -> None:
    spreads = EngineConfig().credit
    r = cr.cost_of_debt(0.040, "BBB", "公用事業",
                        spreads.rating_spreads, spreads.sector_spreads)
    check(approx(r.spread, 0.0185), "BBB 基準利差 1.85pp")
    check(approx(r.cost_of_debt, 0.0585), "rd = rf + 利差")
    r2 = cr.cost_of_debt(0.040, "AA", "地產",
                         spreads.rating_spreads, spreads.sector_spreads)
    check(approx(r2.spread, 0.0085 + 0.0060), "AA + 地產行業加價")
    r3 = cr.cost_of_debt(0.040, "ZZZ", "公用事業",
                         spreads.rating_spreads, spreads.sector_spreads)
    check(approx(r3.spread, 0.0185), "未知評級應退回 BBB")


# ---------------------------------------------------------------- 流動性
def test_liquidity_assessment() -> None:
    loose = lq.liquidity_assessment(0.005, 0.006)
    check(loose.stress < 0.25 and loose.label == "寬鬆", "低 HIBOR → 寬鬆")
    tight = lq.liquidity_assessment(0.055, 0.058)
    check(tight.stress >= 0.75 and tight.label == "收緊", "高 HIBOR → 收緊")
    check(approx(tight.premium, tight.stress * 0.004), "流動性溢價 = 壓力 × 上限")
    none = lq.liquidity_assessment(None)
    check(not none.available, "缺少 HIBOR 應標為不可用")


# ---------------------------------------------------------------- 隱含 ERP
def test_implied_erp_gordon_and_sentiment() -> None:
    r = iem.implied_erp(rf=0.040, fundamental=0.055, div_yield=0.036, pe=11.5)
    check(r.available and r.method == "gordon", "有股息率時用股利增長法")
    check(approx(r.gordon, 0.036 + 0.040 - 0.040), "Gordon ERP = 股息率 + g − rf")
    check(r.sentiment == "optimistic", f"隱含 3.6% < 基本面 5.5% → 偏樂觀，實得 {r.sentiment}")
    r2 = iem.implied_erp(rf=0.030, fundamental=0.050, pe=10.0)
    check(r2.available and r2.method == "earnings_yield", "無股息率時用盈利收益率法")
    check(approx(r2.earnings_yield, 0.10 - 0.030), "E/P 法 = 1/PE − rf")
    r3 = iem.implied_erp(rf=0.030, fundamental=0.050)
    check(not r3.available, "缺市場數據應標為不可用")


# ---------------------------------------------------------------- 波動率
def test_realized_volatility() -> None:
    check(analytics.realized_volatility([100.0] * 25, 20) == 0.0,
          "零變動序列的已實現波動率為 0")
    ups = [100.0 * (1.01 ** i) for i in range(25)]
    check(analytics.realized_volatility(ups, 20) is not None, "單邊走勢應有數值")


def test_volatility_profile_band() -> None:
    r = vol.volatility_profile(25000.0, 0.20, 0.04)
    check(r.available and r.level_label == "常態", "σ 20% → 常態")
    check(r.band_low < 25000.0 < r.band_high, "95% 區間應包含現值")
    check(0.0 < r.prob_below_20pct < 0.5, "一年內跌破 80% 的機率應小於 50%")


# ---------------------------------------------------------------- Altman
def test_altman_zones() -> None:
    # 手算：0.24 + 0.14 + 0.264 + 0.72 + 1.50 = 2.864 → 灰色區
    r = am.altman_z(1000, 200, 100, 80, 1500, 600, 500)
    check(r.available and approx(r.z, 2.864, 1e-9), f"Z 應為 2.864，實得 {r.z}")
    check(r.zone == "grey" and approx(r.premium, 0.008), "灰色區溢價 +0.8pp")
    safe = am.altman_z(1000, 300, 200, 120, 1500, 900, 300)
    check(safe.zone == "safe" and safe.premium == 0.0, "安全區無溢價")
    bad = am.altman_z(1000, 200, None, 80, 1500, 600, 500)
    check(not bad.available, "缺任一財務數字就不可用，不得補值")


# ---------------------------------------------------------------- PPP
def test_ppp_cumulative_inflation_regression() -> None:
    """曾把同比當環比連乘，兩年 2% 通脹算成 +60%；此測試防止回歸。"""
    months = _months((2023, 1), 35)            # 2023-01 .. 2025-11
    series = [(m, 0.02) for m in months]
    cum = pppm.cumulative_inflation(series, "2023-12")
    expected = 1.02 ** 2 - 1.0                 # 基準期後整 23 個月 ≈ 兩年複利
    check(cum is not None and abs(cum - expected) < 0.005,
          f"固定 2% 同比的累積應約 {expected:.2%}，實得 {cum}")
    check(cum is not None and cum < 0.10, "兩年 2% 通脹絕不可能累積到兩位數")


def test_ppp_misalignment_labels() -> None:
    months = _months((2023, 1), 24)
    hk = [(m, 0.02) for m in months]
    cn = [(m, 0.005) for m in months]
    fair_case = pppm.ppp_misalignment(0.925, 0.9100, "2023-12", hk, cn)
    check(fair_case.available, "CPI 足夠時應可用")
    check(fair_case.label == "接近均衡", f"小錯配 → 接近均衡，實得 {fair_case.label}")
    strong = pppm.ppp_misalignment(0.80, 0.9100, "2023-12", hk, cn)
    check(strong.label == "港元偏強" and strong.misalignment < -0.05,
          "現值遠低於 PPP 均衡 → 港元偏強")


# ---------------------------------------------------------------- 風險評分
def test_risk_score_and_band() -> None:
    r = rkm.macro_risk_score(rf=0.0422, cpi=0.019, unemp=0.041, natural_unemp=0.030,
                             trend_gdp=0.025, gdp_yoy=0.043, gdp_gap=0.0028)
    check(r.band_key == "low", f"各指標貼近目標 → 低風險，實得 {r.score:.1f}")
    check(approx(sum(c.weight for c in r.components), 1.0, 1e-9), "權重合計應為 1")
    r2 = rkm.macro_risk_score(rf=0.0422, cpi=0.045, unemp=0.055, natural_unemp=0.030,
                              trend_gdp=0.025, gdp_yoy=0.043, gdp_gap=-0.03,
                              liquidity_stress=1.0)
    check(r2.band_key in ("elevated", "high") and r2.score > r.score,
          "通脹高、失業升、缺口負、流動性緊 → 分數應顯著上升")
    for s, key in ((10, "low"), (40, "neutral"), (60, "elevated"), (90, "high")):
        check(rkm.risk_band(s)[0] == key, f"band({s}) 應為 {key}")


def test_risk_weight_remap() -> None:
    base = rkm.macro_risk_score(rf=0.0422, cpi=0.019, unemp=0.041, natural_unemp=0.030,
                                trend_gdp=0.025, gdp_yoy=0.043, gdp_gap=0.0028)
    remap = rkm.macro_risk_score(rf=0.0422, cpi=0.019, unemp=0.041, natural_unemp=0.030,
                                 trend_gdp=0.025, gdp_yoy=0.043, gdp_gap=0.0028,
                                 weights={"gdp_gap": 0.60, "unemployment": 0.15,
                                          "inflation": 0.15, "liquidity": 0.10})
    check(approx(sum(c.weight for c in remap.components), 1.0, 1e-9),
          "重映射後權重仍應合計 1")
    gw = {c.key: c.weight for c in remap.components}
    check(gw["growth"] > 0.5, "成長權重應按使用者設定放大")


# ---------------------------------------------------------------- WACC
def test_wacc_composition() -> None:
    w = waccm.build_wacc(re_nominal=0.11, rf=0.04, spread=0.02, cpi=0.02,
                         tax=0.165, debt_to_equity=0.35)
    dv = 0.35 / 1.35
    expect = (1 - dv) * 0.11 + dv * 0.06 * (1 - 0.165)
    check(approx(w.wacc_nominal, expect, 1e-9), "WACC = E/V·re + D/V·rd·(1−t)")
    check(approx(w.debt_weight, dv), "D/E 應換算成債務權重")
    check(approx(w.wacc_real, 1.094470 / 1.02 - 1, 1e-6), "費雪精確實質化")
    check(w.warning == "", "區間內不應有警告")
    w2 = waccm.build_wacc(0.11, 0.04, 0.02, 0.02, 0.165, 0.35, band=(0.02, 0.05))
    check(w2.warning != "", "超出警戒區間應產生警告")
    try:
        waccm.build_wacc(0.11, 0.04, 0.02, 0.02, 1.5, 0.35)
    except ValueError:
        check(True, "")
    else:
        raise AssertionError("稅率 ≥ 100% 應被拒絕")


# ---------------------------------------------------------------- DCF 參數
def test_dcf_g_cap_and_passthrough() -> None:
    cfg = EngineConfig()
    p = cfg.profile("hk_local")
    d = dcfm.build_dcf_params(p, 30.0, 0.20, 0.10, cfg.dcf)
    check(approx(d.g_cap, p.trend_gdp + p.infl_target), "g 上限 = 趨勢 + 通脹目標")
    check(d.g_capped and approx(d.g_effective, d.g_cap), "g 必須壓回上限")
    d2 = dcfm.build_dcf_params(p, 30.0, 0.20, 0.03, cfg.dcf)
    check(not d2.g_capped and approx(d2.g_effective, 0.03), "低於上限的 g 原樣保留")
    # 內地收入型：PMI 偏弱 + 內地通縮 → 傳導係數下調
    pm = cfg.profile("hk_mainland")
    d3 = dcfm.build_dcf_params(pm, 30.0, 0.20, None, cfg.dcf,
                               cn_cpi=0.005, cn_pmi=45.0)
    check(d3.pass_through < pm.pass_through, "內地因子應壓低通脹傳導")
    check(approx(d3.pass_through, pm.pass_through - 0.10 - 0.05), "PMI −0.10、通縮 −0.05")
    d4 = dcfm.build_dcf_params(p, 90.0, 0.35, None, cfg.dcf)
    check(cfg.dcf.equity_margin_low <= d4.margin_equity <= cfg.dcf.equity_margin_high,
          "安全邊際應夾在上下限內")


# ---------------------------------------------------------------- NPV 參數
def test_npv_standard_excludes_market_factors() -> None:
    cfg = npvm.NpvConfig()
    std = npvm.build_npv_params(0.096, 23.0, "neutral", cfg,
                                real_option=False, sigma=0.35, sentiment="cautious")
    check(std.option_adjust == 0.0 and std.option_volatility is None,
          "標準 NPV 不得讀取波動率／情緒")
    check("不讀取" in std.note, "說明必須明示隔離")
    opt = npvm.build_npv_params(0.096, 23.0, "neutral", cfg,
                                real_option=True, sigma=0.35, sentiment="cautious")
    check(opt.option_adjust > 0.0, "實物期權通道開啟後才允許 σ／情緒進入")
    check(opt.hurdle > std.hurdle, "通道開啟只會提高（更保守）門檻")
    lo = npvm.build_npv_params(0.096, 0.0, "stable", cfg)
    hi = npvm.build_npv_params(0.096, 100.0, "stagflation", cfg)
    check(cfg.minimum <= lo.multiplier < hi.multiplier <= cfg.maximum,
          "乘數應隨風險／週期上升，且被夾在上下限內")


# ---------------------------------------------------------------- ERP 歸因
def test_erp_decomposition_sums_exactly() -> None:
    cfg = EngineConfig()
    from macro_engine.models import MacroInputs as MI
    mi = MI("HK", _obs("rf", "10Y", 0.0402, "2026-09"),
            _obs("gdp", "GDP", 0.043, "2026Q2"),
            _obs("unemp", "失業", 0.041, "2026-09"),
            _obs("cpi", "CPI", 0.019, "2026-09"), 1.10)
    cyc = cycle.classify("HK", 0.043, 0.041, 0.019)
    profile = cfg.profile("hk_local")
    total, contrib, clipped = erp_decomposition(cfg, cyc, profile, mi,
                                                0.0028, 0.10, None, None)
    check(abs(sum(contrib.values()) - total) < 1e-12,
          "歸因貢獻（含 clip）合計必須等於總調整")
    check(not clipped, "正常情境不應觸及上下限")
    erp = cfg.erp.base + total
    check(cfg.erp.lower <= erp <= cfg.erp.upper, "ERP 必須落在硬上下限內")
    # 內地收入型 + 內地數據 → cn_factor 非零
    pm = cfg.profile("hk_mainland")
    _, contrib2, _ = erp_decomposition(cfg, cyc, pm, mi, 0.0028, 0.10, 0.005, 45.0)
    check(abs(contrib2["cn_factor"]) > 0, "內地收入型必須有內地因子調整")
    _, contrib3, _ = erp_decomposition(cfg, cyc, profile, mi, 0.0028, 0.10, 0.005, 45.0)
    check(contrib3["cn_factor"] == 0.0, "本地收入型不得被內地因子污染")


# ---------------------------------------------------------------- 快照庫
def test_snapshot_store_roundtrip() -> None:
    import time as _time
    with tempfile.TemporaryDirectory() as tmp:
        store = SnapshotStore(tmp)
        cfg = EngineConfig()
        payload = {"version": "2.0.0", "results": [
            {"region": "HK", "risk": {"score": 22.9},
             "inputs": [{"stage": "preliminary"}], "extras": []}]}
        s1 = store.save(payload, cfg, note="第一次")
        _time.sleep(1.1)
        payload["results"][0]["risk"]["score"] = 31.0
        s2 = store.save(payload, cfg, note="第二次")
        check(s1.stage == "preliminary", "含初步數據的快照應標 preliminary")
        snaps = store.list()
        check(len(snaps) == 2, "應能讀回兩筆快照")
        loaded = store.load(s2.ts)
        check(loaded is not None and loaded.payload["results"][0]["risk"]["score"] == 31.0,
              "load 應取回指定時點的內容")
        series = store.risk_series("HK")
        check(len(series) == 2 and series[0][1] < series[1][1],
              "風險序列應按時間排列")
        pruned = store.prune(keep=1)
        check(pruned >= 1 and len(store.list()) == 1, "prune 應只保留最新 N 筆")


# ---------------------------------------------------------------- 階段標籤
def test_stage_labels() -> None:
    check(STAGE_LABEL["preliminary"] == "初步", "初步標籤")
    check(STAGE_LABEL["revised"] == "修訂", "修訂標籤")
    check(STAGE_LABEL["final"] == "定稿", "定稿標籤")
    o = _obs("gdp", "GDP", 0.03, "2026Q2", stage="preliminary")
    check(o.stage_label == "初步", "Observation 應暴露中文階段標籤")


# ---------------------------------------------------------------- 端到端
def _synthetic_bundle():
    from macro_engine.engine import DataBundle
    from macro_engine.models import MacroInputs as MI

    qs = _quarters(2018, 1, 34)
    levels = [(p, 100.0 * 1.02 ** (i / 4.0) * [0.99, 1.0, 1.02, 0.995][i % 4])
              for i, p in enumerate(qs)]
    months = _months((2023, 1), 24)

    hk = MI("HK", _obs("rf", "10Y 港元政府債", 0.0402, "2026-09-30"),
            _obs("gdp", "GDP 實質同比", 0.043, "2026Q2"),
            _obs("unemp", "失業率", 0.041, "2026-09"),
            _obs("cpi", "綜合 CPI", 0.019, "2026-09"), 1.10,
            extras={"hibor_1m": _obs("hibor_1m", "HIBOR 1M", 0.0162, "2026-10"),
                    "hibor_3m": _obs("hibor_3m", "HIBOR 3M", 0.0177, "2026-10")})
    mo = MI("MO", _obs("rf", "10Y 港元政府債（共用）", 0.0402, "2026-09-30"),
            _obs("gdp", "GDP 同比", 0.010, "2026Q3"),
            _obs("unemp", "失業率", 0.018, "2026-09"),
            _obs("cpi", "CPI", 0.0133, "2026-09"), 1.15)
    market = MarketInputs(
        hsi_level=_obs("hsi", "恒生指數", 26000.0, "2026-11-04"),
        hsi_pe=_obs("hsi_pe", "恒指 PE", 11.5, "2026-11"),
        hsi_div_yield=_obs("hsi_dy", "恒指股息率", 0.036, "2026-11"),
        vhsi=_obs("vhsi", "VHSI", 0.22, "2026-11-04"),
        hkd_cny=_obs("fx", "HKD/CNY", 0.9200, "2026-11-04"),
        closes=[25000.0 * (1.0 + 0.0004 * i) for i in range(70)],
    )
    china = ChinaInputs(
        cpi=_obs("cn_cpi", "內地 CPI", 0.005, "2026-09"),
        pmi=_obs("cn_pmi", "內地 PMI", 49.2, "2026-09"),
        lpr_1y=_obs("lpr_1y", "LPR 1Y", 0.030, "2026-10"),
        lpr_5y=_obs("lpr_5y", "LPR 5Y", 0.035, "2026-10"),
        cpi_series=[(m, 0.005) for m in months],
    )
    return DataBundle(
        regions={"HK": hk, "MO": mo},
        histories={"HK": levels},
        history_kind={"HK": "level"},
        hk_cpi_history=[(m, 0.019) for m in months],
        market=market, china=china,
        errors={}, fetched_at="test",
    )


def test_end_to_end_compute() -> None:
    cfg = EngineConfig()
    out = compute(_synthetic_bundle(), cfg,
                  firm=FirmInputs(debt_to_equity=0.35, tax=0.165, g_user=0.03))
    check(len(out.results) == 2, "HK + MO 都應有結果")
    for res in out.results:
        erp = res.discount.adjusted_erp
        check(cfg.erp.lower <= erp <= cfg.erp.upper, f"{res.inputs.region} ERP 應在上下限內")
        check(res.wacc is not None and res.wacc.wacc_nominal > 0, "WACC 應為正")
        check(approx(res.dcf.g_cap, res.profile.trend_gdp + res.profile.infl_target),
              "g 上限 = 趨勢 + 通脹目標")
        check(res.npv.option_adjust == 0.0, "標準 NPV 分支不得混入市場因子")
        check(len(res.diagnosis) > 40, "自動診斷文字應存在")
        check(res.risk is not None and 0 <= res.risk.score <= 100, "風險分數應在 0–100")
    # ERP 歸因鏈
    hk = out.region("HK")
    check(abs(sum(hk.erp_contributions.values()) - hk.discount.erp_adjust) < 1e-12,
          "歸因合計 = ERP 調整")
    # 情境隔離：內地收入型的內地因子必須非零，且不影響本地型
    out2 = compute(_synthetic_bundle(), cfg,
                   profiles={"HK": "hk_mainland"},
                   firm=FirmInputs(debt_to_equity=0.35, tax=0.165))
    hk2 = out2.region("HK")
    check(abs(hk2.erp_contributions.get("cn_factor", 0.0)) > 0,
          "內地收入型應有內地因子調整")
    check(hk2.discount.adjusted_erp != hk.discount.adjusted_erp,
          "兩個情境的 ERP 不應相同")
    payload = out.to_dict()
    for key in ("config_hash", "results", "modules", "disclaimer", "market", "china"):
        check(key in payload, f"JSON 輸出缺少 {key}")


def test_compute_rejects_bad_config() -> None:
    cfg = EngineConfig().copy()
    cfg.erp.lower = 0.09
    try:
        compute(_synthetic_bundle(), cfg)
    except ValueError:
        check(True, "")
    else:
        raise AssertionError("驗證失敗的設定應被拒絕")


# ---------------------------------------------------------------- Excel 匯出
def test_excel_export_smoke() -> None:
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        print("    （未安裝 openpyxl，略過 Excel 測試）")
        return
    from macro_engine import excel_export
    from macro_engine.history import SnapshotStore as SS

    cfg = EngineConfig()
    out = compute(_synthetic_bundle(), cfg,
                  firm=FirmInputs(debt_to_equity=0.35, tax=0.165, g_user=0.03))
    with tempfile.TemporaryDirectory() as tmp:
        store = SS(tmp)
        store.save(out.to_dict(), cfg, note="測試快照")
        path = tmp + "\\export.xlsx"
        excel_export.export_excel(path, out, history_dir=tmp)
        wb = openpyxl.load_workbook(path)
        names = wb.sheetnames
        check(len(names) == 10, f"應有 10 張工作表，實得 {len(names)}：{names}")
        check(any("摘要" in n for n in names), "應有摘要表")


# ---------------------------------------------------------------- 執行
def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for func in tests:
        try:
            func()
            print(f"  ✓ {func.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  ✗ {func.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001 - 讓任何錯誤都算失敗而非崩潰
            failed += 1
            print(f"  ✗ {func.__name__}: 未預期錯誤 {type(exc).__name__}: {exc}")
    print(f"\n{len(tests)} 個測試、{PASSED} 個斷言，失敗 {failed} 個")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

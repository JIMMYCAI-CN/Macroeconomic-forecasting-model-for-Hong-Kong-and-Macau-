"""
sources/censtatd.py —— 香港政府統計處（C&SD）IDD Web API
=========================================================
官方 API 形式（實測可用，無需 key）：
    https://www.censtatd.gov.hk/api/get.php?id=<表號>&lang=en&full_series=1

回應結構：
    {"header": {...}, "dataSet": [{"freq":"Q","period":"202606","sv":...,
                                   "svDesc":"Year-on-year % change",
                                   "figure": 4.3, "sd_value": "p"}, ...]}

本模組固定抓三張表：
    310-31003  本地生產總值（連環物量，按開支組成部分）→ 實質同比
    510-60001  消費物價指數（2019/20 基期）→ 綜合 CPI 同比
    210-06103  失業率及就業不足率（按年齡及性別）→ 整體失業率（三個月）

注意：C&SD 的 series 代號會隨基期修訂改變（例如 CPI 的 CC_CM_1920），
所以程式用「前綴 + 描述」比對，而不是硬編一個會過期的代號。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..models import Observation
from ..net import DataSourceError, fetch_json, now_stamp, read_cache, write_cache

API = "https://www.censtatd.gov.hk/api/get.php?id={table}&lang=en&full_series=1"

TABLE_GDP = "310-31003"
TABLE_GDP_INDEX = "310-31001"
TABLE_CPI = "510-60001"
TABLE_UR = "210-06103"

SOURCE_NAME = "政府統計處 C&SD"
CACHE_KEY = "censtatd_hk"


def _url(table: str) -> str:
    return API.format(table=table)


def _records(table: str) -> List[Dict[str, Any]]:
    payload = fetch_json(_url(table))
    header = payload.get("header", {}).get("status", {})
    if header.get("code") not in (0, "0"):
        raise DataSourceError(f"C&SD 表 {table} 回應失敗：{header.get('description')}")
    data = payload.get("dataSet")
    if not isinstance(data, list) or not data:
        raise DataSourceError(f"C&SD 表 {table} 沒有資料")
    return data


def _num(value: Any) -> Optional[float]:
    """C&SD 有時用 '-' 或 '' 表示沒有數字。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _flag_note(flag: str) -> str:
    return {"p": "p＝初步數字", "r": "r＝修訂數字"}.get((flag or "").strip(), "")


def _flag_stage(flag: str) -> str:
    """把 C&SD 的 p/r 標記轉成回測用的修訂階段。"""
    return {"p": "preliminary", "r": "revised"}.get((flag or "").strip(), "final")


def _fmt_quarter(period: str) -> str:
    if len(period) == 6 and period.isdigit():
        return f"{period[:4]}Q{int(period[4:]) // 3}"
    return period


def _fmt_month(period: str) -> str:
    if len(period) == 6 and period.isdigit():
        return f"{period[:4]}-{period[4:]}"
    return period


def _fmt_3m(period: str) -> str:
    """三個月移動期間：202609 代表 2026 年 7–9 月。"""
    if len(period) == 6 and period.isdigit():
        year, month = int(period[:4]), int(period[4:])
        start = month - 2
        if start >= 1:
            return f"{year}-{start:02d}~{period[4:]}"
        # 跨年：1 月回看至上年 11 月
        return f"{year - 1}-11~{period[4:]}"
    return period


# 同一次執行內只抓一次大表：GDP 表有近 7000 列，重複抓會拖慢啟動
_MEMO: Dict[str, List[Dict[str, Any]]] = {}


def _records_memo(table: str) -> List[Dict[str, Any]]:
    if table not in _MEMO:
        _MEMO[table] = _records(table)
    return _MEMO[table]


def fetch_gdp_history() -> List[tuple]:
    """
    全部季度的實質同比（小數），按期間由舊到新。

    HP 濾波需要完整歷史；只取最新一期是算不出潛在產出的。
    """
    rows = [
        r for r in _records_memo(TABLE_GDP)
        if r.get("freq") == "Q"
        and (r.get("GDP_COMPONENT") or "") == ""
        and str(r.get("svDesc", "")).startswith("Year-on-year")
    ]
    out = []
    for r in rows:
        value = _num(r.get("figure"))
        period = r.get("period")
        if value is None or not period:
            continue
        out.append((_fmt_quarter(str(period)), value / 100.0))
    if len(out) < 8:
        raise DataSourceError("GDP 歷史序列不足，無法計算產出缺口")
    return sorted(set(out))


def fetch_gdp_levels() -> List[tuple]:
    """
    實質 GDP 指數（2024 = 100）季度水平，供 HP 濾波直接使用。

    這比用同比鏈接可靠得多：同比只有「相對去年同季」，無法還原年內水平，
    任何鏈接都會把基準年的年內結構永久帶進整條序列。
    C&SD 表 310-31001 直接提供連環物量指數，是本引擎的首選。
    """
    rows = [
        r for r in _records_memo(TABLE_GDP_INDEX)
        if r.get("freq") == "Q"
        and str(r.get("svDesc", "")) == "Index (Year 2024=100)"
    ]
    out = []
    for r in rows:
        value = _num(r.get("figure"))
        period = r.get("period")
        if value is None or not period:
            continue
        out.append((_fmt_quarter(str(period)), value))
    if len(out) < 24:
        raise DataSourceError("實質 GDP 指數序列不足 24 季")
    return sorted(set(out))


def fetch_cpi_history() -> List[tuple]:
    """全部月份的綜合 CPI 同比（小數），供 PPP 累計通脹使用。"""
    rows = [
        r for r in _records_memo(TABLE_CPI)
        if r.get("freq") == "M"
        and str(r.get("sv", "")).startswith("CC")
        and str(r.get("svDesc", "")).startswith("Year-on-year")
    ]
    out = []
    for r in rows:
        value = _num(r.get("figure"))
        period = r.get("period")
        if value is None or not period:
            continue
        out.append((_fmt_month(str(period)), value / 100.0))
    return sorted(set(out))


def fetch_gdp() -> Observation:
    """香港 GDP 實質同比增長（最新季度）。"""
    rows = [
        r for r in _records_memo(TABLE_GDP)
        if r.get("freq") == "Q"
        and (r.get("GDP_COMPONENT") or "") == ""          # 整體 GDP
        and str(r.get("svDesc", "")).startswith("Year-on-year")
    ]
    if not rows:
        raise DataSourceError("找不到 GDP 實質同比序列")
    latest = max(rows, key=lambda r: r["period"])
    value = _num(latest.get("figure"))
    if value is None:
        raise DataSourceError("GDP 最新一期沒有數字")
    return Observation(
        key="gdp",
        label="GDP 實質同比",
        value=value / 100.0,
        period=_fmt_quarter(latest["period"]),
        source=f"{SOURCE_NAME} 表 {TABLE_GDP}",
        url=_url(TABLE_GDP),
        status="live",
        note=_flag_note(latest.get("sd_value", "")),
        stage=_flag_stage(latest.get("sd_value", "")),
    )


def fetch_cpi() -> Observation:
    """香港綜合消費物價指數同比（最新月份）。"""
    rows = [
        r for r in _records_memo(TABLE_CPI)
        if r.get("freq") == "M"
        and str(r.get("sv", "")).startswith("CC")          # CC = Composite CPI
        and str(r.get("svDesc", "")).startswith("Year-on-year")
    ]
    if not rows:
        raise DataSourceError("找不到綜合 CPI 同比序列")
    latest = max(rows, key=lambda r: r["period"])
    value = _num(latest.get("figure"))
    if value is None:
        raise DataSourceError("CPI 最新一期沒有數字")
    return Observation(
        key="cpi",
        label="綜合 CPI 同比",
        value=value / 100.0,
        period=_fmt_month(latest["period"]),
        source=f"{SOURCE_NAME} 表 {TABLE_CPI}",
        url=_url(TABLE_CPI),
        status="live",
        note=_flag_note(latest.get("sd_value", "")),
        stage=_flag_stage(latest.get("sd_value", "")),
    )


def fetch_unemployment() -> Observation:
    """香港整體失業率（三個月移動，經季節性調整）。"""
    rows = [
        r for r in _records_memo(TABLE_UR)
        if r.get("sv") == "UR"
        and (r.get("AGE") or "") == ""
        and (r.get("SEX") or "") == ""
        and r.get("freq") == "M3M"
    ]
    if not rows:
        raise DataSourceError("找不到整體失業率序列")
    latest = max(rows, key=lambda r: r["period"])
    value = _num(latest.get("figure"))
    if value is None:
        raise DataSourceError("失業率最新一期沒有數字")
    return Observation(
        key="unemp",
        label="失業率",
        value=value / 100.0,
        period=_fmt_3m(latest["period"]),
        source=f"{SOURCE_NAME} 表 {TABLE_UR}",
        url=_url(TABLE_UR),
        status="live",
        note=_flag_note(latest.get("sd_value", "")),
        stage=_flag_stage(latest.get("sd_value", "")),
    )


def fetch_all(offline: bool = False) -> Dict[str, Observation]:
    """
    一次抓三條序列，並把結果寫入本地快取。

    每一項獨立降級：某一張表掛掉時，只有該項退回快取，
    其餘仍然是即時數據，不會因為一個 API 失敗就全部變舊資料。
    """
    fetchers = {"gdp": fetch_gdp, "cpi": fetch_cpi, "unemp": fetch_unemployment}
    cached = read_cache(CACHE_KEY) or {}
    out: Dict[str, Observation] = {}
    fresh: Dict[str, dict] = {}

    for key, func in fetchers.items():
        if offline:
            item = cached.get(key)
            if not item:
                raise DataSourceError("離線模式但沒有 C&SD 快取，請先連線執行一次")
            out[key] = _from_cache_item(key, item)
            continue
        try:
            obs = func()
            out[key] = obs
            fresh[key] = {
                "value": obs.value, "period": obs.period,
                "source": obs.source, "note": obs.note,
                "stage": obs.stage, "url": obs.url,
                "fetched_at": now_stamp(),   # 記下抓取時間，快取才能顯示時效
            }
        except Exception as exc:  # noqa: BLE001 - 單項降級
            item = cached.get(key)
            if not item:
                raise DataSourceError(f"{key} 讀取失敗且無快取：{exc}") from exc
            out[key] = _from_cache_item(key, item)

    if fresh:
        merged = {**cached, **fresh}
        write_cache(CACHE_KEY, merged)
    return out


LABELS = {"gdp": "GDP 實質同比", "cpi": "綜合 CPI 同比", "unemp": "失業率"}


def _from_cache_item(key: str, item: Dict[str, Any]) -> Observation:
    return Observation(
        key=key,
        label=LABELS.get(key, key),
        value=float(item["value"]),
        period=str(item.get("period", "")),
        source=str(item.get("source", SOURCE_NAME)),
        status="cache",
        note=str(item.get("note", "")),
        stage=str(item.get("stage", "final")),
        url=str(item.get("url", "")),
        fetched_at=str(item.get("fetched_at", "")),
    )

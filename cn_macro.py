"""
sources/cn_macro.py —— 內地宏觀因子（CPI、PMI、LPR）
=========================================================
港股中有大量企業的收入主要來自內地。只调整香港本地 CPI 並不足夠：
內地物價決定成本端、內地 PMI 決定需求端、LPR 決定內地融資環境，
三者都會透過「內地收入型」情境影響合理的折現率與增長假設。

資料來源（皆為公開、無需 key）：
  * 國家統計局月度數據的鏡像：東方財富 datacenter API
      RPT_ECONOMY_CPI / RPT_ECONOMY_PMI
  * 貸款市場報價利率（LPR）：中國貨幣網 LprHis 介面

每一項都獨立降級（即時 → 快取 → 內建基準），並在 Observation 標明狀態；
抓不到時**不會**假裝是今天的數字。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..models import Observation
from ..net import DataSourceError, fetch_json, now_stamp, read_cache, write_cache

EASTMONEY = (
    "https://datacenter-web.eastmoney.com/api/data/v1/get?"
    "reportName={report}&columns=ALL&sortColumns=REPORT_DATE&sortTypes=-1"
    "&pageSize={size}&pageNumber=1"
)
LPR_URL = "https://www.chinamoney.com.cn/ags/ms/cm-u-bk-currency/LprHis?lang=CN"
CACHE_KEY = "cn_macro"
SEED_PATH = Path(__file__).resolve().parent.parent / "data" / "cn_seed.json"

_MONTH_CN = {
    "01": "01", "02": "02", "03": "03", "04": "04", "05": "05", "06": "06",
    "07": "07", "08": "08", "09": "09", "10": "10", "11": "11", "12": "12",
}


def _month(raw: Any) -> str:
    """'2026年09月份' / '2026-09-01 00:00:00' → '2026-09'。"""
    text = str(raw or "")
    if "年" in text:
        year, _, rest = text.partition("年")
        month = rest[:2]
        if year.isdigit() and month in _MONTH_CN:
            return f"{year}-{month}"
    if len(text) >= 7 and text[4] == "-":
        return text[:7]
    return ""


def fetch_cpi_history(size: int = 60) -> List[Tuple[str, float]]:
    """內地 CPI 同比月度序列（小數），由新到舊排序。"""
    payload = fetch_json(EASTMONEY.format(report="RPT_ECONOMY_CPI", size=size))
    rows = (payload.get("result") or {}).get("data") or []
    out: List[Tuple[str, float]] = []
    for row in rows:
        period = _month(row.get("REPORT_DATE") or row.get("TIME"))
        value = row.get("NATIONAL_SAME")
        if period and value is not None:
            out.append((period, float(value) / 100.0))
    if not out:
        raise DataSourceError("東方財富 CPI 沒有可用數據")
    return sorted(out)


def fetch_cpi() -> Observation:
    series = fetch_cpi_history(24)
    period, value = series[-1]
    return Observation(
        key="cn_cpi", label="內地 CPI 同比", value=value, period=period,
        source="國家統計局月度數據（東方財富鏡像）", url=EASTMONEY.format(
            report="RPT_ECONOMY_CPI", size=24),
        status="live",
    )


def fetch_pmi() -> Observation:
    payload = fetch_json(EASTMONEY.format(report="RPT_ECONOMY_PMI", size=24))
    rows = (payload.get("result") or {}).get("data") or []
    best: Optional[Tuple[str, float]] = None
    for row in rows:
        period = _month(row.get("REPORT_DATE") or row.get("TIME"))
        value = row.get("MAKE_INDEX")
        if period and value is not None and (best is None or period > best[0]):
            best = (period, float(value))
    if best is None:
        raise DataSourceError("東方財富 PMI 沒有可用數據")
    return Observation(
        key="cn_pmi", label="內地製造業 PMI", value=best[1], period=best[0],
        source="國家統計局月度數據（東方財富鏡像）",
        url=EASTMONEY.format(report="RPT_ECONOMY_PMI", size=24),
        status="live", note="50 為榮枯線",
    )


def _lpr_date(raw: str) -> str:
    """'20 Oct 2026' → '2026-10-20'。"""
    months = {"Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05",
              "Jun": "06", "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10",
              "Nov": "11", "Dec": "12"}
    parts = str(raw or "").split()
    if len(parts) == 3 and parts[1] in months:
        return f"{parts[2]}-{months[parts[1]]}-{int(parts[0]):02d}"
    return ""


def fetch_lpr() -> Dict[str, Observation]:
    payload = fetch_json(LPR_URL)
    records = payload.get("records") or []
    if not records:
        raise DataSourceError("中國貨幣網 LPR 沒有記錄")
    latest = records[0]
    period = _lpr_date(latest.get("showDateEN", "")) or str(latest.get("showDateCN", ""))
    out: Dict[str, Observation] = {}
    for key, field, label in (("lpr_1y", "1Y", "內地 LPR（1 年）"),
                              ("lpr_5y", "5Y", "內地 LPR（5 年）")):
        raw = latest.get(field)
        if raw is None:
            continue
        out[key] = Observation(
            key=key, label=label, value=float(raw) / 100.0, period=period,
            source="全國銀行間同業拆借中心（中國貨幣網）", url=LPR_URL,
            status="live",
        )
    if not out:
        raise DataSourceError("LPR 欄位解析失敗")
    return out


def _seed() -> Dict[str, Observation]:
    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    out: Dict[str, Observation] = {}
    for key, item in data.items():
        if not isinstance(item, dict):
            continue
        out[key] = Observation(
            key=key, label=item.get("label", key), value=float(item["value"]),
            period=str(item.get("period", "")), source="內地宏觀內建基準（離線備用）",
            status="seed", note=str(item.get("note", "")),
        )
    return out


def fetch_all(offline: bool = False) -> Tuple[Dict[str, Observation], List[Tuple[str, float]]]:
    """
    回傳 (指標字典, CPI 月度序列)。

    序列用於 PPP 的累計通脹；若即時抓不到，會用快取中的序列。
    """
    cached = read_cache(CACHE_KEY) or {}
    fresh: Dict[str, Any] = {}
    series: List[Tuple[str, float]] = []

    if not offline:
        try:
            series = fetch_cpi_history(48)
            fresh["cpi_series"] = [[p, v] for p, v in series]
        except Exception:  # noqa: BLE001
            series = [tuple(x) for x in cached.get("cpi_series", [])]  # type: ignore[misc]

        for key, func in (("cpi", fetch_cpi), ("pmi", fetch_pmi)):
            try:
                obs = func()
                fresh[key] = {"value": obs.value, "period": obs.period,
                              "label": obs.label, "source": obs.source,
                              "note": obs.note, "fetched_at": now_stamp()}
            except Exception:  # noqa: BLE001 - 單項降級
                pass
        try:
            for key, obs in fetch_lpr().items():
                fresh[key] = {"value": obs.value, "period": obs.period,
                              "label": obs.label, "source": obs.source,
                              "fetched_at": now_stamp()}
        except Exception:  # noqa: BLE001
            pass
    else:
        series = [tuple(x) for x in cached.get("cpi_series", [])]  # type: ignore[misc]

    merged = {**cached, **fresh}
    if fresh:
        write_cache(CACHE_KEY, merged)

    out: Dict[str, Observation] = {}
    for key in ("cpi", "pmi", "lpr_1y", "lpr_5y"):
        item = merged.get(key)
        if isinstance(item, dict) and "value" in item:
            fresh_now = key in fresh
            target = "cn_" + key if key in ("cpi", "pmi") else key
            out[target] = Observation(
                key=target,
                label=str(item.get("label", key)),
                value=float(item["value"]),
                period=str(item.get("period", "")),
                source=str(item.get("source", "")),
                status="live" if fresh_now else "cache",
                note=str(item.get("note", "")),
                fetched_at="" if fresh_now else str(item.get("fetched_at", "")),
            )

    seed_map = {"cpi": "cn_cpi", "pmi": "cn_pmi", "lpr_1y": "lpr_1y", "lpr_5y": "lpr_5y"}
    for key, obs in _seed().items():
        target = seed_map.get(key, key)
        if target not in out:
            obs.key = target
            out[target] = obs
    return out, series

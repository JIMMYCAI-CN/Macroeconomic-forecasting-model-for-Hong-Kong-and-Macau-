"""
sources/dsec.py —— 澳門統計暨普查局（DSEC）
=========================================================
澳門沒有像 C&SD 那種穩定的公開 API。實測結果：

  * TimeSeriesApi（https://www.dsec.gov.mo/TimeSeriesApi/...）
    指標樹與指標清單可用，但「取數值」的介面目前回傳 SQL 例外
    （IndicatorValue/LatestSameEndPeriodv3 全參數組合都失敗），
    所以不能作為唯一資料來源。

  * WechatApi/KeyIndicator.aspx
    官方維護的行動版「主要指標」頁，純 HTML、更新及時，
    直接含綜合 CPI 同比與總體失業率，是本模組的主要來源。

  * GDP 實質增長不在該頁（頁上只有 GDP 總額的絕對值），
    因此改用 DSEC 新聞稿公布的季度實質增長，存於 data/mo_gdp_seed.json，
    可用 --mo-gdp 覆寫。

這種「一項即時、一項基準值」的混搭在報告中會逐項標示，
不會讓使用者誤以為全部都是即時數據。
"""

from __future__ import annotations

import html as html_mod
import json
import re
from pathlib import Path
from typing import Dict, Optional, Tuple

from ..models import Observation
from ..net import DataSourceError, fetch_text, now_stamp, read_cache, write_cache

KEY_INDICATOR_URL = "https://www.dsec.gov.mo/WechatApi/KeyIndicator.aspx"
SOURCE_NAME = "澳門統計暨普查局 DSEC"
CACHE_KEY = "dsec_key_indicator"
GDP_SEED = Path(__file__).resolve().parent.parent / "data" / "mo_gdp_seed.json"

_CELL_RE = re.compile(
    r'<div class="weui_cell_bd[^"]*"[^>]*>(.*?)</div>\s*'
    r'<div class="weui_cell_ft[^"]*"[^>]*>(.*?)</div>',
    re.S,
)
_UPDATE_RE = re.compile(r"更新：\s*([0-9]{4}-[0-9]{2}-[0-9]{2})")
_PERIOD_CN_RE = re.compile(
    r"[(（]\s*([0-9]{4})年\s*([0-9]{1,2})月"
    r"(?:\s*至\s*(?:([0-9]{4})年)?\s*([0-9]{1,2})月)?\s*[)）]"
)


def _plain(fragment: str) -> str:
    """去掉標籤與 HTML 實體，壓成單行。"""
    text = re.sub(r"<br\s*/?>", " ", fragment, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", html_mod.unescape(text)).strip()


def _period(raw: str) -> str:
    """把「2026年7月至9月」這種寫法轉成 2026-07~09。"""
    match = _PERIOD_CN_RE.search(raw)
    if not match:
        return ""
    year, start = match.group(1), int(match.group(2))
    end_year, end = match.group(3), match.group(4)
    if end:
        if end_year and end_year != year:
            return f"{year}-{start:02d}~{end_year}-{int(end):02d}"
        return f"{year}-{start:02d}~{int(end):02d}"
    return f"{year}-{start:02d}"


def _num(raw: str) -> Optional[float]:
    cleaned = raw.replace(",", "").replace("%", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_key_indicator(page: str) -> Dict[str, Dict[str, object]]:
    """
    解析「主要指標」頁，回傳 {key: {value, period, label}}。

    頁面片段長相：
        <div class="weui_cell_bd weui_cell_primary" ...>綜合消費物價指數按年變動
            <br/>(2026年9月)(%)</div><div class="weui_cell_ft" ...>1.33</div>
    """
    out: Dict[str, Dict[str, object]] = {}
    for label_html, value_html in _CELL_RE.findall(page):
        label = _plain(label_html)
        value = _num(_plain(value_html))
        if value is None:
            continue
        if "綜合消費物價指數按年變動" in label:
            key = "cpi"
        elif "總體失業率" in label:
            key = "unemp"
        elif "本地居民失業率" in label:
            key = "unemp_resident"
        elif "本地生產總值" in label and "實質" in label:
            key = "gdp"
        else:
            continue
        out[key] = {"value": value, "period": _period(label), "label": label}

    updated = _UPDATE_RE.search(page)
    if updated:
        out["_updated"] = {"value": 0.0, "period": updated.group(1), "label": "頁面更新日"}

    if "cpi" not in out or "unemp" not in out:
        raise DataSourceError("DSEC 主要指標頁格式改變，找不到 CPI 或失業率")
    return out


def _load_key_page() -> Tuple[Dict[str, Dict[str, object]], bool]:
    """回傳 (解析結果, 是否即時)。抓不到就用上次快取。"""
    try:
        page = fetch_text(KEY_INDICATOR_URL, encoding="utf-8")
        parsed = parse_key_indicator(page)
        stamp = now_stamp()
        for k in ("cpi", "unemp"):
            parsed[k]["fetched_at"] = stamp   # 記下抓取時間，快取才能顯示時效
        write_cache(
            CACHE_KEY,
            {
                "cpi": parsed["cpi"],
                "unemp": parsed["unemp"],
                "updated": parsed.get("_updated", {}).get("period", ""),
            },
        )
        return parsed, True
    except Exception as exc:  # noqa: BLE001 - 降級到快取
        cached = read_cache(CACHE_KEY)
        if not cached:
            raise DataSourceError(f"DSEC 主要指標讀取失敗且無快取：{exc}") from exc
        parsed = {k: cached[k] for k in ("cpi", "unemp") if k in cached}
        parsed["_updated"] = {"period": cached.get("updated", "")}
        return parsed, False


def fetch_cpi(parsed: Optional[Dict[str, Dict[str, object]]] = None,
              live: Optional[bool] = None) -> Observation:
    parsed = parsed or _load_key_page()[0]
    item = parsed["cpi"]
    live = live if live is not None else True
    return Observation(
        key="cpi",
        label="綜合 CPI 同比",
        value=float(item["value"]) / 100.0,
        period=str(item.get("period") or ""),
        source=f"{SOURCE_NAME}（主要指標頁）",
        url=KEY_INDICATOR_URL,
        status="live" if live else "cache",
        fetched_at="" if live else str(item.get("fetched_at", "")),
    )


def fetch_unemployment(parsed: Optional[Dict[str, Dict[str, object]]] = None,
                       live: Optional[bool] = None,
                       basis: str = "overall") -> Observation:
    """
    basis='overall' 用總體失業率（國際可比）；
    basis='resident' 用本地居民失業率（澳門政策討論常用，數值較高）。
    """
    parsed = parsed or _load_key_page()[0]
    live = live if live is not None else True
    key = "unemp_resident" if basis == "resident" and "unemp_resident" in parsed else "unemp"
    item = parsed[key]
    label = "本地居民失業率" if key == "unemp_resident" else "失業率"
    return Observation(
        key="unemp",
        label=label,
        value=float(item["value"]) / 100.0,
        period=str(item.get("period") or ""),
        source=f"{SOURCE_NAME}（主要指標頁）",
        url=KEY_INDICATOR_URL,
        status="live" if live else "cache",
        note="澳門口徑：本地居民口徑" if key == "unemp_resident" else "",
        fetched_at="" if live else str(item.get("fetched_at", "")),
    )


def fetch_gdp_placeholder() -> Observation:
    data = json.loads(GDP_SEED.read_text(encoding="utf-8"))
    return Observation(
        key="gdp",
        label="GDP 實質同比",
        value=float(data["value"]),
        period=str(data["period"]),
        source=f"DSEC 新聞稿（{data['period']} 初步值）",
        url=str(data.get("url", "")),
        status="seed",
        note=str(data.get("note", "")),
        stage="preliminary",
    )


def fetch_all(offline: bool = False, basis: str = "overall") -> Dict[str, Observation]:
    if offline:
        cached = read_cache(CACHE_KEY)
        if not cached:
            raise DataSourceError("離線模式但沒有 DSEC 快取")
        parsed = {k: cached[k] for k in ("cpi", "unemp") if k in cached}
        parsed["_updated"] = {"period": cached.get("updated", "")}
        live = False
    else:
        parsed, live = _load_key_page()
    return {
        "gdp": fetch_gdp_placeholder(),
        "cpi": fetch_cpi(parsed, live),
        "unemp": fetch_unemployment(parsed, live, basis=basis),
    }

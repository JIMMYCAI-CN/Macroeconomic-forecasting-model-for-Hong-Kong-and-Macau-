# 港澳宏觀折現率引擎 2.0

Hong Kong / Macao Macro Parameter Engine — 面向港股、澳門相關企業 DCF／NPV 估值的
**宏觀參數上游模組**。

引擎只做一件事：把宏觀數據整理成**統一、可追溯、可回測**的一套折現率校準參數
（rf → 週期／HP 缺口 → ERP → CAPM → WACC → DCF／NPV 參數）。
**不計算**股價、FCF、項目現金流或 NPV 本身——那些是下游模型的事。

> 備註：僅供港股、澳門相關企業 DCF／NPV 估值參考，不是投資建議。

---

## 1. 全景

```
資料層（四級降級：API → 官方檔案 → 快取 → 種子/手動）
  ├─ 香港：10Y 港元政府債、實質 GDP 指數、CPI、失業率、HIBOR、恒指、VHSI、HKD/CNY
  ├─ 澳門：GDP、CPI、失業率（rf 沿用港元，聯繫匯率制度）
  ├─ 內地（輔助）：CPI、PMI、LPR
  └─ 每筆輸入都是 Observation：值 + 期間 + 來源 + 狀態 + 修訂階段（初步/修訂/定稿）
          │
          ▼
計算層（analytics/ 12 個純函數模組，全部可開關）
  HP 缺口（λ=1600，季節調整）· 泰勒規則 · 信用利差 · 流動性溢價
  隱含 ERP 對比 · 波動率剖面 · Altman Z（預設關） · PPP 匯率錯配
          │
          ▼
  ERP = 基準 + 週期溢價 + Σ(權重×因子分數×上限) + 內地二次調整
        → 夾在 [3.0%, 8.5%]，截斷差額以「clip」入帳，歸因合計必等於總調整
          │
          ▼
輸出層
  WACC（名義/實質，稅盾只在債務）· 風險分 0–100（低/中性/偏高/高）
  政策方向（加息/維持/減息）· DCF 參數（g 上限、通脹傳導、雙安全邊際）
  NPV 參數（風險乘數、項目門檻）· 自動診斷文字
```

三條下游分支：

| 分支 | 使用 | 明確隔離 |
|---|---|---|
| DCF 股權估值 | WACC、g 上限、通脹傳導、安全邊際、（可選）隱含 ERP／波動率／PPP | — |
| 標準 NPV 資本開支 | 風險乘數、項目門檻 | **不讀取** VIX／隱含 ERP／Z-Score／PPP／永續增長 |
| 實物期權（預設關） | 解鎖 σ／情緒進入 NPV 門檻 | 需在參數頁明確開啟 |

地區情境彼此隔離：`hk_local`（港股本地收入型）、`hk_mainland`（港股內地收入型，
額外吃內地 CPI／PMI 二次調整）、`mo_local`（澳門本地企業）。參數不交叉污染。

## 2. 快速開始

```bash
python run_macro.py --gui                  # 七頁籤圖形介面儀表板
python run_macro.py                        # 港澳一次算完（即時數據）
python run_macro.py --region HK --beta 1.25
python run_macro.py --profile hk_mainland  # 內地收入型港股
python run_macro.py --rf 4.10% --mo-gdp 1.5%   # 手動覆寫個別輸入
python run_macro.py --offline              # 無網路：只用快取／內建值
python run_macro.py --show-thresholds      # 印出港澳兩套門檻
python run_macro.py --history              # 歷史快照與風險分數序列
python run_macro.py --json out.json --excel out.xlsx
```

Windows 可雙擊 `start_gui.bat`（GUI）或 `start_macro.bat`（命令列）。

當函式庫用：

```python
from macro_engine import EngineConfig, build_bundle, compute, FirmInputs

cfg = EngineConfig()                       # 所有界限／權重／利差都在這裡調
bundle = build_bundle(cfg)                 # 抓數據（離線：build_bundle(cfg, offline=True)）
out = compute(bundle, cfg, firm=FirmInputs(debt_to_equity=0.35, g_user=0.03))
hk = out.region("HK")
print(hk.wacc.wacc_nominal, hk.dcf.g_cap, hk.risk.score, hk.diagnosis)
out.to_dict()                              # 完整 JSON（含設定指紋，可入庫回測）
```

**核心只用 Python 標準庫**（3.9+）。可選：`xlrd`（讀 HKMA 官方 XLS 收益率表）、
`openpyxl`（Excel 匯出）。

## 3. 資料來源與降級鏈

| 項目 | 主要來源 | 備援 |
|---|---|---|
| 香港 rf（10Y） | HKMA 月報表 10.4.5 XLS（API 受 WAF 攔截時的既定路徑） | 本地快取 → 內建基準值 → 手動 |
| 香港 GDP | C&SD IDD 表 **310-31001 實質 GDP 指數（2024=100）**，HP 首選輸入 | 表 310-31003 同比（備援，標「精度較低」） |
| 香港 CPI／失業率 | C&SD IDD 表 510-60001／210-06103 | 本地快取 |
| HIBOR 1M/3M | 手動覆寫優先；否則由 10Y 期限利差推導（標 `derived`） | 內建假設 |
| 恒指／HKD/CNY | Yahoo Finance 圖表 JSON／Frankfurter（ECB） | 本地快取 → 種子值 |
| 澳門 CPI／失業率 | DSEC「主要指標」頁 | 本地快取 → 手動 |
| 澳門 GDP | DSEC 新聞稿季度實質增長（種子） | `--mo-gdp` 覆寫 |
| 內地 CPI／PMI | Eastmoney 數據中心 | 種子值 |
| LPR | chinamoney 官網 JSON | 種子值 |

狀態標記：`live 即時` / `file 官方檔案` / `cache 快取` / `seed 內建` /
`manual 手動` / `derived 推導`；修訂階段：`初步(p) / 修訂 / 定稿`——
回測時可區分「當時看到的初版數字」與「後來的定稿數字」，避免後視偏差。

## 4. 核心規則（全部可配置，無寫死參數）

- **ERP**：`ERP = 5.5% 基準 + 週期溢價 + Σ(權重×因子×2pp 上限) + 內地調整`，
  夾在 **3.0%–8.5%**；因子為 GDP 缺口 35%／失業 25%／通脹 20%／流動性 20%（滑桿可調）。
- **週期**：港澳門檻各一套，優先次序互斥（過熱→滯脹→衰退→繁榮穩定→復甦／中性），
  附逐條判定軌跡與臨界情境提示。CPI ≥ 3% 一律視為過熱訊號。
- **WACC**：`rd = rf + 信用利差（評級×行業矩陣）`；`WACC = E/V·re + D/V·rd·(1−t)`，
  稅盾只在債務。re 與 WACC 各有警戒區間，超出即紅字 + 警告。
- **g 上限**：`永續增長 g ≤ 長期名義 GDP 增速 = 實質趨勢 + 通脹目標`，超出壓回。
- **費雪精確式**：`(1+名義)/(1+π) − 1`，不用近似式。
- **風險分 0–100**：利率 18%／通脹 20%／失業 20%／增長 27%／流動性 15%，
  權重隨 ERP 滑桿等比重映射；<30 低／30–50 中性／50–70 偏高／≥70 高。
- **政策方向**：泰勒規則理論利率 vs 市場 10Y（扣期限溢價），±25bp 內視為維持。

## 5. 快照與回測

每次「重算」自動把**完整假設快照**寫入 `output/history/snapshots.jsonl`：
全部輸入觀測值（含狀態與修訂階段）、設定指紋（`config.hash()`）、風險分數、診斷文字。
CLI `--history` 可列出快照、還原任一時點重算、匯出風險分數序列——
這是回測 ERP／WACC 調整貢獻的基礎。

## 6. 圖形介面（七頁籤）

`python run_macro.py --gui`

1. **總覽** — 港澳 12 張結果卡（週期、ERP、re、WACC、風險）＋宏觀數據表
   （數值／期間／狀態／修訂階段／時效／來源，超時效轉紅）＋ERP 組成疊圖。
2. **折現率與 WACC** — 10 張卡（rd、信用利差、D/E 權重、名義/實質 WACC…）＋
   WACC 疊疊橫條＋基本面 vs 市場隱含 ERP 對照。
3. **DCF 參數** — g 上限（趨勢+通脹）、g 是否被壓回、通脹傳導、雙安全邊際＋診斷文字。
4. **NPV／項目** — 風險乘數、項目門檻、五種週期下的門檻階梯圖；明示標準 NPV 隔離範圍。
5. **週期與風險** — 風險儀表、五因子分項、風險分數歷史、週期判定軌跡、GDP 缺口柱狀。
6. **歷史快照** — 快照列表、還原重算、假設差異檢視。
7. **參數與覆寫** — ERP 規則、權重滑桿（即時顯示歸一化比例）、模組開關（關閉即隱藏
   卡片與圖表並退出計算）、15 個手動覆寫欄位、Altman 財務欄位、設定載入/儲存。

手動覆寫值顯示**橙色**、計算值黑色；滑鼠懸停 ERP／WACC／缺口／隱含 ERP 等卡片
有方法論提示。底部免責聲明常駐。

## 7. Excel 審計包（10 工作表）

`01 摘要`、`02 ERP 歸因`、`03 折現率與 WACC`、`04 DCF 參數`、`05 NPV 參數`、
`06 模組輸出`、`07 宏觀數據`（含每筆來源與狀態）、`08 週期與風險`（判定軌跡）、
`09 假設清單`（設定指紋＋全部可調參數）、`10 歷史快照`。
手動值橙底、超警戒紅底（需 openpyxl）。

## 8. 模組結構

```
run_macro.py                 入口（CLI + --gui）
macro_engine/
  config.py    全部可調參數：ERP 界限/權重、警戒帶、利差矩陣、地區情境、模組開關
  models.py    Observation / MacroInputs / MarketInputs / ChinaInputs / FirmInputs
  net.py       標準庫 HTTP、重試、本地快取（.cache/macro）
  sources/     censtatd（C&SD）、hkma（rf）、dsec（澳門）、cn_macro（內地）、
               market（恒指/匯率）、hibor（推導+手動）
  analytics/   hp · taylor · credit · liquidity · implied_erp · volatility ·
               altman · ppp · risk · wacc · dcf · npv（純函數，全部可單測）
  cycle.py     港澳門檻、判定軌跡、臨界情境
  capm.py      CAPM + 費雪實質化（1.x 相容層）
  engine.py    編排：build_bundle → compute；ERP 歸因；警戒檢查
  diagnosis.py 自動診斷文字
  history.py   JSONL 快照庫（回測）
  report.py / cli.py / gui.py / excel_export.py
tests/test_macro.py          46 個測試／180 斷言，全離線
```

## 9. 方法論限制（請連同結果一起讀）

- ERP 基準、週期溢價、利差矩陣、自然失業率等是**方法論假設**，可配置但非官方數字。
- 週期門檻是啟發式規則，目的是讓調整有紀律、可覆核，不是計量估計。
- 澳門無本地長債，rf 沿用港元（聯繫匯率）；澳門 GDP 缺口在歷史序列不足時不可用，
  引擎會明示而非猜測。
- 名義折名義現金流、實質折實質現金流，不可混用。
- HIBOR 為推導值（標 `derived`）時僅供流動性方向判斷，精確定價請手動覆寫。

## 10. 測試

```bash
python tests/test_macro.py     # 46 個測試、180 個斷言，全部離線執行
```

涵蓋：設定往返/雜湊/驗證、HP 濾波與季節調整、同比鏈接防回歸（不得連乘爆增）、
泰勒訊號、信用/流動性/隱含 ERP/波動率/Altman/PPP、風險分與權重重映射、
WACC 組成、DCF g 上限與傳導、標準 NPV 隔離、ERP 歸因合計、快照庫往返、
Excel 匯出冒煙、以及合成數據的端到端 compute（含情境隔離與壞設定拒絕）。

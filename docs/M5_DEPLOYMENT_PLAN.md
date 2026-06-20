# M5 — 部署計畫：benchmark（單資產 0050）→ 6 資產 Asset Allocator（M0+M1+M2）

> **狀態：Phase A 建置完成、gate 通過（2026-06-19c，agent workflow `wo9hofr8d`／11 agents）。建置全程 additive、mode-gated → live 執行路徑仍 benchmark（0050+MA200）逐位不變**（`pytest` 323 綠、既有 105 行為中性、cross-val max|Δ|=0、`strategy.mode` 仍 benchmark、帳本未碰；對抗 review 抓到 2 個 must-fix 皆已修補測，見 §12）；切到 `mode: allocator` + 帳戶遷移是 paper 跑 ≥十幾天後的**另一步、由使用者觸發**。本檔是「怎麼把 §3.7 拍板定案的 M0+M1+M2 從 returns-based 研究沙盒落到 live paper 引擎」的逐步 playbook + **§11 凍結建置 spec（單一介面真相）**。
>
> 規格真相＝`MULTI_ASSET_UPGRADE_PLAN.md` §3.7（2026-06-19b 使用者最終拍板定案）＋ `tw_rebalancing_rules_2026_07.md`（M0 全文）。建立 2026-06-19b。

---

## 0. 鐵律（本計畫全程遵守）

1. **additive**：所有新碼掛在 `strategy.mode: allocator` 之後；`mode: benchmark` 時系統**逐位不變**（現行 105 測試全綠、行為 max|Δ|=0）。
2. **分階段 Gate**：建置 → 影子跑（不下單）→ paper 實跑（小步）；每階段有明確過關準則 + 使用者拍板。
3. **rollback 永遠可用**：`strategy.mode` 回 `benchmark` → `make_engine()` fail-safe → 回現行 0050+MA200。
4. **live＝paper（無真錢）**：本計畫止於 paper-trading。真錢／Shioaji 實單是**日後另一個獨立決策**，不在 M5 範圍。
5. **不打 API 做回測**；live 取數遵守 FinMind/來源限流。survivorship + 主動<1yr 未經空頭 → 一切預期帶上界 caveat。

---

## 1. 現況 → 目標差距（依架構測繪）

| 面向 | 現況（live） | 目標（M5 後） |
|---|---|---|
| 標的 | 單一 0050 | 6 資產：0050 / 00981A / 00991A / 00635U / 00864B / 永豐MMF |
| 引擎輸出 | 標量曝險（`current_target_exposure`→`decide_rebalance`） | 6 標的目標權重向量 → 6 筆有序訂單 |
| 配置決策 | vol-target + MA200 overlay | M0 不對稱帶寬 + M1 股票腿 de-risk + M2 現金 tilt |
| 再平衡 | 月初 + 5pp drift band（單檔） | 月初 + regime/usd 變動觸發（組合級，含優先序/地板） |
| 巨集資料 | 無 | live 取 US CPI+Fed（M2） |

**可直接重用（免改）**：`PaperBroker`（`data/processed/paper_account.json`）、`PositionManager`（`positions.json`）、`OrderManager.enter/exit`、`RiskGuard`、`Notifier`、config loader（`src/utils/helpers.py::load_settings`）、`RebalanceAction`（`src/strategy_engines/base.py`）、**`_regime_below` / `is_month_first_trading_day`**（`benchmark_engine.py`，M1 骨幹直接複用）。執行層 + 記帳本**已是多標的 dict**，6 檔不需改。

**需改造**：`BenchmarkEngine`（單檔 → 多檔）、`main.py` rebalance task（單檔 fetch+1 次 decide → 多檔 + macro + 訂單迴圈）、`src/data/fetcher.py`（多標的並行取數）、config schema。

**淨新建**：① Allocator 引擎（M0/M1/M2 → 目標權重）；② 現金感知 Rebalance 規劃器（先賣後買、優先序、lot、現金約束）；③ Macro monitor（CPI/Fed live 取數）；④ 多資產測試組。

**⚠️ 最關鍵翻譯落差**：研究沙盒（`full_book_backtest.py`）是 **returns-based 月度權重** 模擬；live 必須是 **持股級、日排程、整數 lot、現金約束** 的真實下單。M0/M1/M2 的**決策邏輯**可移植，但「權重→股數→有序訂單」這段是 live 才有的新工程（見 §4.2）。

---

## 2. 標的與資料落差盤點（先驗證、後動工）

- **0050 / 00981A / 00991A / 00635U / 00864B**：皆 **TWSE 上市、TWD 交易**。00635U（黃金期貨型）、00864B（美債）的 **USD 曝險在 ETF NAV 內部，下單與報價皆 TWD** → **不需 FX feed、不需貨幣轉換**（更正架構測繪的 FX 顧慮）。走現有 `PaperBroker` + `fetcher` 路徑即可。
- **永豐 MMF**：**非交易所標的**（基金申購/贖回，真實有 T+1/2 結算）。live paper **以合成 cash 等價 sleeve 模型**處理：一個 pseudo-symbol `MMF`，NAV 從 1.0 起、日 accrual ~1.5%/yr、零手續費、即時申贖。記帳併入 `PositionManager`，但不經 broker 真實掛單。→ 決策點 §10(e)。
- **行情覆蓋（架構已確認 2026-06-19c）**：`FugleFetcher.get_realtime_quote(sym, odd=True)` **已支援盤中零股報價（`type=oddlot`、~5 秒撮合）**；`odd_lot_fill.py`（`parse_odd_ladder` / `odd_lot_buy_fill` book-walk 部分成交）**已具零股成交模型** → allocator 路徑直接複用（滿足 §10b 硬要求）。`get_candles` 為歷史 K（多標的需並行擴充）。**仍須 spike 驗證**：5 檔 ETF 的 K 線 + 零股報價實際可取、**00981A/00991A（<1yr、量能小）零股深度/可成交性**（Phase A 動工時順帶驗）。
- **M2 巨集（淨新）**：需 live 取 **US CPI（CPIAUCSL）+ Fed Funds（FEDFUNDS）**，目前只有研究快取 CSV（`data/raw/macro/`）。→ 新 `MacroMonitor`（FRED 月級、**發布落後 shift**、雙確認、失敗 fallback last-known、嚴禁 look-ahead）。

---

## 3. Config schema 變更（`config/settings.yaml`，additive）

新增 `strategy.mode: "allocator"` 為可選值（**預設維持 `benchmark`**），並新增 `allocator:` 區塊。草案：

```yaml
strategy:
  mode: "benchmark"          # benchmark（現行）| allocator（M5 目標）；預設不變
  allocator:
    enabled_layers: ["M0", "M1"]   # M2 預設不開（見 §5 分階段）；全開＝["M0","M1","M2"]
    assets:                         # 目標權重（對齊 §3.7 / tw_rebalancing_rules）
      "0050":   {target: 0.35, band_lower: 0.31,  band_upper: 0.42}
      "00981A": {target: 0.16, band_lower: 0.13,  band_upper: 0.23}   # 上界 +7%（2026-06-19b）
      "00991A": {target: 0.16, band_lower: 0.125, band_upper: 0.23}
      "00635U": {target: 0.10, band_lower: 0.08,  band_upper: 0.15}
      "00864B": {target: 0.115, band_lower: 0.10, band_upper: 0.15}
      "MMF":    {target: 0.115, band_lower: 0.095, band_upper: 0.145}
    sell_priority: ["00991A", "00981A", "00635U", "0050"]
    buy_priority:  ["0050", "00981A", "00991A", "00635U"]
    funding_priority: ["MMF_excess", "MMF_normal", "00864B_excess", "other_sells"]
    sell_fraction: 0.60        # 超過 target 賣 60%（留強勢續跑）
    hard_floor: {MMF: 0.095, "00864B": 0.10}
    equity_sleeve: ["0050", "00981A", "00991A"]
    M1:                        # 股票下行 de-risk（複用 _regime_below）
      signal_symbol: "0050"
      ma: 200
      confirm_days: 3
      band_pct: 0.01
      derisk_action: 0.75      # ON → 股票 sleeve ×0.75（flat）
      suspend_equity_dip_buy: true
      freed_to: {MMF: 0.667, "00635U": 0.333}   # 釋出資金去向；黃金上限 band_upper 15%
    M2:                        # 美元 tilt（只動現金）
      enabled: false           # 先關；macro feed 驗證後再開
      cpi_series: "CPIAUCSL"
      fed_series: "FEDFUNDS"
      lookback_months: 3
      confirm_months: 2
      publish_lag_months: 2
      magnitude_pp: 0.05
      scope: ["00864B", "MMF"]   # 只在現金腿互換
    rebalance:
      monthly_first_day: true
      on_regime_change: true
      on_usd_change: true
    mmf_annual_yield: 0.015
    transaction_cost_oneway: 0.002
```

對齊原則：此區塊**逐項對應 §3.7 規格 + tw_rebalancing_rules**；任一改動兩邊同步（單一真相）。

---

## 4. 工程模組（淨新 + 改造）

### 4.1 `AllocatorEngine`（新 `src/strategy_engines/allocator_engine.py`）
- 介面對齊 `base.StrategyEngine`；複用 `_regime_below`（M1）、`is_month_first_trading_day`。
- 輸入：6 標的近 ~320 日價格（MMF 為合成 NAV）、當前持股、現金、macro state。
- 邏輯：移植 `full_book_backtest.target_weights()` 的 **M0 帶寬 / M1（股票腿 ×0.75 + 暫停買跌）/ M2（現金 ±5pp tilt、受地板 clip）**，輸出 **6 個目標權重**（非標量）。
- 輸出：`dict[symbol → target_weight]`（純計算，不下單）。
- `make_engine()` 擴充：`mode == "allocator"` → `AllocatorEngine`；否則 `BenchmarkEngine`（fail-safe **不變**）。

### 4.2 `PortfolioRebalancer`（新 `src/execution/portfolio_rebalancer.py`）★ 最關鍵新工程
- 輸入：目標權重 + 當前持股 + 現金 + 即時價 + lot 規則 + 帶寬（只在出帶才動）。
- 步驟：① 算 target 市值/股數；② 套帶寬（帶內持有、出上界賣 60%、破下界買回 target）；③ 依 **賣序→買序、資金序** 排序；④ **先賣後買**釋放現金；⑤ 整數 lot（零股）、cash 約束（不可超買）、硬地板保護。
- 輸出：**有序 `RebalanceAction` list**（餵 `OrderManager` 迴圈）。
- 防雷：解決架構測繪點名的「PaperBroker 每單原子、現金中途用罄則 cascade 失敗」——規劃器先全域算清現金流再下單。

### 4.3 `MacroMonitor`（新 `src/data/macro_fetcher.py`，M2 用）
- FRED 月抓 CPI/Fed → YoY 近3月變化 + Fed 近3月變化 → 雙確認（連2月）+ **發布落後**（防 look-ahead）→ `usd_regime ∈ {-1,0,+1}`。
- 快取 + 取數失敗 → fallback last-known state（不可因抓不到而誤觸發）。
- M2 `enabled: false` 時完全不啟用。

### 4.4 `fetcher` 擴充
- `get_candles` / `get_realtime_quote` 多標的並行（ThreadPool）；MMF 走合成 NAV（不打行情）。

### 4.5 `main.py` rebalance task 改造（additive）
- `mode == "allocator"`：多標的 fetch + macro → `AllocatorEngine` 算目標權重 → `PortfolioRebalancer` 出訂單集 → `OrderManager` 迴圈執行（先賣後買）→ 更新 `PositionManager`/notify。
- `mode == "benchmark"`：**走原路徑、逐位不變**。pre_market/post_market 任務對應擴充（多標的曝險播報 / 組合級日結）。

---

## 5. 分階段上線 + 每階段 Gate

| Phase | 內容 | 過關 Gate | live 動到？ |
|---|---|---|---|
| **A. 建置 + 行為中性**（✅ 完成 2026-06-19c） | 寫 §11 全模組 + config + 測試（§8）；**M2 一併建好**（`enabled: false` 預設） | ① `mode=benchmark` 既有 **105 測試逐位綠**；② 新多資產測試綠；③ **交叉驗證**：allocator 引擎在歷史快取上重現 `full_book_backtest` 的權重軌跡（容差內）＝ live 引擎 ≡ 研究沙盒；④ 對抗 review 無 look-ahead/mode-gating 洩漏/現金 cascade/地板違反 → **全達成**（pytest 323 綠、cross-val max\|Δ\|=0、2 must-fix 已修補測，見 §12） | 否（仍 benchmark） |
| ~~B. 影子跑~~ | **已移除**（§10b 使用者選直接 paper） | — | — |
| **C. paper 實跑** | **歸零重建帳戶（§6 選項 i）** → `mode: allocator` → 真在 paper account 下單（**Fugle 零股 ~5 秒撮合價**）。先 M0+M1，macro feed 驗證後再開 M2 | 跑 **≥十幾天**（§10d）；paper 曲線與預期一致、無執行 bug、DD/周轉/地板/優先序如實、regime/macro state 正確 | **是（paper）** |
| **D. 真錢/Shioaji** | 帳戶+API key 已申請；**本計畫僅文件化、先不實做**（§10d、paper ≥十幾天後另議） | 另開決策 | — |

**M2 上線時點**：本次 Phase A **把 M2 一併建好**（§10a），但 config 預設 `M2.enabled: false`；Phase C 先跑 **M0+M1**，待 `MacroMonitor` live feed（FRED）穩定驗證後於 paper 階段單獨開啟。理由：M2 邊際（δ 內、僅 +0.6pp DD），且 live macro 是**最大新外部依賴**，風險/報酬不對稱。

---

## 6. paper account 遷移（Phase C 前執行）

- 現況 `paper_account.json` 可能持有 benchmark 的 0050 部位（CLAUDE.md 提到的孤兒倉）。
- 步驟：停 `main.py` → **備份** `paper_account.json` + `positions.json` → 重建 → 重啟。
- **使用者已選 (i) 歸零重建（§10c，最乾淨）**：賣出 0050 → 全現金 → 依 6 標的目標權重一次建倉。〔(ii) 保留 0050 補建＝已否決。〕
- `conftest.py` 測試自清狀態檔，不受影響。

---

## 7. Rollback

- **任一階段**：`strategy.mode` 回 `benchmark` → `make_engine()` fail-safe → 現行 0050+MA200。新 allocator 碼 additive、不影響 benchmark 路徑。
- 若已進 Phase C（帳戶已轉 6 資產）：rollback 需**手動把組合賣回 0050**（或接受持有 ETF 至手動處理）；備份 json 可還原帳務基準。

---

## 8. 測試計畫（隨 Phase A）

- `test_allocator_engine.py`：M0 帶寬 / M1（股票腿 ×0.75 + 暫停買跌）/ M2（現金 tilt、地板 clip）；**退化測試：layers 關閉 ≡ 對應行為**。
- `test_portfolio_rebalancer.py`：現金約束、先賣後買、賣/買/資金優先序、整數 lot、硬地板、cascade 不爆。
- `test_macro_monitor.py`：雙確認、發布落後、**無 look-ahead**、抓取失敗 fallback。
- `test_allocator_vs_sandbox.py`：live 引擎在快取上權重軌跡 ≡ `full_book_backtest`（容差內）＝研究/live 一致性。
- **行為中性**：`mode=benchmark` 時既有測試逐位不變（守鐵律 #1）。

---

## 9. 風險與未知（依架構測繪、已更正）

1. **多資產現金排序**：先賣後買 planner（§4.2）解；PaperBroker 原子單 → 必須全域先算現金流。
2. **MMF 合成模型**：真實申贖有結算延遲，paper 簡化為即時零費 → 與真錢落差（決策點 §10e）。
3. **00981A/00991A 流動性/零股可成交性**：<1yr、量能小 → 動工前 spike 驗證行情與成交。
4. **live macro feed（M2）**：FRED 發布時點、抓取失敗 fallback、嚴防 look-ahead；M2 邊際 → 建議最後上。
5. **主動 ETF <1yr 未經空頭**：de-risk 閾值在 0050-proxy 上校準 → **post-deploy 必須 OOS 監看**，真實空頭行為可能逼出不同參數。
6. **regime 月中觸發 whipsaw**：E1+E2（連3日+1%帶）已緩；live 需確認觸發頻率不過密。
7. **config 漂移**：allocator 區塊與 §3.7/tw_rebalancing_rules 必須單一真相對齊。
8. ~~USD/TWD FX feed~~：**不需要**（00635U/00864B 為 TWSE TWD 交易，FX 在 NAV 內）。

---

## 10. 決策點 — 使用者已拍板（2026-06-19c）

- **(a) M2 時點**：**建置納入 M2**（跑 paper 前做好即可）；上線可 toggle（`allocator.M2.enabled`），macro feed 驗證前可暫 `false`，驗證後於 paper 階段開啟。
- **(b) 影子跑**：**不跑影子、直接 paper**。硬要求：**用 Fugle API 抓盤中零股每 ~5 秒撮合成交價**（`get_realtime_quote(sym, odd=True)` + `odd_lot_fill` book-walk，infra 已具——見 §2、§11.5）。（保留 Phase A 的**行為中性 + 沙盒交叉驗證「正確性 Gate」**——那不是影子、是回歸驗證，未被豁免。）
- **(c) paper 遷移**：**歸零重建（乾淨）**——停 main → 備份 → 賣 0050 → 全現金 → 依 6 標的目標權重一次建倉。
- **(d) 真錢/Shioaji**：帳戶 + API key 已申請。**寫進計畫（Phase D 文件化）但先不實做**——paper 至少跑十幾天看效果後才另議。
- **(e) MMF**：**paper 階段合成 cash 等價 sleeve**（pseudo-symbol `MMF`、NAV 日 accrual 1.5%/yr、零費即時、**不經 broker**；見 §11.6）。

> 已拍板 → 進建置（§11 凍結 spec）。建置 additive、mode-gated，**live 執行仍 benchmark 不變**。

---

## 11. 凍結建置 Spec（2026-06-19c）— agent workflow 一律逐字遵守

> 這是 Phase A 建置的**單一介面真相**。每個 build agent 讀本節 + 指名的既有檔案，**完全照簽名/契約實作、不得自創介面**。決策邏輯的權威來源＝`notebooks/regime_tilt/full_book_backtest.py::target_weights()`（行 126–162）＋ `tw_rebalancing_rules_2026_07.md`（M0 全文）＋ §3.7（凍結參數）＋本檔 §3（config schema）。

### 11.0 建置鐵律（不可違反）
1. **additive / mode-gated**：所有新行為掛 `strategy.mode == "allocator"` 之後。`mode == "benchmark"` 路徑**逐位不變**。
2. **不得改 `strategy.mode`**（settings.yaml 維持 `benchmark`）；**不得碰** `data/processed/paper_account.json`、`positions.json`（執行期帳本）；**不得 `git commit` / `git push`**（鐵則#6）。
3. **測試/建置期不打外部 API**：`MacroMonitor` 的 FRED 抓取、`FugleFetcher` 的線上呼叫，在測試中一律 **mock 或讀快取**（`data/raw/macro/*.csv`）。鐵則#4。
4. **行為中性 Gate**：完成後 `pytest` 既有測試（含 `tests/test_benchmark_engine.py`、`test_paper_broker.py`、`test_odd_lot_fill.py` …，全綠基線 105）**逐位不變**；新測試另計。
5. **config 對齊**：`allocator` 區塊參數逐項對應 §3.7 / `tw_rebalancing_rules` / `full_book_backtest`（TARGET/BANDS/A_DERISK=0.75/SELL_FRAC=0.60）；交叉驗證測試（§11.8）以 `import full_book_backtest` 斷言一致 → 數字不得 drift。

### 11.1 檔案清單
**淨新建：**
- `src/strategy_engines/allocator_engine.py` — `AllocatorEngine`（M0/M1/M2 → 6 目標權重；pure 計算）。
- `src/execution/portfolio_rebalancer.py` — `PortfolioRebalancer`（目標權重 → 有序零股訂單；現金感知）。★ 最關鍵新工程
- `src/data/macro_fetcher.py` — `MacroMonitor`（M2：FRED CPI/Fed → `usd_regime ∈ {-1,0,+1}`，causal）。
- `src/execution/mmf_sleeve.py` — `SyntheticMMF`（合成 cash 等價 sleeve，不經 broker）。
- `tests/test_allocator_engine.py`、`tests/test_portfolio_rebalancer.py`、`tests/test_macro_monitor.py`、`tests/test_mmf_sleeve.py`、`tests/test_allocator_vs_sandbox.py`。

**改造（additive、mode-gated；既有簽名不得破壞）：**
- `src/strategy_engines/benchmark_engine.py`：`make_engine()` 增 `mode=="allocator"` → `AllocatorEngine`（其餘 fail-safe **不變**）。**`_regime_below` / `vol_target_exposure` / `is_month_first_trading_day` 不得改**（M1 直接 import 複用）。
- `src/data/fetcher.py`：`FugleFetcher` **新增** 多標的並行 helper（如 `get_candles_multi(symbols, start)`）+ 零股報價便利包裝；**既有 `get_realtime_quote` / `get_candles` 簽名不動**。
- `main.py`：新增 allocator 任務（§11.7），`mode=="benchmark"` 排程**原封不動**。
- `config/settings.yaml`：新增 `strategy.allocator` 區塊（§3 草案，**M2.enabled: false 預設**）；**`strategy.mode` 維持 `benchmark`**。

### 11.2 決策邏輯（權威＝`full_book_backtest.target_weights()`）— 凍結參數
- `TARGET = {0050:.35, 00981A:.16, 00991A:.16, 00635U:.10, 00864B:.115, MMF:.115}`；`EQUITY=[0050,00981A,00991A]`。
- `BANDS`（lower,upper）：`0050(.31,.42) / 00981A(.13,.23) / 00991A(.125,.23) / 00635U(.08,.15) / 00864B(.10,.15) / MMF(.095,.145)`。
- **M0**（regime full）：逐非-MMF 腿 `cur>upper → cur−0.60·(cur−target)`（賣 60% 超額）；`cur<lower → target`（買回）；帶內 → 持有。`MMF = max(1−Σ非MMF, .095)`。
- **M1**（`regime_on` ON）：股票腿 flat `target×0.75`；freed 釋出 = Σ(target−new)；`黃金 = min(.10+freed/3, .15)`、`MMF = .115 + freed·2/3 + 黃金溢出`；00864B 不變。（M1 ON 時**不套 M0 帶寬**，直接從 TARGET flat-cut。）
- **M2**（`usd≠0`，只動現金、受地板 clip）：弱(−1) `shift=clip(.05, 00864B−.10, .145−MMF)`、00864B−=shift/MMF+=shift；強(+1) 反向（00864B 上限 .15 / MMF 地板 .095）。
- 末步：全權重正規化 `tw[k]/Σtw`。
- `regime_on`：0050 收盤 MA200、`_regime_below(confirm_days=3, band_pct=.01)`、**act T+1（shift 1）**＝複用 live `_regime_below`。
- `usd_regime`：見 §11.4。

### 11.3 `AllocatorEngine`
- `mode = "allocator"`；`__init__(cfg=None)` 讀 `settings.yaml strategy.allocator`（缺值安全預設）。
- `target_weights(drift_weights: dict[str,float], regime_on: bool, usd_regime: float) -> dict[str,float]`：移植 §11.2 邏輯，輸出 6 標的權重（和為 1）。**純計算、無 I/O。**
- `compute_regime_on(closes_0050: pd.Series) -> bool`：用 `_regime_below(..., confirm_days, band_pct)` 末日值 + T+1 語意（與 sandbox 一致）。
- `make_engine()`：`mode=="allocator"` → `AllocatorEngine()`。
- **交叉驗證契約**：對任一 drift/on/usd，`AllocatorEngine.target_weights == full_book_backtest.target_weights(..., use_m1=True, use_m2=cfg)`（容差 1e-9）。

### 11.4 `MacroMonitor`（M2）
- `usd_regime(asof: date) -> float ∈ {-1,0,+1}`：移植 §full_book_backtest 行 111–122——CPI YoY 近3月變化 + Fed 近3月變化 → 雙確認（連2月）→ **發布落後 shift(2)** → ffill。**causal，嚴禁 look-ahead**（只用 `asof` 前已發布資料）。
- 線上抓 FRED `CPIAUCSL`/`FEDFUNDS`（月級）+ 磁碟快取；**抓取失敗 → fallback last-known state**（不可因抓不到而誤觸發/翻轉）。
- `enabled=false`（config）時完全短路、回 0。測試一律餵快取 CSV、不打網。

### 11.5 `PortfolioRebalancer` ★（live 才有的新工程）
- `plan(target_weights, holdings, cash, mmf_value, quotes, *, bands, lot_rules) -> list[RebalanceAction]`。
- 步驟：① 總權益 = cash + Σ持倉市值 + mmf_value；② 目標市值 = 權益×權重；③ **帶寬閘**（只在出帶才動：出上界賣、破下界買回 target、帶內不動——與 §11.2 M0 同口徑；M1/M2 已在權重內）；④ 目標市值 → **整數零股股數**（`lot_size()`，零股=1 股粒度）；⑤ 排序：**賣序 `[00991A,00981A,00635U,0050]` → 買序 `[0050,00981A,00991A,00635U]`**；⑥ **先賣後買**：先全域算清現金流（避免 PaperBroker 原子單中途現金用罄 cascade 失敗）、賣出釋金後才買；⑦ **硬地板**：MMF≥.095、00864B≥.10 不得破；⑧ 現金約束（不融資、含手續費 `calc_trade_cost`）。
- **零股成交價（§10b 硬要求）**：用 `fugle.get_realtime_quote(sym, odd=True)` 取盤中零股簿 → `odd_lot_fill.parse_odd_ladder` + `odd_lot_buy_fill`（book-walk 部分成交）；無簿 fallback。買用賣方階梯、賣用買方最佳價。
- **MMF 不出 `RebalanceAction`**：經 `SyntheticMMF`（§11.6）以 cash↔MMF 轉移實現（buy 序末、sell 序末當資金緩衝）。
- 輸出餵 `OrderManager.enter/exit` 迴圈（main.py）。

### 11.6 `SyntheticMMF`（§10e）
- pseudo-symbol `"MMF"`；狀態持久化於 `data/processed/mmf_sleeve.json`（`{units, nav, last_accrual_date}`），**不經 PaperBroker / 不發 place_order**。
- NAV 起始 1.0；`accrue(asof)`：日 accrual `(1+0.015)**(1/252)-1`（交易日計）。
- `value() = units×nav`；`deposit(twd)`：cash→MMF（units += twd/nav）；`withdraw(twd)`：MMF→cash（即時、零費）。
- 計入總權益與權重；歸零重建時依目標權重 11.5% 初始化。

### 11.7 `main.py` allocator 任務（additive）
- 啟動：`mode=="allocator"` 時排 `allocator_pre_market_task` / `allocator_rebalance_task` / 沿用 `post_market_task`（多標的播報）；`mode=="benchmark"` 排程**原封不動**。
- `allocator_rebalance_task`（開盤後）：①`SyntheticMMF.accrue`；②多標的 fetch（`get_candles_multi` 算 0050 MA200/regime_on、各腿即時零股報價）；③`MacroMonitor.usd_regime`（M2 開時）；④`AllocatorEngine.target_weights`；⑤**觸發判定**＝當月首交易日 OR regime_on 變 OR usd 變（與 sandbox 同）；⑥`PortfolioRebalancer.plan` → `OrderManager` 迴圈（先賣後買）+ `SyntheticMMF` 轉移 → `PositionManager` 記帳 + notify。
- 沿用既有：`broker`/`position_mgr`/`notifier`/`fugle`/`RiskGuard`/`_reconcile_positions`/HALT 旗標/T+1 防呆。

### 11.8 測試 + Gate
- `test_allocator_engine`：M0 帶寬三分支 / M1（股票×0.75 + freed→MMF·2/3+gold·1/3 + gold cap 溢出）/ M2（雙向 tilt、地板 clip）/ 正規化；**退化**：對應 layer 關閉 ≡ 該行為。
- `test_allocator_vs_sandbox`：`import full_book_backtest`，隨機 drift/on/usd 下 `AllocatorEngine.target_weights ≡ fbb.target_weights`（1e-9）＝研究/live 一致。
- `test_portfolio_rebalancer`：現金約束、先賣後買、賣/買優先序、整數零股、硬地板、cascade 不爆、零股 book-walk 成交價。
- `test_macro_monitor`：雙確認、發布落後 shift(2)、**無 look-ahead**、抓取失敗 fallback、enabled=false 短路（餵快取、不打網）。
- `test_mmf_sleeve`：accrual、deposit/withdraw round-trip、value、不經 broker。
- **行為中性**：`mode=benchmark` 既有 105 測試逐位綠。
- **Gate（全綠才算 Phase A 完成）**：上述全綠 + 交叉驗證一致 + 對抗 review（look-ahead / mode-gating 洩漏 / 現金 cascade / 地板違反 / config drift）無 must-fix。

---

## 12. Phase A 建置結果 + Phase C 上線前檢查清單（2026-06-19c）

**Phase A ＝完成、gate 通過**（agent workflow `wo9hofr8d`，11 agents）：
- 新建 `src/strategy_engines/allocator_engine.py` / `src/execution/portfolio_rebalancer.py` / `src/data/macro_fetcher.py` / `src/execution/mmf_sleeve.py` + 6 測試檔（`test_allocator_engine` / `_vs_sandbox` / `_macro_monitor` / `_mmf_sleeve` / `_portfolio_rebalancer` / `_allocator_order_loop`）；改造 `make_engine()`（mode-gated 分支）/ `main.py`（allocator 盤前+再平衡任務、3 段下單迴圈）/ `fetcher.py`（`get_candles_multi`/`get_odd_quotes_multi`）/ `paper_broker.py`（`adjust_cash`）。
- **Gate 全綠（獨立複核一致）**：`pytest` **323 passed**；行為中性（既有 **105 逐位綠**、benchmark 路徑不變、`make_engine` mode=="benchmark" byte-identical）；交叉驗證 `AllocatorEngine.target_weights ≡ full_book_backtest.target_weights`（145 斷言 + 獨立 20k，**max\|Δ\|=0**）；`strategy.mode` 仍 **benchmark**；執行帳本未碰。
- **對抗 review 抓到 2 個 must-fix（皆在歸零重建路徑）並已修+補測**：
  ① **MMF cash↔sleeve 不守恆** — `deposit/withdraw` 未動 broker 現金 → 權益雙重計/憑空生滅 + `insufficient_cash`。修：`PaperBroker.adjust_cash(delta)`（不透支 clip）+ main.py 把 MMF 轉移與現金腿做成原子 + 守恆測試。
  ② **T+1 賣單跳過餓死同日買單** — 歸零重建首日全 `hold_days=0`、賣單全跳過卻照排買單 → `insufficient_cash` cascade + 每筆燒 3×60s sleep。修：下單迴圈拆 3 段（賣→MMF提領→買），買單以 `broker.get_balance()` 實際現金為硬閘縮量 + 測試（patch `time.sleep`，任何重試即 fail）。

**Phase C 上線前待清（should-fix + spike；非 gate-blocking、live 仍 benchmark）：**
1. **[should-fix] 盤中 regime 用「完整收盤」（T+1 紀律）**：`main.py::_alloc_fetch_closes` 未限 `end_date` → 09:12 盤中 Fugle 歷史K 若含今日未完成 bar，會污染 MA200/`regime_on` 且偏離 sandbox `shift(1)`。修：regime 計算前剔除「日期≥今日」bar（**僅 allocator 路徑**）。⚠️ benchmark 現行 live 同型樣式 → 一併確認 Fugle 盤中是否回未完成 bar。
2. **[should-fix] planner/executor 報價分歧**：planner 用 book-walk vwap size 買單、迴圈逐筆重抓價；現金方向安全（不超買）但買單可能未成/縮量 → paper 階段觀察。
3. **[nit] 強化**：cross-val grid 補 M2 clip 邊界案例；`MacroMonitor.confirm_months` 非 2 時與 sandbox 分歧（預設＝2、僅文件化）；硬地板賣價用 best-bid（內部一致）。
4. **[spike] Phase C 動工驗**：Fugle 5 檔（尤其 00981A/00991A <1yr）K 線長度足 MA200 暖身 + 零股薄帳可成交；FRED live 端點真連一次（開 M2 前）；部署環境具 `apscheduler`/`fugle-marketdata`。
5. **遷移配套**：歸零重建時一併清 `data/processed/allocator_state.json`（runtime 觸發狀態，非凍結帳本）+ 確認 `SyntheticMMF` 建倉日起息語意（首次 accrue 設基準日、隔交易日起算）。

> Phase A 完成、**live 仍 benchmark 不變**。建議下一步＝清 should-fix #1（T+1 cap）+ nits 的短 hardening pass（過同一 verify gate）→ 再 Phase C（歸零重建[含清 `allocator_state.json`] + 切 `mode: allocator` 跑 paper、先 M0+M1），皆由使用者觸發。

---

## 12.1 should-fix #1/#2 已修 + spike 結果（2026-06-19c）

**should-fix #1/#2 已修 + 補測（`pytest` 326 綠、behavior-neutral 維持、cross-val 不動）：**
- **#1 T+1 完整收盤**：新增 `fetcher.completed_daily_closes(candles, today)`（剔除日期 ≥ today 的未完成 bar）；`main.py::_alloc_fetch_closes` 改用之 → regime/ref 一律用「昨日(含)前完整收盤」、對齊 sandbox `shift(1)` 與 `compute_regime_on` 契約。測試 `test_fetcher_adjust.py`（剔今日 bar / 空值）。
- **#2 planner/executor 報價一致**：`RebalancePlan` 新增 `fill_prices`（賣＝最佳買價、買＝book-walk vwap）；`plan()` 記錄、`main.py` 段1/段3 下單改用 `plan.fill_prices.get(sym)`（fallback `_alloc_*_px`）→ 消除「planner 多股 vwap vs executor 1 股重抓價」分歧；現金 re-gate（T+1 安全網）保留。測試 `test_portfolio_rebalancer.py::test_fill_prices_recorded_and_match_actions`。

**spike 結果（2 背景 agent，read-only、live-feed 驗證）：**
- 🟥 **BLOCKER — Fugle 免費層歷史 K 僅 ~22 bars**：`get_candles('0050', start=420d)` 伺服端硬截到 ~30 日（~22 bars），但 **MA200 regime 需 ≥202 bars**。`_alloc_fetch_closes`（allocator）與 `_benchmark_0050_closes`（**現行 benchmark live**）皆**只**從 `fugle.get_candles` 取 0050、無 FinMind/archive fallback → `compute_regime_on` 的 `rolling(200)` 全 NaN、guard `len<202` 每日失敗。**⇒ allocator regime 無法計算（Phase C 阻斷）；現行 live benchmark 的 MA200 防禦 overlay 幾乎確定也 silently inert（同一 call 同一截斷）。** #1 的 T+1 cap 正確但不足以解此（22−1 仍 <202）。
  - **✅ 已修（2026-06-19c，使用者拍板「FinMind + 一併修 benchmark」）**：新增 `main.py::_finmind_closes(sym, lookback)`（FinMind `get_daily_price(adjust=True)`、全史快取、過 `completed_daily_closes` T+1 cap）；**benchmark `_benchmark_0050_closes` 與 allocator 兩任務的 c0050 regime 史料全改走 FinMind**（Fugle 僅留即時零股報價＝成交價）。**端到端驗證（1 次 live FinMind call）**：0050 取得 **262 bars**、MA200 非 NaN（last 72.65）、benchmark overlay 於序列 **20 日曾觸發**（不再 silently inert）、`compute_regime_on(today)=False`（0050 107.3 ≫ MA200 → 滿倉，**部署不會即觸發砍倉**）。`pytest` 326 綠、mode 仍 benchmark、帳本未碰。**⚠️ benchmark live 行為已改（MA200 overlay 失效→生效），`main.py` 重啟才生效。** live quota：~2 FinMind call/日（價+除權息、磁碟快取、與背景 builder 共用配額但量微）。
- ✅ **FRED live（M2）PASS**：CPIAUCSL/FEDFUNDS 線上端點 200、格式符、與快取 max|Δ|=0；`usd_regime(today)=0`（中性）、causal、發布落後正確；`enabled=false` 短路。開 M2 無技術阻斷。
- ✅ **部署依賴 PASS**：權威 interpreter＝`.venv/bin/python`（3.11.15；launchd `deploy/macos/start_bot.sh` + systemd `deploy/trading-bot.service` 皆用它），9 依賴（含 apscheduler/fugle-marketdata）全在。`start.sh.save`＝stale 廢檔（錯 interpreter + 不存在路徑）建議刪。
- 🟡 **零股 live 深度＝DEFERRED**（spike 跑在週六休市）：端點/簿結構正確、symbol 全有效；Fri-18 快照＝0050/00981A 厚、00991A 中、00635U 薄、**00864B 極薄（L1 106 股、價差寬）**。下個交易日 09:10–13:30 須複驗小單可成交性（尤其 00864B/00635U）。

**⇒ 史料來源 BLOCKER 已解（FinMind、both paths、已驗證）。Phase C 剩餘 gating＝① 市場時段（下個交易日 09:10–13:30）零股深度複驗（尤其 00864B 106 股/00635U 薄）；② 歸零重建遷移（含清 `allocator_state.json`、刪 stale `start.sh.save`）；③ benchmark live MA200 修正已就緒、`main.py` 重啟即生效（不即觸發砍倉）。**

# E1+E2 正式 Walk-forward 驗證 + 整併入 live（whipsaw 修正落地）

> **產生方式**：承 `docs/E1_E3_COMPARISON.md`（E1-E3 in-sample 細網格）→ 本文把 E1（N 日確認）+ E2（對稱緩衝帶）升級成**正式 walk-forward OOS** 驗證，並把整併後的穩健配置落地到 live。
> **腳本**：`notebooks/e1e2_walkforward.py`（walk-forward）、`notebooks/e1e2_combined_validate.py`（整併候選落地前驗證）。純快取、0 API。
> **性質**：描述性、survivorship 上界。**定位＝現行 overlay 的「結構性降 whipsaw 微調」、非 alpha（R5 未翻案）。**
> **落地**：`config/settings.yaml` `strategy.benchmark.regime_confirm_days: 3`、`regime_band_pct: 0.01`；引擎 `benchmark_engine.py` additive（預設 1/0.0＝舊行為，行為中性）。日期 2026-06-18。

---

## 0. 一句話總結

- **walk-forward 確認**：E1、E2 對「降 whipsaw / 不惡化 DD / 不犧牲牛市」的改善是**前進窗穩健**（非僅 in-sample）——跨 4 個前進年（2022-25）都成立。
- **但無 alpha**：對**同 beta 的 0050**，OOS Sharpe 邊際 +0.04~0.05 ≪ δ=0.51、IRvs0050 還微負 → 無顯著超額（與 R5 一致）。
- **整併落地**：combined **N=3 + band=1.0%**（穩健高原值、非 in-sample 峰）。2022 假穿越 **7→1**、最差前進年 DD **−31.2→−30.5%**、交易 126→105、2018/2022 報酬+Sharpe 皆優於現行、2020 無 over-lag。
- **誠實框架**：這是把**已部署的防禦 overlay（R6）**做低風險、OOS-穩健的 whipsaw 改良，**不是**找到 alpha。0050 買持全期報酬仍最高。

---

## 1. ⚠️ 方法論修正：IRvs基準B 是 beta、不是 alpha

walk-forward 第一版用「IR vs 基準B」當 alpha 檢定 → 跑出 **+1.13**，會被誤讀成「找到 alpha」。**這是 beta 不是 alpha**：基準B（vol0.011）是 de-risked 低曝險，2023-25 牛市任何接近滿 beta 的策略都會海放它。鐵證：

| 策略 | OOS Sharpe | OOS年化 | 最差前進年DD | IRvs基準B* | **IRvs0050（真 alpha 檢定）** |
|---|---|---|---|---|---|
| current-live (MA200-85) | 0.995 | 20.2% | −31.2% | +1.13 | **−0.18** |
| walk-fwd E1 (Calmar·相對) | 0.996 | 20.2% | −31.1% | +1.13 | **−0.18** |
| walk-fwd E2 (Calmar·相對) | 0.985 | 20.0% | −30.8% | +1.10 | **−0.27** |
| 基準B (vol0.011) | 0.798 | 13.5% | −32.2% | 0 | −1.00 |
| **0050 買持** | 0.947 | 20.3% | −34.0% | **+1.00** | 0 |

> **`0050 買持自身的 IRvs基準B = +1.00`（純 beta、零技巧）** ＝ beta 參考線。walk-fwd 的 +1.13 ≈ 0050 的 +1.00 → 只是 beta。**真 alpha 檢定＝同 beta 的 IRvs0050 ＝ −0.18 / −0.27（負/零）**；OOS Sharpe 對 0050 的邊際（+0.04~0.05）遠在 δ=0.51 雜訊內。**結論：無顯著 alpha。** 此修正已寫回 `notebooks/e1e2_walkforward.py` Part B/D。

---

## 2. Walk-forward 方法（移植 r1_walkforward.py）

- **擴張窗**：每個前進年 Y∈{2022,23,24,25}，用 [2018-01-01, Y−1] 選參、套到 Y（嚴格 OOS）。
- **內層選參**：Calmar 優先（Sharpe tiebreak）；**DD floor 重錨「同族基線 current-live」− 2.2pp**（鐵則#8——基準B 是不同 vol 體制、錨它會 vacuous）；**永不 fallback 固定參數**。
- **主裁**：pooled OOS（FWD 日報酬串接）Sharpe / IRvs0050 / 最差前進年 DD；對照固定預先指定基準B + 0050。
- 退化點 sanity：E1(N=1) ≡ E2(band=0) ≡ 引擎 overlay 路徑（max|Δ|<1e-3 元）。

### 逐 fold 選參（誠實：選參「測不準」＝平滑高原徵兆）

| 規則 | 2022 | 2023 | 2024 | 2025 | 跨度 |
|---|---|---|---|---|---|
| E1 Calmar·相對 | N=2 | N=10 | N=4 | N=4 | 5 格/7（3 相異）|
| E1 Sharpe·相對 | N=2 | N=4 | N=4 | N=4 | 2 格/7 |
| E2（兩規則） | 3.50% | 3.50% | 3.50% | 3.50% | rail to edge（邊界）|

> E1 選參跳動、E2 一路頂到網格邊界 ＝ **平原太平、無真最佳值**（任何小 N / 任何帶 ≈ 等價）。**具體參數測不準，但效益（whipsaw↓、DD 守住、牛市不犧牲）跨 fold 穩健成立、與選哪個參數無關。** → 不可宣稱「N=x 最佳」；只能說「小 N / ~1-2% 帶 穩健降 whipsaw 且無下行」。

---

## 3. 2018 / 2022 stress 年焦點（whipsaw 重災年）

**2018＝in-sample chop；2020＝V 急崩（over-lag 檢查）；2022＝OOS 熊市+whipsaw。** 報酬 / Sharpe / DD / 態轉折 flips：

| 配置 | 2018 報酬/Sh/fl | 2020 報酬/DD/fl | 2022 報酬/Sh/DD/fl |
|---|---|---|---|
| 0050 買持 | −5.5% / −0.26 / — | 30.2% / −28.2% / — | −21.9% / −1.04 / −34.0% / — |
| 基準B | −7.8% / −0.45 / — | 21.6% / −24.9% / — | −24.1% / −1.46 / −32.2% / — |
| **current-live (N=1,band=0)** | **−7.8% / −0.45 / 11** | **27.8% / −27.0% / 4** | **−20.2% / −1.11 / −31.2% / 7** |
| **★ LIVE：combined N=3 + 1.0%** | **−6.9% / −0.38 / 5** | **26.9% / −27.3% / 2** | **−19.4% / −1.06 / −30.5% / 1** |
| combined N=4 + 1.25% | −6.1% / −0.32 / 3 | 26.8% / −27.0% / 2 | −19.4% / −1.05 / −30.5% / 1 |
| E1-only N=3 | −6.8% / −0.37 / 7 | 26.9% / −27.3% / 2 | −19.7% / −1.08 / −30.8% / 3 |

**讀法：**
- **2018**：current-live 因 whipsaw **輸給 0050**（−7.8% vs −5.5%）。整併後討回大半（−6.9%，flips 11→5，Sharpe −0.45→−0.38）。
- **2022（OOS）**：整併後**同時贏 current-live 與 0050**——報酬 −20.2→−19.4%（且優於 0050 −21.9%）、DD −31.2→−30.5%（且優於 0050 −34.0%）、flips 7→1、Sharpe −1.11→−1.06。
- **2020 V 急崩 over-lag 檢查**：整併後 2020 DD 維持 −27.3%（Δ −0.3pp vs current-live −27.0%）＝**雙重確認沒有 over-lag**（COVID 崩盤深且持續、輕易穿透 confirm+band、防禦完整保留）。

---

## 4. 整併候選落地前驗證（`e1e2_combined_validate.py`）

統一狀態機 `exp_combined(confirm_days, band_pct)`（generalises 兩者；(1,0.0)＝current-live byte-identical）＝預定加進引擎的邏輯。全候選對真實 0050 [2018-25]：

| 配置 | 全期 Sh | OOS Sh | 最差前進年DD | 2022 flips | 交易數 | 結構 Gate |
|---|---|---|---|---|---|---|
| current-live (1, 0) | 1.01 | 0.98 | −31.2% | 7 | 126 | （基線）|
| **★ N=3 + 1.0%（LIVE）** | 1.01 | 0.99 | **−30.5%** | **1** | 105 | **PASS** |
| N=4 + 1.25% | 1.02 | 0.99 | −30.5% | 1 | 100 | PASS |
| E1-only N=3 | 1.01 | 0.99 | −30.8% | 3 | 108 | PASS |
| N=2 + 0.5% | 1.02 | 0.99 | −31.1% | 3 | 108 | PASS |

**所有候選都過結構 Gate**（DD 不惡化且優於基準B/0050、whipsaw↓、牛市不犧牲、2020 不 over-lag）。差異全在 δ=0.51 雜訊內 → 選 **N=3 + 1.0%** 係穩健姿態（非 in-sample 峰）：N=3＝Alvarez SPY/QQQ 文獻甜蜜點 N=2-3、band 1%≈0050 一日移動 / SMA-envelope 慣例。**使用者拍板 combined N=3 + 1.0%。**

---

## 5. §5 Gate 裁決（walk-forward）

| Gate 條件 | E1 | E2 | 結果 |
|---|---|---|---|
| ① 對照固定基準B/0050 | ✓ | ✓ | 已算 |
| ② 降-DD 不惡化且優於兩被動（最差前進年DD）| ✓ −31.1% | ✓ −30.8% | 優於 live −31.2% / B −32.2% / 0050 −34.0% |
| ③ OOS Sharpe 不顯著差於 current-live（δ 帶內）| ✓ 0.996 | ✓ 0.985 | vs live 0.995 |
| ④ whipsaw 降低（2022 flips < 7）| ✓ | ✓ | 整併 7→1 |
| ⑤ 牛市不顯著犧牲（OOS 年化 vs live 20.2%）| ✓ 20.2% | ✓ 20.0% | — |
| ⑥ 選參穩定 / robustness | ⚠️ 跳動但效益穩 | ⚠️ rail to edge | 平滑高原、參數測不準但效益穩 |
| **⑦ 真 alpha（同 beta vs 0050）** | **✗ IRvs0050 −0.18** | **✗ −0.27** | **無（δ 內；R5 一致）** |

**▶ 裁決：結構 Gate PASS（whipsaw↓ / DD 不惡化 / 牛市不犧牲，OOS 跨 fold 穩健）；alpha Gate FAIL（無顯著超額）。**

---

## 6. 落地內容（live 變更）

- **引擎** `src/strategy_engines/benchmark_engine.py`：新增 `_regime_below(close, ma, confirm_days, band_pct)` 狀態機 helper；`vol_target_exposure` 新增 kwargs `regime_confirm_days=1, regime_band_pct=0.0`（**預設＝舊每日 MA 規則、行為中性**）；`_benchmark_cfg`/`__init__`/`exposure_series` 串接。
- **config** `config/settings.yaml`：`strategy.benchmark.regime_confirm_days: 3`、`regime_band_pct: 0.01`。
- **測試** `tests/test_benchmark_engine.py`：+7 測試（行為中性、N 日確認、緩衝帶、combined 遲滯、config 讀取）；全套 **105 passed**。
- **行為中性驗證**：預設 (1, 0.0) 對真實 0050 [2018-25] 與舊引擎 exposure **max|Δ| = 0**；新 config (3, 0.01) 與沙盒 `exp_combined` **max|Δ| = 0**。
- **main.py 不需改**（`current_target_exposure` 為 config 驅動；新參數自動生效）。
- **部署**：使用者重啟 `main.py` 後生效（與 R6 同；現有持倉受 5pp 帶/月度再平衡自然收斂）。

---

## 7. Caveats（誠實聲明）

1. **survivorship 上界**：FinMind 無下市股、0050 單一存續 ETF → 所有數字（DD 改善、whipsaw 降幅）皆為上界、偏樂觀。
2. **單一市場單期 power 有限**：OOS 僅 2022-25、一次 2022 熊市 + 一次 2018 chop；whipsaw 削減建立在少數離散 regime 轉換、未做 bootstrap 顯著性。
3. **無 alpha**：對同 beta 的 0050 無顯著超額（R5 未翻案）；定位嚴格為**結構性降 whipsaw/降回撤微調**、非 outperformer。0050 買持全期報酬仍最高。
4. **參數測不準**：walk-forward 選參跳動 / rail to edge ＝平滑高原；N=3/band=1% 係**穩健姿態值非資料最佳值**（鐵則#7：不挑 in-sample 峰）。
5. **這是 in-sample 全期細掃 + walk-forward 的綜合**；落地係把已部署防禦 overlay（R6）的 whipsaw 行為改良，**非新 alpha 策略部署**。

*建立 2026-06-18｜E1+E2 walk-forward 驗證 + combined N=3+1% 整併落地｜結構 Gate PASS、alpha FAIL。*

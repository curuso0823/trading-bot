# 00981A / 00991A 主動式 ETF 擬合代理模型

## 1. 模型形式

以 0050 為市場基準，主動式 ETF 報酬拆解為：

$$
r_{active,t}=\beta \cdot r_{0050,t}+\alpha_{daily}+\varepsilon_t
$$

其中：

$$
\alpha_{daily}=\frac{\alpha_{net,annual}}{252}
$$

$$
\alpha_{net,annual}=\alpha_{gross,annual}-fee_{annual}
$$

殘差風險：

$$
\varepsilon_t \sim (0,\sigma_{idio})
$$

若採 deterministic 回測，可不顯式加入 $\varepsilon_t$，但在風險統計中補上殘差波動。

---

## 2. 參數設定總表

| ETF | 定位 | $\beta$ vs 0050 | Gross Alpha | Fee Drag | Net Alpha | Idiosyncratic Vol | MaxDD 額外懲罰 |
|---|---|---:|---:|---:|---:|---:|---:|
| 00981A | 成長選股型 | 1.10 | +4.0% | -1.8% | +2.2% | 7.0% | -4.0pp |
| 00991A | 未來50增強型 | 1.05 | +2.5% | -1.5% | +1.0% | 5.0% | -2.5pp |

---

# 3. 00981A 模型

## 3.1 報酬模型

$$
r_{00981A,t}=1.10 \cdot r_{0050,t}+\frac{0.022}{252}+\varepsilon_{00981A,t}
$$

其中：

$$
\sigma_{idio,00981A}=7.0\%
$$

## 3.2 Deterministic 回測版本

$$
r_{00981A,t}=1.10 \cdot r_{0050,t}+\frac{0.022}{252}
$$

## 3.3 波動率調整

$$
\sigma_{00981A}=\sqrt{(1.10 \cdot \sigma_{0050})^2+0.07^2}
$$

## 3.4 最大回撤調整

$$
MaxDD_{00981A}=1.10 \cdot MaxDD_{0050}-0.04
$$

範例：

$$
MaxDD_{0050}=-30\% \Rightarrow MaxDD_{00981A}\approx -37\%
$$

---

# 4. 00991A 模型

## 4.1 報酬模型

$$
r_{00991A,t}=1.05 \cdot r_{0050,t}+\frac{0.010}{252}+\varepsilon_{00991A,t}
$$

其中：

$$
\sigma_{idio,00991A}=5.0\%
$$

## 4.2 Deterministic 回測版本

$$
r_{00991A,t}=1.05 \cdot r_{0050,t}+\frac{0.010}{252}
$$

## 4.3 波動率調整

$$
\sigma_{00991A}=\sqrt{(1.05 \cdot \sigma_{0050})^2+0.05^2}
$$

## 4.4 最大回撤調整

$$
MaxDD_{00991A}=1.05 \cdot MaxDD_{0050}-0.025
$$

範例：

$$
MaxDD_{0050}=-30\% \Rightarrow MaxDD_{00991A}\approx -34\%
$$

---

# 5. 回測實作摘要

## 00981A

```text
daily_return_00981A = 1.10 * daily_return_0050 + 0.022 / 252
vol_00981A = sqrt((1.10 * vol_0050)^2 + 0.07^2)
maxDD_00981A = 1.10 * maxDD_0050 - 0.04
```

## 00991A

```text
daily_return_00991A = 1.05 * daily_return_0050 + 0.010 / 252
vol_00991A = sqrt((1.05 * vol_0050)^2 + 0.05^2)
maxDD_00991A = 1.05 * maxDD_0050 - 0.025
```

---

# 6. 模型使用限制

- 此模型不是實際主動 ETF 績效預測。
- 此模型僅作為 00981A / 00991A 歷史資料不足時的代理回測假設。
- 模型已納入：市場 beta、主動 alpha、費用折減、殘差波動、回撤懲罰。
- 模型未完整捕捉：經理人換股風險、持股集中風險、alpha decay、流動性折溢價。

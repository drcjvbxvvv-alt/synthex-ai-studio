## [v2.0.0] - 2026-03-26

### 🚀 Project Brain v2.0 — 三大革命性子系統

本次大版本更新打破了單一專案的知識孤島，引入了真實世界的知識衰減機制，並賦予 AI 基於歷史圖譜的反事實推理能力。所有核心模組均以企業級安全標準進行深度強化。

#### 🌐 1. SharedRegistry 多專案知識共享 (`core/brain/v2/shared_registry.py`)

打破知識孤島，建立可見性受控的跨 Repo 知識庫（儲存於 `~/.brain_shared/registry.db`），避免相同踩坑在不同團隊間重複發生。

- **核心功能：** 支援透過 `brain share` 發布踩坑紀錄，並可指定可見性（如 `--visibility team`）；支援透過 `brain query-shared` 進行跨專案檢索。
- **安全與併發設計：**
  - **PII 自動過濾：** 透過正規表達式自動攔截並過濾密碼、API Key、IP、Email 與 URL。
  - **Namespace 防護：** 路徑注入防護，僅允許字母數字開頭。
  - **併發安全與效能：** 啟用 WAL 模式確保多專案讀寫不衝突；實作連線池復用（同進程不重複建立連線）。
  - **品質控制：** 具備冪等發布機制（相同內容 Hash 不重複儲存），且信心門檻低於 **0.7** 的知識不予分享。

#### 📉 2. DecayEngine 三維知識衰減 (`core/brain/v2/decay_engine.py`)

讓信心分數反映真實世界。從單一的時間衰減，升級為融合「時間」、「程式碼擾動 (Churn)」與「顯式失效」的三維複合衰減模型。

- **衰減公式：**
  $$c_{final}(t) = c_{time}(t) \times c_{churn} \times c_{explicit}$$
  $$c_{time}(t) = c_0 \times \exp(-\lambda_{eff} \times \text{days})$$
  $$\lambda_{eff} = \lambda_{base} \times (1 + \text{churn\_penalty})$$
  $$c_{churn} = 1 - (\text{churn\_score} \times 0.3)$$
  $$c_{explicit} = 0.05 \text{ (if invalidated)}$$
- **權重實作：** 踩坑記錄（$\lambda=0.001$）在一年後仍保有約 90% 信心；決策記錄（$\lambda=0.003$）一年後約剩 67%。當關聯程式碼頻繁變動時，信心將加速衰減。
- **CLI 支援：** 新增 `brain decay report`（衰減報告）、`update`（分析擾動）與 `invalidate`（顯式標記失效）指令。
- **安全與穩定性設計：** 實作 NaN/Inf 防護（浮點運算包裹於 `_safe_float()`）；信心邊界嚴格截斷於 $[0.001, 1.0]$；全面防護 SQL 注入；實作快取上限（超過 2,000 筆自動清空）與 Git 分析子進程 Timeout（最高 30 秒）。

#### 🔮 3. CounterfactualEngine 反事實推理 (`core/brain/v2/counterfactual.py`)

最具革命性的功能，基於知識圖譜中的決策歷史與踩坑紀錄，讓 AI 進行有根據的「如果不這樣做，會怎樣？」推理分析。

- **核心功能：** 支援技術債分析與架構複盤。透過 `brain counterfactual` 提問，系統會輸出包含「信心水準」、「最可能結果」、「可避免風險」、「新引入風險」及「推理依據」的結構化報告。
- **安全與成本控制：**
  - **Prompt Injection 防護：** 針對 `ignore`、`forget`、`override` 等惡意指令自動過濾為 `[filtered]`。
  - **邊界限制：** 問題長度限制 400 字元；API 輸出限制 `max_tokens=1500`。
  - **成本優化與容錯：** 採用 Claude Sonnet 模型；實作雙層快取（Memory + SQLite，1 小時 TTL）；當 API 不可用時自動降級為基於知識圖譜的規則分析；嚴格驗證 JSON 輸出格式防止系統崩潰。

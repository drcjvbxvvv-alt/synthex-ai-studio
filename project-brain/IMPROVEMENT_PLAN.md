# Project Brain — 改善規劃書

> **當前版本**：v0.4.0（2026-04-04）
> **文件用途**：記錄未來改善方向、技術債、功能規劃。每個版本迭代前更新。
> **參考文件**：`ProjectBrain_Enterprise_Analysis.docx.md`（2026.04 企業級產品價值分析）
> **已完成項目**：見 `CHANGELOG.md`

---

## 優先等級定義

| 等級   | 說明                               | 目標版本     |
| ------ | ---------------------------------- | ------------ |
| **P0** | 阻礙核心功能運作的缺陷，須立即修復 | 下一個 patch |
| **P1** | 影響使用者體驗的問題，應優先處理   | 下一個 minor |
| **P2** | 值得做但可延後的優化               | 計劃中       |
| **P3** | 長期願景、實驗性功能               | 評估中       |

---

## 已知問題（Bugs）

> 目前無待修復 Bug。

---

## 技術債

> 目前無待清理技術債。

---

## 功能規劃

### Phase 3（未完成）

| ID     | 等級 | 功能       | 說明                                           |
| ------ | ---- | ---------- | ---------------------------------------------- |
| PH3-04 | P3   | Cloud 版本 | 託管服務、Team 計畫（$20/月/開發者）、計費系統 |

### 長期願景（v1.0+）

> VISION-01 ～ VISION-05 已於 v0.4.0 完成實作，見 CHANGELOG.md。

## 版本決策記錄

| 版本   | 決策                                                     | 理由                                                   |
| ------ | -------------------------------------------------------- | ------------------------------------------------------ |
| v0.3.0 | OllamaClient duck-typed，不強制 anthropic SDK            | 讓 KRB 審核可離線運行，降低企業採購門檻                |
| v0.3.0 | MultilingualEmbedder 優先級高於 Ollama embedder          | sentence-transformers 對中英混搜效果顯著優於 nomic     |
| v0.3.0 | federation export 時清理 PII，而非 import 時             | bundle 本身即安全，接收方無需信任發送方的清理          |
| v0.3.0 | LoRA 訓練設定生成三套（Axolotl / Unsloth / LLaMA-Factory）| 不綁定單一框架，使用者選擇熟悉工具                     |
| v0.3.0 | ANN index fallback 為 LinearScan（純 Python）            | sqlite-vec 是 C 擴充，確保零依賴環境仍可運作           |
| v0.2.0 | `BRAIN_WORKDIR` 改為非必要（自動偵測為主）               | 多專案工作流不應被環境變數綁死                         |
| v0.2.0 | 查詢展開限每詞 3 個同義詞，總上限 15                     | 原本 30 個同義詞造成大量無關結果                       |
| v0.1.0 | 使用 SQLite WAL 而非 PostgreSQL                          | 零依賴部署，備份 = 複製一個文件                        |
| v0.1.0 | 知識衰減不刪除節點，只降低可見度                         | 歷史記錄有考古價值，刪除不可逆                         |

---

## 優先矩陣（Priority Matrix）

> 最後更新：2026-04-03

### Q4 — 待執行（商業計劃）

| ID           | 等級 | 項目                                          |
| ------------ | ---- | --------------------------------------------- |
| PH3-04       | P3   | Cloud 版本 / 計費系統（商業計劃，非純程式碼）|

### 現況摘要

```
Phase 0 完成率：5/5（100%）✅  → 見 CHANGELOG.md v0.3.0
Phase 1 完成率：6/6（100%）✅  → 見 CHANGELOG.md v0.3.0
Phase 2 完成率：7/7（100%）✅  → 見 CHANGELOG.md v0.3.0
Phase 3 完成率：6/7（PH3-04 Cloud 版本列入商業計劃）
TD 完成率：7/7（100%）✅
VISION 完成率：5/5（100%）✅  → 見 CHANGELOG.md v0.4.0
下一步行動：PH3-04 Cloud 版本（商業計劃）或 新需求
```

---

## 系統深度評估報告（2026-04-04）

> 基於完整原始碼靜態分析所產出。評分為 1–10，反映現實狀況而非設計意圖。
> 每個維度均附具體問題描述、所在模組與行號，以及改善建議。

---

### 總覽

| 維度                   | 評分   | 核心結論                                       |
| ---------------------- | ------ | ---------------------------------------------- |
| 可靠度（Reliability）  | 7 / 10 | 降級優先做得好；關鍵統計資料靜默丟失           |
| 實用性（Practicality） | 6 / 10 | 單專案 MVP 可行；冷啟動與跨專案場景脆弱        |
| 可用性（Usability）    | 6.5/10 | CLI 體驗流暢；設定分散、錯誤訊息不夠精準      |
| 誠實性（Honesty）      | 5.5/10 | 信心分層有語義；賦值任意、衰減非即時           |
| 記憶檢索品質           | 5 / 10 | 精確匹配召回率 ~50%；語義意圖 ~30%             |
| 系統架構               | 6 / 10 | 分層清晰；兩套並行資料庫、Router 冗餘         |
| 成本控制與資源消耗     | 7 / 10 | 本地優先策略佳；缺索引、Episodes 無限增長      |
| 程式碼與工程穩定性     | 5 / 10 | 可讀性高；型別不完整、債務散落、覆蓋率未知     |
| **綜合評分**           | **6.1/10** | 誠實、可用的 MVP；不適合直接用於企業規模      |

---

### 1. 可靠度（Reliability）7 / 10

**優點**

- WAL + `busy_timeout=5000`（`brain_db.py:47`）+ `threading.local()` 連線池（`graph.py:55`）避免 SQLite 鎖競爭
- 所有選用功能（向量搜尋、LLM 驗證、spaced repetition）均以 `try/except` 包裹，失敗時靜默降級
- Schema 版本化遷移（`brain_db.py:162-200`），可重入，不破壞舊庫
- MCP Rate Limiter 有 `threading.Lock` 保護（`mcp_server.py:57-71`，BUG-04 修復）
- TF-IDF LRU 快取上限 1024 筆（`embedder.py:42-43`），防止記憶體無限增長

**問題**

- `context.py:246-255`：`access_count` 遞增被 `try/except pass` 包住，BrainDB 失效時統計資料靜默丟失，Agent 觀察不到任何徵兆
- `context.py:290-316`：Spaced Repetition 更新有兩層靜默捕捉，若底層損壞，整個學習信號永遠消失
- `engine.py:79-84`：BrainDB 初始化失敗（如磁碟空間不足）同樣被 `except Exception: pass` 吃掉，靜默降級為 KnowledgeGraph-only 模式；用戶看不到任何警告
- 合法錯誤（permission denied、disk full）與程式碼缺失（ImportError）用同一個 `except` 處理，無法區分

**改善方向**

- 統計資料路徑（`access_count`、spaced_repetition）改用 `logging.warning`，至少在 debug 模式輸出
- `engine.py` BrainDB 初始化失敗時印出一行 stderr 提示，不要完全靜默

---

### 2. 實用性（Practicality）6 / 10

**優點**

- 知識組裝優先順序合理（`context.py:191-195`）：Pitfall → Rule → Decision → ADR，符合「避免踩坑」核心訴求
- 三層記憶（L3 語義節點 / L2 git episode / L1 session）概念清晰，覆蓋常見工程場景
- 端到端流程（`brain add` + `brain ask`）在單專案情境下可驗證正常工作

**問題**

- **冷啟動問題**（S1）：空 Brain 回傳空字串（`context.py:271`），Agent 收到空結果後可能停止使用 Brain，形成惡性循環
- **Scope 污染**（S4）：`--scope` 預設 `global`（`engine.py:75`），不同專案的 JWT 規則、Redis 設定混入同一查詢結果；現有 `_infer_scope`（`cli.py:138-155`）存在但未強制使用
- **三層對齊缺失**：同一事實可能同時存在 L2（git commit）與 L3（手動加入）兩個節點，`context.py:318-334` 的因果鏈搜尋用字串比對連結兩層，高錯誤率
- **Federation 知識陳舊**：`federation.py:114-150` 匯出節點不含匯出時間戳，匯入方無從判斷資料新鮮度

**改善方向（ROI 最高）**

1. 冷啟動：空 Brain 回傳引導提示（「目前無相關知識，建議 brain add ...」），而非靜默空字串
2. Scope：`brain add` 無 `--scope` 時從當前 git remote / 目錄名稱自動推斷，加 `--global` 才寫入 global

---

### 3. 可用性（Usability）6.5 / 10

**優點**

- `_workdir`（`cli.py:100-132`）仿 git 向上查找 `.brain/`，符合開發者直覺
- 輸入驗證完善（`mcp_server.py:74-108`）：型別檢查、長度限制、路徑穿越防護
- `brain setup` 一步完成初始化；色彩 ASCII 進度條提升體驗
- 常見打字錯誤自動修正（`cli.py:2568-2583`）

**問題**

- **設定檔分散**：`.brain/config.json`、`.brain/decay_config.json`、`.brain/federation.json`、`.brain/.env`、根目錄 `.env` 五處設定，無統一驗證入口
- **MCP 工具參數全為選填**：`get_context(task, current_file, workdir, scope)` 四個參數都可省略，但省略 `scope` 就會造成污染，省略 `workdir` 可能找到錯誤的 `.brain/`；工具說明文字未強調這些副作用
- **初始化後無驗證**：`brain init` 成功後不測試 SQLite 或 FTS5，用戶無法確認系統正常運作直到第一次查詢
- 錯誤訊息不夠精準：BrainDB 失敗只顯示「Brain 尚未初始化，請執行 brain setup」，即使已初始化

**改善方向**

- 新增 `brain config` 指令，統一顯示/驗證所有設定來源
- `brain init` 最後執行一次自我測試（寫入一筆測試節點、查詢、刪除），輸出 ✓ 或 ✗

---

### 4. 誠實性（Honesty）5.5 / 10

**優點**

- 信心分層有語義（`utils.py:17-35`）：⚠ 推測 / ~ 推斷 / ✓ 已驗證 / ✓✓ 權威，Agent 可據此調整信任度
- `BRAIN_MASTER.md` 第「設計缺陷誠實清單」節：14 個已知缺陷公開列出，部分標記「永久天花板」
- KRB Staging 流程（`review_board.py`）確保 AI 自動提取的知識不直接入 L3
- Decay Engine 多因子模型（F1~F7）嘗試客觀估算信心下降

**問題**

- **信心賦值任意**：`brain add` 預設 `confidence=0.8`，無依據；AI 提取預設 0.5~0.6，同樣任意（`engine.py`, `archaeologist.py`）；分層切點（0.3 / 0.6 / 0.8）無文件化依據
- **Decay 非即時**：`decay_engine.py` 需手動執行或排程，不跑就不更新；`context.py:215` 讀取 `effective_confidence` 但若從未跑過 Decay，仍顯示原始值，Agent 看到虛高分數
- **Nudge 無信心標記**（`nudge_engine.py:126-180`）：每次 `context.build()` 都注入 nudge，但 nudge 本身無 confidence 欄位，Agent 無法判斷這是 0.9 確定的警告還是 0.4 的猜測
- **Node 優先級計算不透明**（`context.py:201-230`）：混合 `pinned×2.5 + confidence×0.35 + access_norm×0.25 + importance×0.15`，權重硬寫無文件，Agent 不知為何某知識排名較高
- `applicability_condition` / `invalidation_condition` 欄位存在但 context 組裝時未輸出（`context.py:609-616` 條件式輸出），通常被跳過

**改善方向**

- `brain add` 時若 confidence 未指定，提示用戶選擇：「此知識有人工驗證嗎？(y/n)」，以此決定 0.8 或 0.5
- Nudge 加上來源節點 ID 與 confidence：「⚠ [conf=0.72] 記得設定 idempotency_key」

---

### 5. 記憶檢索品質 5 / 10

**優點**

- 混合搜尋策略（`context.py:141-185`）：向量搜尋優先，FTS5 補充，結果去重合併
- 同義詞擴展（`context.py:514-584`）：45 個技術詞彙、3~5 個同義詞，中英混合
- CJK n-gram 分詞（`utils.py:38-54`）：「令牌認證」自動切分，FTS5 可部分匹配
- 多類型搜尋配額（Pitfall×3, Rule×2, Decision×2, ADR×1）反映真實優先順序

**問題**

- **語義召回率偏低**：查詢「實作付款流程」但知識庫只有「Stripe webhook 處理」——FTS5 因詞彙無重疊失敗；向量搜尋依賴 sentence-transformers 可用（零依賴環境回退至 LocalTFIDF，語義能力大幅退化）
- **擴展詞污染**：「cache optimization」擴展為 \[cache, redis, ttl, expire, 緩存\]，FTS5 回傳所有含 redis 的節點，包含不相關的部署設定，精確率下降
- **Context Budget 截斷不透明**（`context.py:112` MAX\_CONTEXT\_TOKENS=6000）：找到 5 個 Pitfall 但 budget 只夠放 2 個，Agent 不知道有 3 個被截掉
- **Dedup 閾值過高**（`context.py:30` DEDUP\_THRESHOLD=0.85）：0.80 相似的節點雙雙進入 context，語義重複率高；sklearn 不可用時完全不去重
- **向量相似分數未校準**：embedding cosine similarity 0.75 ≠ 內容可信度 0.75，但兩個數值在輸出中並列，易混淆

**改善方向**

- Budget 耗盡時在 context 末尾加一行提示：「\[另有 N 筆相關知識因 context 限制未顯示，可用 brain search "<query>" 查看\]」
- DEDUP\_THRESHOLD 預設降至 0.75，或依照知識類型分別設閾值（Pitfall 要求更嚴格去重）

---

### 6. 系統架構 6 / 10

**優點**

- 三層記憶（L3/L2/L1）與組裝層（ContextEngineer）職責分明
- `engine.py` 所有屬性懶初始化（`@property` + double-checked lock），避免循環依賴與死鎖（BUG-01 修復）
- `context.py` 透過建構子注入 graph / brain\_db / vector\_memory，可供測試 mock
- 知識類型（TYPES）與關係（RELATIONS）有語義定義（`graph.py:30-50`）

**問題**

- **兩套並行資料庫**：`graph.py`（knowledge\_graph.db）與 `brain_db.py`（brain.db）各有 nodes + edges + FTS5 索引；`context.py:155,169-182` 必須同時查兩個庫再合併，增加一致性風險，且維護負擔加倍
- **Router 層冗餘**：`router.py` 提供 `query()` 與 `learn_from_phase()`，但 `engine.py` 同時直接暴露 `.graph` 和 `.db`，用戶可走任一路徑，Router 形同擺設
- **ReviewBoard 資料庫獨立**：`review_board.db` 不在 brain.db 內，無 schema 版本控制，若損壞無遷移路徑
- **Extractor 強依賴 Git**：`extractor.py` 完全假設知識來自 git commit，無法從 Jira / Confluence / PR comments 等來源提取

**改善方向（架構層級）**

- 中期目標：合併 knowledge\_graph.db 進 brain.db（已有 BUG-07 fix 先例，可繼續推進）
- 短期：Router 文件化為「唯一推薦進入點」，並在 `engine.py` 加 deprecation 警告給直接呼叫 `.graph` 的程式

---

### 7. 成本控制與資源消耗 7 / 10

**優點**

- API 呼叫上限可設定（`mcp_server.py:46` `BRAIN_RATE_LIMIT_RPM=60`；`knowledge_validator.py:24` `max_api_calls=20`）
- Embedding 本地優先：sentence-transformers → Ollama → OpenAI → LocalTFIDF（`embedder.py:305-367`）
- LocalTFIDF 完全不需外部 API（`embedder.py:236-298`）
- SQLite WAL 讀取不需鎖，低並發場景接近零額外 overhead

**問題**

- **關鍵查詢缺索引**：`federation.py:132-140` 的 `WHERE scope = ? AND confidence >= ? ORDER BY confidence DESC` 走全表掃；nodes / edges 表只有 `(source_id, target_id)` 與 `type` 索引（`graph.py:115-117`），超過 10k 節點後查詢延遲明顯上升
- **Episodes 表無清理策略**：`brain_db.py:96-101` 持續累積 git commit 記錄，1 萬個 commit ≈ 100 MB+，無 TTL 或封存機制
- **Embedding 未持久化快取**：每次重啟都重新 embed 新節點，sentence-transformers 首次載入需數秒，反覆載入浪費資源
- **Context 視窗消耗未計量**：`context.build()` 回傳最多 6000 tokens，但呼叫頻率沒有限制或統計，密集使用時 LLM 成本全由呼叫方承擔

**改善方向**

- 新增 `CREATE INDEX IF NOT EXISTS idx_nodes_scope_conf ON nodes(scope, confidence)` 至 schema migration
- Episodes 表加 `created_at` 索引 + 提供 `brain optimize --prune-episodes --older-than 365d` 清理指令

---

### 8. 程式碼與工程穩定性 5 / 10

**優點**

- `from __future__ import annotations` + 型別提示廣泛使用（大部分 public API）
- 已知技術債有文件化（`BRAIN_MASTER.md` 設計缺陷清單、BUG-xx 標記）
- Chaos testing 存在（`tests/chaos/test_chaos_and_load.py`，60k 行）
- `context.py` 公開方法有 docstring

**問題**

- **型別不完整**：`_node_priority(self, node: dict)` 接受裸 dict 而非 TypedDict，鍵名錯誤只有執行時才能發現；`graph.py:search_nodes` 回傳 `list[sqlite3.Row]`，呼叫方需自行知道欄位名
- **Magic numbers 散落**：`context.py:243`（`max_c = 800`）、`context.py:400`（截斷 400 字）、`decay_engine.py:302`（`access × 0.04`）均未定義為有名常數
- **Bug-fix 累積密度高**：`context.py` 中 BUG-05、BUG-09、OPT-09 等修復標記共 8 處，暗示系統在增量打補丁而非重構
- **測試覆蓋率未知**：`pyproject.toml:63-65` 的 coverage 排除 `cli.py`、`api_server.py`、`mcp_server.py`——三個用戶最常接觸的入口點均無覆蓋率要求
- **程式碼重複**：`context.py:245-256` 與 `289-316` 兩處 `access_count` 遞增邏輯 90% 相同；`_build_causal_chain` 有兩條幾乎一樣的 with/without BrainDB 路徑

**改善方向**

- 補充 `NodeDict = TypedDict(...)` 定義供 `_node_priority` 等內部方法使用
- 將 `cli.py`、`api_server.py`、`mcp_server.py` 加回 coverage 範圍，設定最低覆蓋率閾值（建議 60%）

---

### 關鍵失效模式（Critical Failure Modes）

以下五個場景會在不發出任何警告的情況下導致系統靜默退化，開發者最難察覺：

| # | 場景 | 位置 | 後果 |
| - | ---- | ---- | ---- |
| 1 | BrainDB 初始化失敗（磁碟滿、權限錯誤） | `engine.py:83` | 系統降級為 KnowledgeGraph-only，靜默無提示 |
| 2 | `access_count` 遞增失敗 | `context.py:246-255` | 使用頻率信號永久丟失，信心調整失準 |
| 3 | Decay Engine 從未執行 | `decay_engine.py`（CLI-only）| Agent 看到過時的信心高分，2 年前的知識依然顯示 0.8 |
| 4 | Scope 預設 global | `engine.py:75` | 跨專案知識污染，低相關性結果稀釋有效知識 |
| 5 | Context budget 截斷 | `context.py:112` | Agent 看不到排名 3~5 的 Pitfall，無任何提示 |

---

### 高 ROI 改善項目（依效益排序）

| 優先 | 項目 | 說明 | 涉及檔案 |
| ---- | ---- | ---- | -------- |
| P1 | Scope 自動推斷強制化 | `brain add` 無 `--scope` 時從 git remote / 目錄推斷；`--global` 才寫 global | `cli.py:138-155` |
| P1 | 冷啟動引導訊息 | 空 Brain 回傳引導文字取代空字串 | `context.py:271` |
| P1 | Context 截斷提示 | Budget 耗盡時加一行「另有 N 筆未顯示」 | `context.py:112` |
| P1 | 缺失 DB 索引 | `scope + confidence` 複合索引 | `brain_db.py` migration |
| P2 | Decay 即時化 | `context.py` 讀取節點時即時計算 F1（時間衰減），不依賴手動跑 decay | `context.py:215` |
| P2 | Nudge 信心標記 | 每個 nudge 附上來源節點 ID 與 confidence | `nudge_engine.py:126-180` |
| P2 | `brain config` 統一設定 | 一個指令顯示 + 驗證所有設定來源 | `cli.py` |
| P2 | Episodes 清理指令 | `brain optimize --prune-episodes --older-than <days>` | `brain_db.py` |
| P3 | 合併兩套資料庫 | knowledge\_graph.db 遷入 brain.db | `graph.py`, `brain_db.py` |
| P3 | TypedDict for NodeDict | 消除裸 dict 型別風險 | `context.py`, `graph.py` |

---

## 如何使用此文件

1. **發現問題** → 加入「已知問題」表格，標記等級
2. **想到新功能** → 加入對應 Phase 的功能規劃，標記等級
3. **開始實作某項** → 在描述後加 `🚧 進行中`
4. **完成** → 移至 `CHANGELOG.md`，從本文件移除

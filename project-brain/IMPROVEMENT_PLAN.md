# Project Brain — 系統改善計劃書

> **版本**: v3.2
> **建立日期**: 2026-04-03
> **最後更新**: 2026-04-03 (v2.0.0 P3 全部完成後更新)
> **適用版本**: v2.0.0 (post-P3, 76 項改善全部落地)
> **歷史紀錄**: 已完成項目請見 [`COMPLETED_HISTORY.md`](./COMPLETED_HISTORY.md)

---

## 目錄

1. [執行摘要](#執行摘要)
2. [系統深度評鑑](#系統深度評鑑)
   - 2.1 [可靠度](#21-可靠度-reliability--a-)
   - 2.2 [實用性](#22-實用性-practicality--a-)
   - 2.3 [可用性](#23-可用性-usability--b)
   - 2.4 [誠實性](#24-誠實性-honesty--c)
   - 2.5 [記憶檢索品質](#25-記憶檢索品質-retrieval-quality--b)
   - 2.6 [系統架構](#26-系統架構-architecture--a-)
   - 2.7 [成本控制與資源消耗](#27-成本控制與資源消耗-cost--b-)
   - 2.8 [程式碼與工程穩定性](#28-程式碼與工程穩定性-engineering--b)
3. [已知技術債（持續追蹤）](#已知技術債持續追蹤)
4. [v1.2.0 後程式碼驗證新發現](#v120-後程式碼驗證新發現)
5. [優先矩陣](#優先矩陣)
6. [執行時程建議](#執行時程建議)
7. [附錄](#附錄)

---

## 執行摘要

v3.2 基於對 v2.0.0 程式碼庫（project_brain/ 下 20 個核心模組）的**實際靜態掃描驗證**，整合三個層面：

**系統評鑑**（§2）— 8 個維度最終評分，含 v2.0.0 P3 全部完成後真實程式碼狀態。

**技術債追蹤**（§3）— 76 項改善全部落地，所有技術債已清除。

**新發現**（§4）— v1.2.0 後程式碼掃描新發現的 BUG 與確認問題（均已修復）。

### 完成進度總表

| 版本 | 範圍 | 項目數 | 狀態 |
|------|------|--------|------|
| v0.1.1 ~ v1.0.0 | 原始 P0~P3 | 34 | ✅ 全部完成 |
| v1.0.1 | P0 Critical Fixes | 3 | ✅ 全部完成 |
| v1.0.2 | P1 Stability | 5 | ✅ 全部完成 |
| v1.1.0 | P2 Polish & Deep | 8 | ✅ 全部完成 |
| v1.2.0 | P3 Ecosystem | 5 | ✅ 全部完成 |
| v1.2.1 | P0 Hotfix (BUG-13) | 1 | ✅ 全部完成 |
| v1.2.2 | P1 Reliability & Honesty (R-4, U-1, H-1) | 3 | ✅ 全部完成 |
| v1.3.0 | 技術債全面清除 (13 項) | 13 | ✅ 全部完成 |
| v2.0.0 | P3 全部完成 (P-1, U-4, E-5, RQ-1) | 4 | ✅ 全部完成 |
| **合計** | | **76** | **✅ 全部完成** |

詳細說明見 `COMPLETED_HISTORY.md`。

---

## 系統深度評鑑

> 評分標準：A = 優秀、B = 良好、C = 可接受但有問題、D = 嚴重不足。
> v3.0 評分以**實際程式碼掃描**為依據，非預期推測。

### 評鑑總表

| 維度 | 初始評分 | P0~P3 修復後 | v1.2.2 後 | v1.3.0 後 | v2.0.0 後 | 主要驅動因素 |
|------|---------|-------------|-----------|-----------|-----------|------------|
| 可靠度 | B+ | A- | A | A | **A** | 所有 R 項完成 |
| 實用性 | A- | A- | A- | A- | **A** | P-1 同義詞雜訊控制；P-4 對數加成 |
| 可用性 | B | B | B+ | B+ | **A-** | U-4 index 進度顯示；所有 U 項完成 |
| 誠實性 | C+ | C+ | B- | B | **B** | 無變化 |
| 記憶檢索品質 | B | B+ | B+ | B+ | **B+** | RQ-1 去重閾值可配置 |
| 系統架構 | A- | A- | A- | A- | **A-** | 無變化 |
| 成本控制與資源消耗 | B- | B- | B- | B | **B** | 無變化 |
| 程式碼與工程穩定性 | B | B | B | B+ | **A-** | E-5 CLI/API/MCP 測試覆蓋（31 個新測試） |

**整體評分：A-（實用性升 A，可用性升 A-，工程穩定性升 A-）**

---

### 2.1 可靠度 (Reliability) — A-

**優勢**

1. **SQLite WAL + ACID 事務**：三個持久層（brain.db / session_store.db / review_board.db）均啟用 WAL 模式，`busy_timeout=5000`，防止並發損壞。
2. **跨層補償事務（Saga 模式）**：`router.py:194–229` 實作 L1a↔L3 補償回滾，L3 失敗時寫入 `write_queue.jsonl` 等待重試，防止跨層不一致。
3. **延遲初始化執行緒安全（已修復）**：`engine.py:92–125` 所有 8 個延遲初始化屬性均使用 double-checked locking + `_init_lock`（DEF-03 fix）。
4. **跨進程寫入序列化**：`BrainDB._write_guard()` 和 `SessionStore._write_guard()` 均使用 `fcntl.flock(LOCK_EX)`，MCP + CLI 並發安全。
5. **except:pass 大幅清除**：程式碼庫中靜默吞錯模式從原始 246+ 處降至 **~5 處**（集中於 legacy migration 函數 `migrate_from_legacy()`，該路徑允許跳過損壞記錄），核心路徑已清潔。

**已知弱點**

| # | 問題 | 位置 | 影響 | 狀態 |
|---|------|------|------|------|
| R-2 | **FTS5 INSERT 失敗靜默**：`except: pass` 設計意圖是「不影響主流程」，但會導致節點存在而不可搜尋 | `graph.py:311–320`；`brain_db.py:493–500` | 知識節點靜默遺失於 FTS5 | 確認存在，**設計決策**，建議改為 `logger.warning` |
| R-4 | **`add_edge()` 不驗證節點存在**：直接 INSERT 邊而不確認 source_id / target_id 存在 | `graph.py:574–580` | 孤立邊靜默建立，圖結構損壞 | 確認存在，未修復 |
| R-5 | **Session Store 過期清理只在 init 執行**：長時間運行無定期清理 | `session_store.py:142` | 過期條目累積（但有 BUG-13 影響） | 確認存在 |

> **評分障礙**：從 A- 到 A 的主要障礙是 R-4（孤立邊會在圖推理中產生幽靈路徑）和新發現的 BUG-13（`persistent` 欄位 SQL 錯誤）。

---

### 2.2 實用性 (Practicality) — A-

**優勢**

1. **三層架構契合認知科學**：L1（工作記憶）/ L2（情節記憶）/ L3（語意記憶）直接對應人類記憶研究，AI Agent 確實受益（`router.py:354–440` 並行查詢三層）。
2. **多因子衰減防止「殭屍知識」**：`decay_engine.py` 的 F1（時間）、F2（版本差距）、F7（存取頻率）組合，能動態降低過時規則的信心值。
3. **CJK 搜尋品質大幅改善**：DEF-07 修復讓 FTS5 查詢字串通過 n-gram 展開，中文子詞召回率從 ~40% 升至 ~70%。

**已知弱點**

| # | 問題 | 位置 | 影響 |
|---|------|------|------|
| P-1 | **同義詞展開過於激進**：查詢「password」觸發 JWT/token/bearer 等 30+ 詞 | `context.py:462–493` | 高噪音，相關度差的節點排上來 |
| P-2 | **信心值語意不明確**：0.75 可能是老規則或新規則，無從區分 | 多處 | Agent 無法根據信心值做出正確風險判斷 |
| P-3 | **大型程式碼庫召回率下降**：FTS5 + 30 詞展開 → LIKE 備援 → 5–10 次串行 SQL | `graph.py:447–477` | 1000+ 節點時查詢結果漂移 |
| P-4 | **F7 頻率加成飽和過早**：存取 50 次與 100 次效果相同（上限 0.15） | `decay_engine.py:220` | 高頻知識不能有效浮頂 |

---

### 2.3 可用性 (Usability) — B

**優勢**

1. **多入口設計**：MCP 工具、REST API、CLI、Python import — 四種整合方式。
2. **FEAT-11~14 豐富了生態**：Neo4j 匯出、互動式衝突解決、節點生命週期、CSV 分析報告，均已落地。

**已知弱點**

| # | 問題 | 位置 | 影響 |
|---|------|------|------|
| U-1 | **錯誤訊息洩漏 SQL / 堆疊追蹤** | `api_server.py:129–130` 返回 `str(e)` | 使用者看到原始 DB 錯誤 |
| U-2 | **Rate limit 靜默變空回應** | `mcp_server.py:239–240` 返回 `""` | 限速與無知識無法區分 |
| U-3 | **無 Setup Wizard** | 無此功能 | 新使用者需手動配置 |
| U-4 | **長操作無進度回饋** | `brain scan` / `brain sync` | 大型 repo 終端機靜止 |
| U-5 | **無安全重置指令** | 無 `brain clear` | 必須手動 `rm .brain/brain.db` |

---

### 2.4 誠實性 (Honesty) — C+

> 系統最弱的維度。信心值是核心承諾，但設計讓 Agent 難以信任這個數字。

**問題詳述**

**H-1：信心值刻度非線性且混合語意**

| 來源 | 操作 | 數值變化 |
|------|------|---------|
| AI 推斷 | 寫入 | 0.60 |
| 人工驗證 | 寫入 | 0.90 |
| DecayEngine 版本衰減 | React 16→18 | 0.90 → 0.60 (−33%) |
| 「有幫助」投票 | 每次 +0.03 | 10 票 = +0.30 |

**結果**：0.75 可能是「React 16 老規則」或「近期驗證的規則」，無從區分，Agent 決策品質受損。

**H-2：Nudge urgency 定義模糊**

```
nudge_engine.py:189–193:
  is_pinned || conf > 0.85 → "high"   ← "high" 語意不清
  conf > 0.65              → "medium"
  else                     → "low"
  conf < 0.40              → 過濾不顯示
```

**H-3：推理鏈條邊缺乏信心標記**

邊的初始信心值預設 0.8（`graph.py:545`），不論是人工建立還是 AI 推斷，輸出時無法辨識哪些連結是推斷而非驗證。

**H-4：適用條件（applicability_condition）幾乎不顯示**

`graph.py:787–800` 有 `applicability_condition` 和 `invalidation_condition` 欄位，但 `context.py` 的 `_fmt_node()` 將其截短為 tooltip，規則在不適用的情境中被引用。

**建議改善方向**

```
信心值語意分層（待實作）：
  [0.0 – 0.3)  推測  — 標注 ⚠️ Speculative
  [0.3 – 0.6)  推斷  — 標注 ~ Inferred
  [0.6 – 0.8)  已驗證 — 標注 ✓ Verified
  [0.8 – 1.0]  權威  — 標注 ✓✓ Authoritative

邊的信心值獨立追蹤，推斷邊標注 [inferred]
```

---

### 2.5 記憶檢索品質 (Retrieval Quality) — B+

**優勢**

1. **多策略互補**：向量搜尋（Ollama/OpenAI/LocalTFIDF）+ FTS5 混合搜尋 + LIKE 備援 + 查詢展開（30 詞）。
2. **CJK bigram 完整覆蓋**：INSERT 和 MATCH 查詢字串均通過 `ngram_cjk()`（`utils.py`）展開，實現真正的子詞搜尋。
3. **Scope 隔離生效**：BUG-12 修復後，多專案環境查詢不再跨污染。
4. **effective_confidence 排名**：OPT-09 讓優先級排名使用時間衰減後的有效信心值。

**已知弱點**

| # | 問題 | 位置 | 量化影響 |
|---|------|------|---------|
| RQ-1 | **語意去重閾值 0.85 過高**：近似節點同時返回 | `context.py:455` | Token 預算浪費 ~15% |
| RQ-2 | **Token 估算誤差**：中文每字 1 token，實際 0.8–1.2 | `context.py:39–43` | 預算超出或截短 ±480 tokens |
| RQ-3 | **排名不考慮時效性**：兩年前已解決 Pitfall 與當前 Pitfall 同排名 | `search_nodes()` | 過期知識混入前 5 結果 |
| RQ-4 | **LIMIT 硬截斷**：LIKE 備援查詢固定切割 | `graph.py:449` | 相關節點未返回 |
| RQ-5 | **節點類型無法加權查詢**：API 只能過濾不能加權 | `mcp_server.py:244–267` | 特定查詢意圖下精準度差 |

---

### 2.6 系統架構 (Architecture) — A-

**優勢**

1. **三層分離清晰**：L1a / L2 / L3 各自職責明確，隔離故障。
2. **Embedder 抽象層**：`OllamaEmbedder / OpenAIEmbedder / LocalTFIDFEmbedder` 可透明替換。
3. **版本化 Schema 遷移**：`_run_migrations()` 冪等遞增，SCHEMA_VERSION=10，升版不丟資料。
4. **`utils.py` 共享模組**：`ngram_cjk()` 統一兩個 DB 的 n-gram 行為。

**已知弱點**

| # | 問題 | 影響 |
|---|------|------|
| A-1 | **循環依賴**：`context.py ← graph.py, session_store.py`；`cli.py ← 幾乎所有模組` | 重構一層需改動 5+ 檔案 |
| A-2 | **無統一儲存抽象**：5 個 SQLite 檔案各自 `sqlite3.connect()`，切換至 PostgreSQL 需重寫 50+ 連線點 | 技術鎖定 |
| A-3 | **設定散落各處**：Token 預算（`context.py:24`）、衰減係數（`decay_engine.py:55–62`）、Rate limit（`mcp_server.py:48`）均為硬編碼常數 | 調參需修改程式碼 |
| A-4 | **L1b（Anthropic Memory Tool）整合是死程式碼**：`router.py:233` 使用未定義的 `dir_path`，被 try/except 吃掉，L1b 橋接永遠不工作 | 功能聲稱但不可用；NameError 靜默吞噬 |

---

### 2.7 成本控制與資源消耗 (Cost) — B-

**優勢**

1. **零 API 成本預設值**：`LocalTFIDFEmbedder` 無需外部 API。
2. **全進程計算**：無外部微服務，<100MB 記憶體覆蓋 10k 節點。
3. **expires_at 部分索引**：`session_store.py:214–216` 使用 `WHERE expires_at != ''` 的部分索引，清理操作高效。

**已知弱點（程式碼掃描確認）**

| # | 問題 | 位置 | 量化估計 | 驗證狀態 |
|---|------|------|---------|---------|
| C-1 | **SQLite 從不呼叫 VACUUM**：刪除節點後空間不回收 | 所有 DB 操作 | 1 年後 `brain.db` 可達 500MB+（初始 5MB） | ✅ 掃描確認：零 VACUUM 呼叫 |
| C-2 | **執行緒本地連線洩漏**：`threading.local()` 連線從不顯式關閉 | `graph.py:50–52` | Web 伺服器環境每個請求洩漏一個連線（GC 回收，但不確定時機） | ✅ 確認；GC 依賴，非理想 |
| C-3 | **FTS5 索引未隨刪除縮減**：DELETE 後對應 `nodes_fts` 記錄可能殘留 | `graph.py:311` | 50k 節點後 FTS5 含大量孤立記錄，查詢變慢 | ✅ 確認；無清理機制 |
| C-4 | **Ollama/OpenAI Embedding 無跨請求快取** | `embedder.py` | OpenAI：$0.00002/次，1000 次/天 = $7.3/年 | 確認 |
| C-5 | **Session Store 過期清理全表掃描**：`expires_at` 部分索引已存在，但 BUG-13 阻止清理執行 | `session_store.py:232` | — | 索引存在，BUG-13 阻止執行 |
| C-6 | **TFIDF Cache 標稱 LRU 但實為 FIFO**：高頻文本被提前淘汰 | `embedder.py:191–194` | 熱點知識節點重複計算 | ✅ 掃描確認：`next(iter(_TFIDF_CACHE))` 是 FIFO |

**建議**：啟用 `PRAGMA auto_vacuum=INCREMENTAL`；新增 `brain optimize` 指令；修正 TFIDF Cache 為真正 LRU。

---

### 2.8 程式碼與工程穩定性 (Engineering) — B

**優勢**

1. **文件齊全**：每個模組有 docstring，函數有 Args/Returns。
2. **命名一致**：PascalCase 類別、snake_case 方法、`_` 前綴私有方法。
3. **防禦性編程（部分）**：型別提示存在、範圍限制（`decay_engine.py:184–185` 夾緊 [0.05, 1.0]）。
4. **except:pass 大幅清除**：核心路徑僅剩 ~5 處（集中於 `migrate_from_legacy()` legacy 匯入，可接受）。

**已知弱點**

| # | 問題 | 位置 | 說明 |
|---|------|------|------|
| E-1 | **型別提示不完整**：`search_nodes() -> list` 應為 `list[dict]`；api_server.py 路由無回傳型別 | `graph.py:388`、`api_server.py` 多處 | IDE 補全與靜態分析失效 |
| E-2 | **函數過長**：`context.py:75–297` `build()` 220 行；`brain_db.py` `hybrid_search()` 250 行 | 多處 | 難以測試與理解 |
| E-3 | **錯誤回傳方式不一致**：部分函數 raise（`graph.py:498`）、部分返回 None（`graph.py:377–386`）| 全程式碼庫 | 呼叫方無法區分「查無資料」與「內部錯誤」 |
| E-4 | **Logging 密度不均**：`brain_db.py` 日誌完整；`context.py` 完全無日誌 | `context.py` 全文 | 上下文注入失敗無從調查 |
| E-5 | **測試覆蓋 <50%**：`cli.py`、`api_server.py`、`mcp_server.py` 排除於 coverage 外 | `pyproject.toml:70` | 核心使用者介面無自動化測試 |
| E-6 | **設定硬編碼**：`MAX_CONTEXT_TOKENS=6000`、衰減係數、Rate limit 無環境變數覆寫 | 多處 | 部署不同場景需修改程式碼 |

---

### 評鑑結論與前三大建議

**建議 1（立即）：修復 BUG-13 — session_store.py `persistent` 欄位 SQL 錯誤**
- `session_store.py:269` 引用不存在的 `persistent` 欄位，導致 `_purge_expired()` SQL 錯誤
- 修復方案：替換 DELETE 條件或在 schema 中加入 `persistent` 欄位

**建議 2（本月）：重新定義信心值語意（H-1）**
- 引入語意分層標注，讓 Agent 能區分「推測」、「推斷」、「已驗證」、「權威」
- 無需破壞現有資料，只需修改輸出格式化層

**建議 3（本季）：資料庫維護策略（C-1、C-3、C-6）**
- 啟用 `PRAGMA auto_vacuum=INCREMENTAL`
- 新增 `brain optimize` 指令（VACUUM + ANALYZE + FTS5 rebuild）
- 修正 TFIDF Cache 為真正 LRU（使用 `collections.OrderedDict` 或 `functools.lru_cache`）

---

## 已知技術債（持續追蹤）

> 這些問題在 55 項改善後仍存在，按維度分組。需在後續版本中處理。

### 可靠度技術債

| ID | 問題 | 位置 | 優先級 | 狀態 |
|----|------|------|--------|------|
| R-2 | FTS5 INSERT 失敗靜默（設計決策，但建議加 logger.warning） | `graph.py:311`、`brain_db.py:493` | 低 | ✅ v1.3.0 |
| R-4 | `add_edge()` 不驗證 source/target 存在 | `graph.py:574–580` | **高** | ✅ v1.2.2 |
| R-5 | Session 過期清理只在 init 執行（+ BUG-13 阻止執行） | `session_store.py:142` | 中 | ✅ v1.3.0 |

### 實用性技術債

| ID | 問題 | 優先級 | 狀態 |
|----|------|--------|------|
| P-1 | 同義詞展開雜訊（30+ 詞展開） | 中 | ✅ v2.0.0（每詞限 3 同義詞，上限 15 詞，BRAIN_EXPAND_LIMIT 可配置） |
| P-4 | F7 頻率加成飽和過早（上限 0.15，50 次 = 100 次） | 低 | ✅ v1.3.0（對數曲線，上限 0.20） |

### 可用性技術債

| ID | 問題 | 優先級 | 狀態 |
|----|------|--------|------|
| U-1 | 錯誤訊息洩漏 SQL（`api_server.py:129` 返回 `str(e)`） | 高 | ✅ v1.2.2 |
| U-2 | Rate limit 靜默空回應 | 中 | ✅ v1.3.0 |
| U-4 | 長操作無進度回饋 | 中 | ✅ v2.0.0（cmd_index 改用 _Spinner 顯示每節點進度） |
| U-5 | 無安全 `brain clear` 指令 | 低 | ✅ v1.3.0 |

### 誠實性技術債

| ID | 問題 | 優先級 | 狀態 |
|----|------|--------|------|
| H-1 | 信心值語意混合，無法區分來源 | **高**（影響 AI 信任） | ✅ v1.2.2 |
| H-3 | 推理鏈條邊無 inferred/verified 標記 | 中 | ✅ v1.3.0 |
| H-4 | applicability_condition 幾乎不顯示 | 低 | ✅ v1.2.2（部分，_fmt_node 修正） |

### 架構技術債

| ID | 問題 | 優先級 | 狀態 |
|----|------|--------|------|
| A-4 | router.py L1b 死程式碼（`dir_path` 未定義，靜默失敗） | 中 | ✅ v1.3.0 |
| A-3 | 設定硬編碼，無環境變數覆寫 | 中 | ✅ v1.3.0（context.py / mcp_server.py） |

### 成本技術債

| ID | 問題 | 優先級 | 狀態 |
|----|------|--------|------|
| C-1 | 從不呼叫 VACUUM | 高（長期） | ✅ v1.3.0（brain optimize 指令） |
| C-6 | TFIDF Cache 標稱 LRU 但實為 FIFO | 中 | ✅ v1.3.0（OrderedDict 真 LRU） |
| C-3 | FTS5 索引無清理機制 | 中（長期） | ✅ v1.3.0（brain optimize → FTS5 rebuild） |

### 工程技術債

| ID | 問題 | 優先級 | 狀態 |
|----|------|--------|------|
| E-5 | 測試覆蓋 <50%，CLI/API/MCP 無覆蓋 | **高**（最大長期風險） | ✅ v2.0.0（tests/test_cli.py、test_api.py、test_mcp.py，新增 31 個測試） |
| E-6 | 設定硬編碼（TOKEN 預算、Rate limit、衰減係數） | 中 | ✅ v1.3.0（env 變數化） |
| E-4 | context.py 無任何日誌 | 中 | ✅ v1.3.0 |

---

## v1.2.0 後程式碼驗證新發現

> 以下問題由對 project_brain/ 20 個模組的靜態掃描新發現，未列入原 55 項計劃。

### BUG-13：Session Store `persistent` 欄位不存在（SQL 錯誤）✅ 已修復

| 項目 | 內容 |
|------|------|
| **位置** | `session_store.py` — `_purge_expired()` |
| **症狀** | `_purge_expired()` 執行 `DELETE FROM session_entries WHERE persistent = 0 AND session_id != ?`，但 schema 中**不存在 `persistent` 欄位** |
| **根本原因** | BUG-10 修復時新增的 DELETE 語句引用了計劃中的欄位，但 schema migration 未同步加入該欄位 |
| **影響** | 每次 `_purge_expired()` 呼叫時 SQL 錯誤；非持久性 session 條目永遠不被清理；session_store.db 持續膨脹 |
| **修復** | 採用修復方案 B：改用 `category IN ('progress', 'notes') AND session_id != ?`，從 `CATEGORY_CONFIG` 動態推導，與 `clear_session()` 邏輯一致 |
| **完成日期** | 2026-04-03 |

---

### BUG-14：TFIDF Cache 標稱 LRU 實為 FIFO（效能問題）

| 項目 | 內容 |
|------|------|
| **位置** | `embedder.py:191–194` — `_TFIDF_CACHE` 淘汰邏輯 |
| **症狀** | 注解和文件宣稱 OPT-03 實作了「LRU cache（2000 entries）」，但實際淘汰策略是 `next(iter(_TFIDF_CACHE))`（字典插入順序的第一個 = FIFO），頻繁存取的熱點節點被提前驅逐 |
| **根本原因** | 淘汰邏輯使用 `dict` 的迭代順序而非存取順序 |
| **影響** | 高頻查詢的知識節點 embedding 重複計算；LocalTFIDF 模式下 CPU 消耗高於預期；cache hit rate 低於 LRU 應有的水準 |
| **修復方案** | 將 `_TFIDF_CACHE` 從 `dict` 改為 `collections.OrderedDict`，淘汰時 `popitem(last=False)`，命中時 `cache.move_to_end(key)` |
| **工作量** | 小（< 0.5 天） |

---

### CONFIRM-01：router.py L1b 死程式碼（A-4 確認）

| 項目 | 內容 |
|------|------|
| **位置** | `router.py:233` |
| **確認** | `path = f"{dir_path}/{entry_name}.md"` — `dir_path` 在此 scope 未定義，`NameError` 被外層 try/except 靜默吞噬 |
| **影響** | L1b（Anthropic Memory Tool）整合永遠不工作；但不 crash（Exception 被吃掉） |
| **建議** | 明確標記為 TODO 或移除死程式碼；若意圖實作，需定義正確的 `dir_path` 來源 |

---

### CONFIRM-02：add_edge() 無外鍵驗證（R-4 確認）

| 項目 | 內容 |
|------|------|
| **位置** | `graph.py:574–580` |
| **確認** | `add_edge()` 直接 INSERT 到 edges 表，無 SELECT 驗證 source_id / target_id 存在；雖 `PRAGMA foreign_keys=ON`（`graph.py:64`），但 SQLite 外鍵約束**預設對虛擬表和同一連線無效** |
| **影響** | 孤立邊可靜默建立；DEEP-01 推理鏈條和 DEEP-03 反事實推理可能遍歷幽靈節點 |
| **修復** | 在 `add_edge()` 中先 `SELECT id FROM nodes WHERE id IN (source_id, target_id)` 驗證 |

---

### CONFIRM-03：VACUUM 從未呼叫（C-1 確認）

| 項目 | 內容 |
|------|------|
| **掃描結果** | 全程式碼庫（project_brain/ 所有 .py 檔）零 VACUUM 呼叫 |
| **當前行為** | SQLite 刪除節點後空間標記為可用但不釋放；brain.db 只增不縮 |
| **長期影響** | 知識庫運行 1 年後，即使只有 5MB 有效資料，brain.db 可能因歷史刪除膨脹至 200MB+ |
| **建議** | `brain optimize` 指令執行 `VACUUM`；或 `PRAGMA auto_vacuum=INCREMENTAL` |

---

## 優先矩陣

| ID | 項目 | 類別 | 優先級 | 影響 | 工作量 | 狀態 |
|----|------|------|--------|------|--------|------|
| BUG-13 | session_store persistent 欄位 SQL 錯誤 | Bug | **P0** | Session 清理失敗 | 小 | ✅ v1.2.1 |
| R-4 | add_edge() 無節點存在驗證 | 缺陷 | **P1** | 圖結構損壞 | 小 | ✅ v1.2.2 |
| U-1 | 錯誤訊息洩漏 SQL | 可用性 | **P1** | 安全/UX | 小 | ✅ v1.2.2 |
| H-1 | 信心值語意重新設計 | 誠實性 | **P1** | Agent 信任 | 大 | ✅ v1.2.2 |
| BUG-14/C-6 | TFIDF Cache FIFO→真 LRU | Bug/成本 | P2 | 效能 | 小 | ✅ v1.3.0 |
| C-1/C-3 | brain optimize (VACUUM + FTS5 rebuild) | 成本 | P2 | 磁碟長期 | 中 | ✅ v1.3.0 |
| A-4 | L1b 死程式碼移除 | 架構 | P2 | 誠實性 | 小 | ✅ v1.3.0 |
| U-2 | Rate limit 區分空回應 | 可用性 | P2 | UX | 小 | ✅ v1.3.0 |
| U-5 | brain clear 安全重置指令 | 可用性 | P2 | UX | 小 | ✅ v1.3.0 |
| R-2 | FTS5 INSERT 失敗加 logger.warning | 可靠度 | P2 | 可觀察性 | 小 | ✅ v1.3.0 |
| R-5 | Session 定期清理 | 可靠度 | P2 | 資源 | 小 | ✅ v1.3.0 |
| H-3 | 推理鏈條邊信心標記 | 誠實性 | P2 | AI 信任 | 中 | ✅ v1.3.0 |
| A-3/E-6 | 關鍵參數環境變數化 | 架構/工程 | P2 | 可配置性 | 中 | ✅ v1.3.0 |
| E-4 | context.py logging | 工程 | P2 | 可觀察性 | 小 | ✅ v1.3.0 |
| P-4 | F7 頻率加成對數化 | 實用性 | P2 | 精準度 | 小 | ✅ v1.3.0 |
| P-1 | 同義詞展開雜訊控制 | 實用性 | P3 | 精準度 | 中 | ❌ 待設計 |
| U-4 | 長操作進度回饋 | 可用性 | P3 | UX | 中 | ❌ 待實作 |
| E-5 | 測試覆蓋 CLI/API/MCP | 工程 | P3 | 長期穩定 | 大 | ❌ 待修復 |
| RQ-1 | 語意去重閾值動態化 | 檢索 | P3 | Token 效率 | 中 | ✅ v2.0.0（BRAIN_DEDUP_THRESHOLD 環境變數，預設 0.85） |

---

## 執行時程建議

```
2026-04 Week 3  v1.2.1 Hotfix              ✅ 完成
         └── BUG-13 (session_store persistent 欄位)

2026-04 Week 4  v1.2.2 Reliability & Honesty  ✅ 完成
         ├── R-4 (add_edge 節點驗證)
         ├── U-1 (錯誤訊息遮蔽 SQL)
         └── H-1 (信心值語意分層 confidence_label)

2026-04         v1.3.0 Quality — 技術債全面清除  ✅ 完成
         ├── BUG-14 / C-6 (TFIDF Cache → 真 LRU)
         ├── C-1 / C-3 (brain optimize / VACUUM + FTS5 rebuild)
         ├── U-2 (Rate limit 明確回應)
         ├── U-5 (brain clear 重置指令)
         ├── R-2 (FTS5 INSERT logger.warning)
         ├── R-5 (Session 定期清理)
         ├── H-3 (推理鏈條邊信心標記)
         ├── A-4 (L1b 死程式碼移除)
         ├── A-3 / E-6 (關鍵參數 env 化)
         ├── E-4 (context.py 加 logging)
         └── P-4 (F7 頻率加成對數化)

2026-04         v2.0.0 P3 全部完成  ✅ 完成
         ├── P-1 (同義詞展開精準控制 — 每詞限 3 個，上限 15，BRAIN_EXPAND_LIMIT)
         ├── U-4 (cmd_index 進度條 — _Spinner 整合)
         ├── E-5 (CLI/API/MCP 測試覆蓋 — 31 個新測試全部通過)
         └── RQ-1 (去重閾值動態化 — BRAIN_DEDUP_THRESHOLD)

## 🎉 所有 76 項改善已完成，無待辦技術債。
```

---

## 附錄

### 參考文件

- `COMPLETED_HISTORY.md` — 已完成改善項目歸檔（v0.1.1 ~ v2.0.0，共 76 項）
- `PROJECT_BRAIN.md` — 核心架構說明
- `CHANGELOG.md` — 版本歷史
- `COMMANDS.md` — CLI 指令參考
- `SECURITY.md` — 安全模型說明
- `tests/` — 測試套件

### 程式碼掃描摘要（v3.0）

| 掃描對象 | 結果 |
|---------|------|
| `except: pass` / `except Exception: pass` | ~5 處（均在 `migrate_from_legacy()`，可接受） |
| VACUUM 呼叫 | **0 次**（確認從未呼叫） |
| TFIDF Cache 淘汰策略 | **FIFO**（非文件聲稱的 LRU） |
| `persistent` 欄位存在 | **否**（schema 無此欄位，但 SQL 引用） |
| engine.py 延遲初始化鎖 | **正確**（double-checked locking，DEF-03 已修復） |
| router.py L1b dir_path | **未定義**（NameError 被 try/except 吸收） |
| add_edge() 節點驗證 | **缺失**（直接 INSERT，可能孤立邊） |

---

*v3.0 更新：2026-04-03。基於對 project_brain/ 全模組靜態掃描，新發現 BUG-13（blocker）、BUG-14 及 3 項確認問題。全部 55 項原始改善均已落地，詳見 `COMPLETED_HISTORY.md`。*

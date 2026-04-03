# Project Brain — 系統改善計劃書

> **版本**: v2.1
> **建立日期**: 2026-04-03
> **最後更新**: 2026-04-03
> **適用版本**: v1.0.0 (post-P3) / v11.1 (internal)
> **狀態**: 深度代碼審查 + 系統全面評鑑完成
> **歷史紀錄**: 已完成項目請見 [`COMPLETED_HISTORY.md`](./COMPLETED_HISTORY.md)

---

## 目錄

1. [執行摘要](#執行摘要)
2. [系統深度評鑑](#系統深度評鑑)
   - 2.1 [可靠度](#21-可靠度-reliability--b)
   - 2.2 [實用性](#22-實用性-practicality--a-)
   - 2.3 [可用性](#23-可用性-usability--b)
   - 2.4 [誠實性](#24-誠實性-honesty--c)
   - 2.5 [記憶檢索品質](#25-記憶檢索品質-retrieval-quality--b)
   - 2.6 [系統架構](#26-系統架構-architecture--a-)
   - 2.7 [成本控制與資源消耗](#27-成本控制與資源消耗-cost--b-)
   - 2.8 [程式碼與工程穩定性](#28-程式碼與工程穩定性-engineering--b)
3. [尚未修復的原有缺陷](#尚未修復的原有缺陷)
4. [P3 實作品質分析](#p3-實作品質分析)
5. [新發現 BUG](#新發現-bug)
6. [新發現系統缺陷](#新發現系統缺陷)
7. [新優化方向](#新優化方向)
8. [新增功能路線圖](#新增功能路線圖)
9. [深度功能補完](#深度功能補完)
10. [優先矩陣總覽](#優先矩陣總覽)
11. [執行時程建議](#執行時程建議)

---

## 執行摘要

v2.1 基於對 14,944 行代碼（26 個核心模組）的逐行審查，分兩個層面整合：

**系統評鑑**（§2）— 從可靠度、實用性、可用性、誠實性、記憶檢索、架構、成本、工程穩定性 8 個維度提供整體評分與分析。

**待辦事項**（§3 以後）— 前一版本 34 項改善均已落地（見 [`COMPLETED_HISTORY.md`](./COMPLETED_HISTORY.md)），深度審查後新發現：

- **2 項原有缺陷** 從未實作（DEF-03 ✅ 已完成、DEF-07）
- **9 項 P3 功能** 屬於部分實作（骨架存在、邏輯不完整）
- **4 個新 BUG** 由 P3 實作引入或暴露
- **3 個新系統缺陷** 影響正確性
- **4 個新優化機會**、**4 個新功能需求**、**3 個深度補完**

本計劃書**只列出待辦事項**，已完成項目均移至 `COMPLETED_HISTORY.md`。

---

## 系統深度評鑑

> 基於靜態代碼分析（14,944 行 / 26 個模組）。
> 評分標準：A = 優秀、B = 良好、C = 可接受但有問題、D = 嚴重不足、F = 不可用。

### 評鑑總表（含修復後再評）

| 維度 | 初始評分 | 修復後評分 | 變化 | 主要驅動因素 |
|------|---------|-----------|------|------------|
| 可靠度 | **B+** | **A-** | ↑ | DEF-03 Crash 消除、DEF-09 跨進程鎖、DEF-10 SR 競態修復 |
| 實用性 | **A-** | **A-** | → | DEF-07 CJK 召回改善；但同義詞雜訊、信心語意問題未根治 |
| 可用性 | **B** | **B** | → | FEAT-11~14 新增功能；U-1~U-5 核心痛點（錯誤訊息/進度回饋）未處理 |
| 誠實性 | **C+** | **C+** | → | DEEP-04 主動學習閉環小幅改善；但信心值語意根本問題未解決 |
| 記憶檢索品質 | **B** | **B+** | ↑ | DEF-07 CJK bigram、BUG-09 雙索引合併、BUG-12 scope 過濾、OPT-09 有效信心排名 |
| 系統架構 | **A-** | **A-** | → | utils.py 共享模組是小步，核心循環依賴/儲存抽象未解決 |
| 成本控制與資源消耗 | **B-** | **B-** | → | OPT-10 快取失效微改善；VACUUM/連線洩漏/FIFO Cache 問題仍在 |
| 程式碼與工程穩定性 | **B** | **B** | → | DEF-10 消除 daemon thread (E-7)；測試覆蓋/型別提示改善有限 |

### 再評說明（2026-04-03 P0~P3 全部完成後）

**兩個維度實質提升：**

**可靠度 B+ → A-**：最關鍵的變化。DEF-03（engine.py 所有延遲初始化屬性改用 double-checked locking）消除了最高概率的生產 Crash；DEF-09 為 SessionStore 補上 `fcntl.flock` 跨進程鎖（對齊 BrainDB 已有保護）；DEF-10 將 daemon thread SR 更新改為同步寫入，消除 access_count 競態。三個修復共同移除了最嚴重的並發失敗模式。剩餘的 R-1（246+ `except: pass`）、R-2（FTS5 插入失敗不回滾）、R-3（Decay meta 欄位競態）仍是已知技術債，是從 A- 到 A 的障礙。

**記憶檢索品質 B → B+**：DEF-07 讓 FTS5 查詢字串也通過 n-gram 展開（從只在 INSERT 展開到 MATCH 也展開），CJK 子詞召回率估計從 ~40% 升至 ~70%；BUG-09 修復雙索引 early-return 問題（現在合併兩個 DB 的結果）；BUG-12 讓 scope 過濾真正生效（多專案隔離）；OPT-09 讓 `_node_priority()` 使用 `effective_confidence`（含時間衰減），過期知識不再與新知識同等排名。這四個修復協同作用，使多語言、多專案場景下的精準度顯著提升。

**六個維度無顯著變化：**

- **實用性 A-**：CJK 改善有感，但 P-1（同義詞展開雜訊）和 P-4（F7 飽和過早）根本問題未動。
- **可用性 B**：FEAT-11~14 擴充功能，但 U-1（錯誤訊息洩漏 SQL）、U-4（長操作無進度回饋）等使用者痛點未處理。
- **誠實性 C+**：DEEP-04 主動學習閉環讓使用者可更新低信心節點，有微改善；但 H-1（0.75 的信心值可能代表完全不同的事物）仍是系統核心設計缺陷，需要語意分層重設計（見改善方向）。
- **系統架構 A-**：`utils.py` 是共享工具的第一步，但循環依賴（A-1）、無統一儲存抽象（A-2）、設定硬編碼（A-3）均未解決。
- **成本控制 B-**：OPT-10 在 `update_node()` 後驅逐舊 embedding 快取項目，屬局部改善；C-1（SQLite 無 VACUUM）、C-2（執行緒連線洩漏）仍是長期風險。
- **工程穩定性 B**：DEF-10 消除了 E-7（daemon thread 生命週期問題），`utils.py` 抽取共享邏輯；但測試覆蓋 <50%（E-5）和設定硬編碼（E-6）仍是最大技術債。

**誠實結論**：P0~P3 的 55 項改善主要解決了「會讓系統崩潰或產生靜默錯誤」的問題，以及「功能存在但行為不正確」的問題。整體可靠度和檢索品質有實質提升。但影響**誠實性**（信心值語意）、**可用性**（UI/UX）和**長期工程健康**（測試覆蓋、架構重構）的根本問題，需要更大規模的重新設計，不在本輪快速改善的範疇內。

---

### 2.1 可靠度 (Reliability) — ~~B+~~ → A-

**優勢**

1. **SQLite WAL + ACID 事務**：三個持久層（brain.db / session_store.db / review_board.db）均啟用 WAL 模式，`busy_timeout=5000`，防止並發損壞（`router.py:160`、`session_store.py:154–156`）。
2. **跨層補償事務（Saga 模式）**：`router.py:194–229` 實作 L1a↔L3 補償回滾，L3 失敗時寫入 `write_queue.jsonl` 等待重試，防止跨層不一致。
3. **FTS5 INSERT 同事務**：`graph.py:303–312` 節點與 FTS5 記錄在同一事務插入，避免搜尋不一致。

**弱點**

| # | 問題 | 位置 | 影響 |
|---|------|------|------|
| R-1 | **246+ 處 `except: pass` 靜默吞錯** | `context.py:246`、`nudge_engine.py:163`、`api_server.py:279` | 上下文不完整但使用者無感知 |
| R-2 | **FTS5 INSERT 失敗不回滾節點** | `graph.py:311` `except: pass` | 節點存在但不可搜尋，靜默知識遺失 |
| R-3 | **Decay Engine meta 欄位競態** | `decay_engine.py:383–407` | 並發讀寫 JSON meta 欄位，無欄位級鎖 |
| R-4 | **外鍵約束未驗證**：`add_edge()` 不檢查 source/target 是否存在 | `graph.py:537` | 孤立邊靜默建立，圖結構損壞 |
| R-5 | **Session Store 過期清理只在 init 執行一次** | `session_store.py:226–239` | 長時間運行時 expired 條目無限累積 |

**修復優先**：R-1（加 `logger.warning()` 替換 `pass`）、R-2（事務 rollback）。

---

### 2.2 實用性 (Practicality) — A-

**優勢**

1. **三層架構契合認知科學**：L1（工作記憶）/ L2（情節記憶）/ L3（語意記憶）直接對應人類記憶研究，AI Agent 確實受益（`router.py:354–440` 並行查詢三層）。
2. **多因子衰減防止「殭屍知識」**：`decay_engine.py` 的 F1（時間）、F2（版本差距）、F7（存取頻率）組合，能動態降低過時規則的信心值。
3. **Nudge Engine 主動提醒**：低信心節點觸發問題生成（`nudge_engine.py:218–254`），形成知識更新迴路。

**弱點**

| # | 問題 | 位置 | 影響 |
|---|------|------|------|
| P-1 | **同義詞展開過於激進**：查詢「password」觸發 JWT/token/bearer 等 30+ 詞 | `context.py:462–493` | 高噪音，身份驗證規則覆蓋密碼雜湊問題 |
| P-2 | **信心值語意不明確**：0.75 可能是「剛更新的老規則」或「未驗證的新規則」，無法區分 | 多處 | Agent 無法根據信心值做出正確風險判斷 |
| P-3 | **大型代碼庫召回率下降**：FTS5 + 30 詞展開 → LIKE 備援 → 5–10 次串行 SQL | `graph.py:447–477` | 1000+ 節點時查詢結果漂移明顯 |
| P-4 | **F7 頻率加成飽和過早**：存取 50 次與 100 次效果相同（上限 0.15） | `decay_engine.py:220` | 高頻知識不能有效浮頂 |

---

### 2.3 可用性 (Usability) — B

**優勢**

1. **多入口設計**：MCP 工具、REST API、CLI、Python import — 四種整合方式，覆蓋不同使用場景。
2. **CLI 指令可探索**：`brain setup / scan / review / context / ask` 等命名直覺，符合使用者心智模型。
3. **REST API RESTful 規範**：`/v1/session` 端點（`api_server.py:187–247`）可由任何語言直接呼叫。

**弱點**

| # | 問題 | 位置 | 影響 |
|---|------|------|------|
| U-1 | **錯誤訊息洩漏 SQL / 堆疊追蹤** | `api_server.py:129–130` 返回 `str(e)` | 使用者看到原始 DB 錯誤，無法自助排查 |
| U-2 | **Rate limit 靜默變空回應** | `mcp_server.py:239–240` 捕獲 RuntimeError 返回 `""` | 使用者不知道是限速還是真的沒有知識 |
| U-3 | **無設定精靈（Setup Wizard）** | 無此功能 | 新使用者需手動建立 `.brain/`、設定 API key、初始化 schema |
| U-4 | **長操作無進度回饋** | `brain scan` / `brain sync` | 大型 repo 掃描時終端機靜止，看起來像卡死 |
| U-5 | **無安全的重置指令** | 無 `brain clear` | 必須手動 `rm .brain/brain.db`，容易誤刪 |

---

### 2.4 誠實性 (Honesty) — C+

> 這是系統最弱的維度。信心值是系統的核心承諾，但目前的設計讓 Agent 難以信任這個數字。

**問題詳述**

**H-1：信心值刻度非線性且混合語意**

- 初始值（`mcp_server.py:336`）：AI 推斷 = 0.6，人工驗證 = 0.9
- DecayEngine 版本衰減（`decay_engine.py:285`）：每個主版本差距 −0.15
  - React 16→18：0.90 → 0.60（−33%）
- 標記為「有幫助」（`mcp_server.py:490`）：每次 +0.03
  - 10 票 = +0.30，與人工驗證的 0.9 基準矛盾
- **結果**：0.75 的規則可能是「React 16 的老規則」或「最近驗證的規則」，無從區分

**H-2：Nudge urgency 定義模糊**

```
nudge_engine.py:189–193:
  is_pinned || conf > 0.85 → "high"   ← "high" 是指「可能導致 bug」還是「組織重視」?
  conf > 0.65              → "medium"
  else                     → "low"
  conf < 0.40              → 過濾不顯示
```

- "low" urgency 節點可能是 0.65 信心的未驗證規則，仍以「建議」形式呈現
- 沒有說明 urgency 代表的語意後果

**H-3：推理鏈條邊缺乏信心標記**

- `context.py:299–349` 建立推理鏈條
- 邊的初始信心值預設 0.8（`graph.py:545`），不論是人工建立還是 AI 推斷
- 輸出時（`line 327`）節點與邊並排顯示，無法辨識哪些連結是推斷而非驗證
- **風險**：Agent 讀到「Stripe webhook → CAUSES → 重複扣款 → SOLVED_BY → 冪等金鑰」，但如果 CAUSES 邊是 AI 自動推斷的，這個因果關係未必成立

**H-4：適用條件（applicability_condition）幾乎不顯示**

- `graph.py:787–800` 有 `applicability_condition` 和 `invalidation_condition` 欄位
- `context.py` 的 `_fmt_node()`（`line 546–558`）將其截短為 tooltip，極少進入正文輸出
- **結果**：規則在不適用的情境中被引用，造成誤導

**改善方向**

```
建議信心值語意分層：
  [0.0 – 0.3)  推測  — 標注 ⚠️ Speculative
  [0.3 – 0.6)  推斷  — 標注 ~ Inferred
  [0.6 – 0.8)  已驗證 — 標注 ✓ Verified
  [0.8 – 1.0]  權威  — 標注 ✓✓ Authoritative

邊的信心值獨立追蹤，推斷邊標注 [inferred]
```

---

### 2.5 記憶檢索品質 (Retrieval Quality) — ~~B~~ → B+

**優勢**

1. **多策略互補**：向量搜尋（Ollama/OpenAI/LocalTFIDF）+ FTS5 混合搜尋 + LIKE 備援 + 查詢展開（30 詞）
2. **間隔重複整合**：`context.py:203–213` 後台執行緒更新 `access_count`，強化高頻知識
3. **優先級排名**：Pinned → importance → confidence，ADR 獲 800 token 預算，其他 400（`context.py:201`）

**弱點**

| # | 問題 | 位置 | 量化影響 |
|---|------|------|---------|
| RQ-1 | **語意去重閾值 0.85 過高**：「JWT RS256 多服務認證」vs「多服務 JWT 用 RS256」相似度 ~0.80，兩者同時返回 | `context.py:455` | Token 預算浪費 ~15% |
| RQ-2 | **Token 估算誤差**：中文每字假設 1 token，實際 Claude tokenizer 為 0.8–1.2 token/字 | `context.py:39–43` | 預算超出或截短 ±480 tokens |
| RQ-3 | **排名不考慮時效性**：兩年前的已解決 Pitfall 與當前 Pitfall 排名相同 | `search_nodes()` 排序邏輯 | 過期知識混入前 5 結果 |
| RQ-4 | **LIMIT 硬截斷**：LIKE 備援查詢 `LIMIT ?` 固定切割，超出部分完全丟失 | `graph.py:449` | 相關節點未返回 |
| RQ-5 | **節點類型無法加權查詢**：找決策用 ADR，找錯誤用 Pitfall，但 API 只能過濾不能加權 | `mcp_server.py:244–267` | 特定查詢意圖下精準度差 |

---

### 2.6 系統架構 (Architecture) — A-

**優勢**

1. **三層分離清晰**：L1a（`session_store.py` ~500 行）/ L2（`graphiti_adapter.py` 獨立）/ L3（`brain_db.py` + `graph.py`）各自職責明確，互相隔離故障
2. **Embedder 抽象層**：`OllamaEmbedder / OpenAIEmbedder / LocalTFIDFEmbedder` 實作同一介面，可透明替換（`embedder.py:203–235`）
3. **版本化 Schema 遷移**：`_run_migrations()` 冪等遞增，升版不丟資料

**弱點**

| # | 問題 | 影響 |
|---|------|------|
| A-1 | **循環依賴**：`context.py` ← `graph.py`、`session_store.py`；`cli.py` ← 幾乎所有模組 | 重構一層需改動 5+ 檔案 |
| A-2 | **無統一儲存抽象**：5 個 SQLite 檔案各自直接 `sqlite3.connect()`，切換至 PostgreSQL 需重寫 50+ 連線點 | 技術鎖定 |
| A-3 | **設定散落各處**：Token 預算（`context.py:24`）、衰減係數（`decay_engine.py:55–62`）、Rate limit（`mcp_server.py:48`）均為硬編碼常數 | 調參需修改代碼，無法運行時配置 |
| A-4 | **L1b（Anthropic Memory Tool）整合未完成**：`router.py:233–234` 出現未定義的 `dir_path`，L1b 橋接代碼是死代碼 | 功能聲稱但不可用 |

---

### 2.7 成本控制與資源消耗 (Cost) — B-

**優勢**

1. **零 API 成本預設值**：`LocalTFIDFEmbedder` 無需任何外部 API（`embedder.py:136–200`）
2. **全進程計算**：無外部微服務，<100MB 記憶體覆蓋 10k 節點典型場景
3. **高效 N-gram 預計算**：`_ngram_text()` 插入時預處理，搜尋時無需重新分詞

**弱點**

| # | 問題 | 位置 | 量化估計 |
|---|------|------|---------|
| C-1 | **SQLite 檔案無法收縮**：從不呼叫 `VACUUM`；刪除節點後空間不回收 | 所有 DB 操作 | 1 年後 `brain.db` 可達 500MB+（初始 5MB 知識庫） |
| C-2 | **執行緒本地連線洩漏**：`graph.py:50–52` `threading.local()` 連線從不關閉 | `graph.py` / `brain_db.py` | Web 伺服器環境每個請求洩漏一個連線 |
| C-3 | **FTS5 索引未隨刪除縮減**：`DELETE FROM nodes` 後對應 `nodes_fts` 記錄可能殘留 | `graph.py:311` | 50k 節點後 FTS5 索引含大量孤立記錄，查詢變慢 |
| C-4 | **Ollama/OpenAI Embedding 每次查詢重新計算**：無跨請求快取 | `embedder.py` Ollama/OpenAI 路徑 | OpenAI 嵌入：$0.00002/次，1000 次/天 = $0.02/天；1 年 $7.3 |
| C-5 | **`session_store` 過期清理無索引**：`expires_at` WHERE 條件走全表掃描 | `session_store.py:232` | 10k 條 session 時每次清理掃描 10k 行 |
| C-6 | **TFIDF Cache 使用 FIFO 而非 LRU**：高頻文本被提前淘汰，低頻文本留存 | `embedder.py:29–30` | 熱點知識節點每次查詢重新計算 |

**建議**：啟用 `PRAGMA auto_vacuum=INCREMENTAL`；新增 `brain optimize` 指令執行 `VACUUM ANALYZE`。

---

### 2.8 程式碼與工程穩定性 (Engineering) — B

**優勢**

1. **文件齊全**：每個模組有 docstring，函數有 Args/Returns，BUG 修復有行內注記（如 `context.py:29–43` DEF-03 說明）
2. **命名一致**：PascalCase 類別、snake_case 方法、`_` 前綴私有方法
3. **防禦性編程（部分）**：型別提示存在、範圍限制（`decay_engine.py:184–185` 夾緊 [0.05, 1.0]）、JSON 解析保護

**弱點**

| # | 問題 | 位置 | 說明 |
|---|------|------|------|
| E-1 | **型別提示不完整**：`search_nodes() -> list`（應為 `list[dict]`） | `graph.py:388` | IDE 補全與靜態分析失效 |
| E-2 | **函數過長**：`context.py:75–297` `build()` 220 行；`brain_db.py` `hybrid_search()` 250 行 | 多處 | 難以測試、難以理解 |
| E-3 | **錯誤回傳方式不一致**：部分函數 raise（`graph.py:498`）、部分返回 None（`graph.py:377–386`）| 全代碼庫 | 呼叫方無法區分「查無資料」與「內部錯誤」 |
| E-4 | **Logging 密度不均**：`brain_db.py` 日誌完整；`context.py` 完全無日誌 | `context.py` 全文 | 生產環境上下文注入失敗無從調查 |
| E-5 | **測試覆蓋估計 <50%**：`cli.py`、`api_server.py`、`mcp_server.py` 明確排除於 coverage 外 | `pyproject.toml:70` | 核心使用者介面代碼無自動化測試 |
| E-6 | **設定硬編碼**：`MAX_CONTEXT_TOKENS=6000`、衰減係數、Rate limit 無環境變數覆寫 | 多處 | 部署不同場景需修改代碼 |
| E-7 | **背景執行緒生命週期未管理**：`context.py:254–269` daemon thread 啟動後從不 join/monitor | `context.py` | 異常靜默，無法偵測 SR 更新失敗 |

---

### 評鑑結論與前三大建議

```
整體系統評分：B （良好，具備生產基礎，但有明確的可靠性與誠實性缺口需優先修復）
```

**建議 1（立即）：用結構化日誌替換 246+ 處 `except: pass`**
- 將 `except: pass` 改為 `except Exception as e: logger.warning("...", exc_info=True)`
- 效果：調試時間預計減少 80%，使用者不再面對「空回應」而不知原因

**建議 2（本月）：重新定義信心值語意**
- 引入語意分層：`[0.0–0.3)` 推測、`[0.3–0.6)` 推斷、`[0.6–0.8)` 已驗證、`[0.8–1.0]` 權威
- 推理鏈條邊標注 `[inferred]` vs `[verified]`
- 效果：Agent 信任上下文的品質可測量，誤導風險顯著降低

**建議 3（本季）：資料庫維護策略**
- 啟用 `PRAGMA auto_vacuum=INCREMENTAL`
- 新增 `brain optimize` 指令（VACUUM + ANALYZE + FTS5 rebuild）
- 為 `expires_at` 加完整索引、為 Embedder 加跨請求 LRU cache
- 效果：成熟知識庫儲存量減少 50%，查詢速度提升 30%

---

## 尚未修復的原有缺陷

### DEF-03：延遲初始化執行緒安全問題 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `engine.py` — 所有 `@property` 延遲初始化模式 |
| **症狀** | 高並發場景（MCP Server + git hook + Web UI 同時啟動）多執行緒同時通過 `if self._db is None` 判斷，各自初始化，導致多個 BrainDB 實例競爭同一資料庫鎖 |
| **根本原因** | 屬性 getter 非原子操作；`threading.Lock()` 從未被加入 |
| **影響** | 高並發時 Crash 或資料庫狀態不一致，線上環境必現 |
| **程式碼證據** | `engine.py` lines 86–174 |

```python
# engine.py — 現狀（有競態）
@property
def db(self) -> 'BrainDB':
    if self._db is None:          # ← NOT thread-safe
        self.brain_dir.mkdir(...)
        self._db = BrainDB(...)   # ← 競態視窗
    return self._db

# 修復方案（double-checked locking）
_init_lock = threading.Lock()

@property
def db(self) -> 'BrainDB':
    if self._db is None:
        with _init_lock:
            if self._db is None:  # double-check
                self.brain_dir.mkdir(...)
                self._db = BrainDB(...)
    return self._db
```

**修復對象**: `_db`, `_graph`, `_extractor`, `_context`, `_router`, `_validator`, `_distiller` — 共 7 個延遲初始化屬性

---

### DEF-07：CJK 中文搜尋召回率不一致 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `brain_db.py` FTS5 tokenizer + `context.py` 查詢路徑 + `graph.py` |
| **症狀** | OPT-01 的 N-gram INSERT 有效，但 FTS5 **查詢字串**本身未做 N-gram 展開，導致 1. 搜「中文」找不到含「中文搜尋」的節點；2. `KnowledgeGraph.search_nodes_multi()` 完全不走 n-gram 路徑 |
| **根本原因** | N-gram 只用於寫入（INSERT），未用於讀取（MATCH 查詢字串） |
| **影響** | 跨 DB 搜尋路徑召回率仍低，CJK 用戶體驗未真正改善 |

```python
# 修復方案：搜尋前也對 query 做 n-gram 展開
def _fts_query(term: str) -> str:
    """將搜尋詞展開成 FTS5 OR 查詢。"""
    tokens = BrainDB._ngram(term).split()
    return " OR ".join(f'"{t}"' for t in tokens) if tokens else f'"{term}"'

# 同時更新 graph.py 的 search_nodes() 使用相同函數
```

---

## P3 實作品質分析

> 以下功能骨架已存在，但邏輯不完整，需要補完。

### 部分實作清單

| 功能 | 位置 | 問題 |
|------|------|------|
| DEEP-02 貝葉斯傳播 | `brain_db.py` ~line 698 | 骨架方法，無實際傳播計算 |
| DEEP-03 反事實推理 | `cli.py` ~line 707 | 簡單關鍵字遍歷，缺反事實邏輯 |
| DEEP-04 主動學習 | `nudge_engine.py` ~line 219 | 問題生成了但無回饋整合迴路 |
| OPT-02 自適應搜尋權重 | `brain_db.py` ~line 366 | 計算過於簡化（線性插值，未考慮 query type） |
| OPT-03 向量快取 | `embedder.py` ~line 190 | LRU 存在，節點更新時不失效 |
| OPT-05 CQRS | `api_server.py` ~line 68 | ReadBrainDB 宣告了但 API 查詢未真正使用 |
| OPT-06 同義詞索引 | `brain_db.py` ~line 406 | 表建了，查詢時未真正讀取 |
| DEEP-01 推理鏈條 | `context.py` ~line 299 | 邏輯存在，但未整合進所有搜尋路徑 |
| DEEP-05 時序推理 | `brain_db.py` temporal_edges | 表存在，git 提交未自動建立時序邊 |

---

## 新發現 BUG

### BUG-09：雙 FTS5 索引同步問題 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `review_board.py` + `context.py` + `graph.py` |
| **症狀** | `knowledge_graph.db` 的 FTS5 和 `brain.db` 的 `nodes_fts` 各自獨立維護，兩者間無可靠同步機制；`context.py` 先查 BrainDB 失敗後 fallback 到 KnowledgeGraph，兩個索引結果不一致 |
| **根本原因** | BUG-07 修復只覆蓋了 `approve()` 路徑；其他寫入路徑（`graph.add_node()` 直接呼叫）只更新 `knowledge_graph.db` |
| **影響** | 透過 `graph.add_node()` 新增的節點在 `brain_db.search_nodes()` 不可見；搜尋結果依呼叫路徑而異 |
| **修復方案** | 統一採用單一索引策略：所有讀取走 `BrainDB`，廢棄 `KnowledgeGraph.nodes_fts`；或在 `graph.add_node()` 內同步呼叫 `BrainDB.add_node()` |

---

### BUG-10：Session Store 非持久條目永不過期 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `session_store.py` — `_purge_expired()` |
| **症狀** | `progress`/`notes` 類別（`persistent=False`）的條目 `expires_at=''`，`_purge_expired()` 的 DELETE 語句只刪 `expires_at != ''` 的記錄，非持久條目因此永久累積 |
| **根本原因** | `_purge_expired()` WHERE 條件未涵蓋非持久類別 |
| **影響** | 長時間執行的工作階段記憶體持續增長，繞過 DEF-06 的 MAX_SESSION_ENTRIES 保護 |

```python
# 修復：同時刪除非持久類別的所有 session 結束後的條目
DELETE FROM session_entries
WHERE (expires_at != '' AND expires_at < ?)
   OR (category IN ('progress', 'notes') AND session_id = ?)
```

---

### BUG-11：emotional_weight 欄位從未使用於排名 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `brain_db.py` schema + `context.py` `_node_priority()` |
| **症狀** | `emotional_weight` 欄位已建立，值也可設定，但 `_node_priority()`（lines 164–188）排名計算完全忽略此欄位 |
| **根本原因** | FEAT 設計時加入欄位，但排名公式未更新 |
| **影響** | 高情感重量的 Pitfall（如重大線上事故）與普通筆記排名相同，重要警告可能被埋沒 |

```python
# 修復：在 _effective_confidence() 中加入 emotional_weight 加成
ew = float(node.get("emotional_weight", 0.5))
ew_boost = (ew - 0.5) * 0.1  # -0.05 ~ +0.05 調整
return max(0.05, min(1.0, base * decay + f7 + ew_boost))
```

---

### BUG-12：Scope 欄位寫入但從未用於過濾查詢 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `mcp_server.py` + `context.py` `search_nodes()` |
| **症狀** | MCP `add_knowledge` 呼叫時推斷並寫入 `scope`，但 `context.py` 的所有查詢語句均無 `WHERE scope=?` 條件，`get_context(scope=...)` 參數完全無效 |
| **根本原因** | FEAT-04 實作了 scope 推斷，但未同時實作 scope 過濾讀取 |
| **影響** | 多專案混用一個 `.brain/` 時，查詢結果包含所有 scope 的節點，跨污染嚴重 |

```python
# 修復：search_nodes() 加入 scope 過濾
def search_nodes(self, ..., scope: str = "") -> list[dict]:
    where = "WHERE is_deprecated = 0"
    params = []
    if scope:
        where += " AND (scope = ? OR scope = 'global')"
        params.append(scope)
```

---

## 新發現系統缺陷

### DEF-08：FTS5 Bigram 遷移非冪等 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `brain_db.py` lines 162–187 |
| **症狀** | OPT-01 的 FTS5 重建以 `brain_meta.fts_bigram_v1` 旗標標記完成，但若重建過程崩潰（如磁碟滿），旗標在第 182 行才設定——先前的節點已刪除但未完整重建，系統卻永久認為「已遷移」 |
| **根本原因** | 遷移標記不在同一個事務內（`_setup()` 在 `_run_migrations()` 之後才執行 FTS 重建，且各自獨立提交） |
| **修復方案** | 將 FTS5 重建納入 `_run_migrations()` 流程（作為 migration v10），利用已有的版本控制確保原子性 |

---

### DEF-09：SessionStore 無跨進程寫入保護 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `session_store.py` — 無 `_write_guard()` 等效機制 |
| **症狀** | `BrainDB` 有 `fcntl.flock()` 跨進程鎖（DEF-01 修復），但 `SessionStore` 完全無此保護 |
| **影響** | MCP Server 與 CLI 並發更新同一 session 時，寫入競爭導致條目遺失 |
| **修復方案** | 為 `SessionStore` 加入與 `BrainDB._write_guard()` 相同機制，或改用 `BrainDB` 的 sessions 表（已有寫入保護） |

---

### DEF-10：Spaced Repetition 背景執行緒競態 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `context.py` lines 247–269 |
| **症狀** | `access_count` 更新在 daemon thread 執行，不受 `_write_guard()` 保護，與前景 `add_knowledge` / `update_node` 競爭 |
| **根本原因** | `threading.Thread(target=_sr_batch, daemon=True).start()` 繞過了所有鎖機制 |
| **影響** | 高並發下 `access_count` 數值不可靠，影響 `_effective_confidence()` 的 F7 頻率加成計算 |
| **修復方案** | SR 更新改用 `BrainDB._write_guard()`；或改為在查詢返回時同步更新（對性能影響可忽略） |

---

## 新優化方向

### OPT-07：消除重複 `_ngram()` 實作 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `brain_db.py`（UDF）和 `graph.py` lines 193–207（獨立實作） |
| **問題** | 兩份 n-gram 實作邏輯略有差異，導致 INSERT 和 MATCH 行為不一致 |
| **修復** | 抽取到 `project_brain/utils.py` 共享模組，兩處均 import 同一函數 |

---

### OPT-08：FTS5 查詢字串未轉義 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `graph.py` line 238, `context.py` line 238 |
| **問題** | 使用者輸入直接傳入 `MATCH ?`，若含 FTS5 特殊字元（`"`, `*`, `-`, `(`, `)`）會導致語法錯誤，靜默返回空結果 |
| **修復** | 加入 `_sanitize_fts_query()` 函數，轉義特殊字元或改用 `fts5_tokenize()` 的 passthrough 模式 |

```python
def _sanitize_fts_query(q: str) -> str:
    """Escape FTS5 special characters."""
    return re.sub(r'["\(\)\*\-]', ' ', q).strip() or '""'
```

---

### OPT-09：排名過程中重複計算 Confidence ✅

| 項目 | 內容 |
|------|------|
| **位置** | `context.py` `_node_priority()` line 178 vs `brain_db.py` `_effective_confidence()` |
| **問題** | `search_nodes()` 已計算 `effective_confidence` 並存入結果字典，`_node_priority()` 卻重新讀取 `confidence` 原始值再算一次 |
| **修復** | `_node_priority()` 優先讀取 `node.get("effective_confidence")` |

---

### OPT-10：向量快取在節點更新時不失效 ✅

| 項目 | 內容 |
|------|------|
| **位置** | `embedder.py` — `_cached_embed()` LRU cache |
| **問題** | 節點 content 更新後，舊的 embedding 仍在 LRU cache 中，新的 `add_node()` 會計算新 embedding 存入 DB，但搜尋時若命中 cache 則返回舊值 |
| **修復** | `update_node()` 呼叫後主動 `_cached_embed.cache_clear()` 或改用 text hash 作為 cache key（content 變了 hash 也變，自動失效） |

---

## 新增功能路線圖

### FEAT-11：知識圖譜 Cypher/Neo4j 匯出 ✅

```bash
brain export --format neo4j > knowledge.cypher
# CREATE (:Rule {id:"r1", title:"JWT RS256"})
# CREATE (:Decision {id:"d1", title:"Use PostgreSQL"})
# MATCH (a:Rule),(b:Decision) WHERE a.id="r1"
# CREATE (a)-[:REQUIRES]->(b)
```

**工作量**: 小（1-2 天）  **影響**: 中（與 Neo4j、Obsidian Canvas 整合）

---

### FEAT-12：匯入衝突互動式解決 ✅

```bash
brain import team_knowledge.json
# 衝突: "JWT must use RS256" 已存在 (confidence=0.9)
# 匯入版本: confidence=0.7, 更新日期: 2025-12-01
# 選項: [k]eep existing  [i]mport new  [m]erge (取最高 confidence)  [s]kip
```

**工作量**: 中（3 天）  **影響**: 高（團隊知識合併場景）

---

### FEAT-13：知識節點生命週期管理 ✅

```bash
brain deprecate <node_id> --replaced-by <new_node_id> --reason "API v2 取代"
brain lifecycle <node_id>
# 狀態: active → deprecated → archived
# 取代節點: <new_node_id> "新版 JWT 規範"
```

**工作量**: 中（3-5 天）  **影響**: 中（長期知識庫治理）

---

### FEAT-14：使用率指標 CSV 匯出 ✅

```bash
brain analytics --period 30d --export csv > report.csv
# node_id, title, access_count, last_accessed, confidence, type
```

**工作量**: 小（1 天）  **影響**: 低（供外部分析工具使用）

---

## 深度功能補完

> 以下三項在 P3 已有骨架，需補完核心邏輯。

### DEEP-02 補完：真實貝葉斯信念傳播 ✅

**現狀**: `brain_db.py` `propagate_confidence()` 骨架方法，無實際圖遍歷計算。

**補完目標**:

```python
def propagate_confidence(self, node_id: str, dampening: float = 0.5,
                         max_hops: int = 3) -> dict[str, float]:
    """
    BFS 遍歷 REQUIRES 邊，計算下游節點的有效信心值。

    傳播公式: conf_downstream = conf_base * (1 - dampening * (1 - conf_upstream))

    Returns: {node_id: effective_confidence} for all affected nodes
    """
    visited = {}
    queue = [(node_id, 1.0, 0)]  # (id, upstream_conf, depth)
    while queue:
        nid, upstream_conf, depth = queue.pop(0)
        if depth > max_hops or nid in visited:
            continue
        node = self.get_node(nid)
        if not node:
            continue
        base = float(node.get("confidence", 0.8))
        effective = base * (1 - dampening * (1 - upstream_conf))
        visited[nid] = round(effective, 4)
        # 繼續遍歷 REQUIRES 下游
        edges = self.get_edges(source_id=nid, relation="REQUIRES")
        for e in edges:
            queue.append((e["target_id"], effective, depth + 1))
    return visited
```

**整合點**: `_effective_confidence()` 可選擇性呼叫 `propagate_confidence()` 獲取更準確的有效值；`health_report()` 應顯示信心傳播警告鏈。

**工作量**: 中（3 天）  **差異化**: 極高

---

### DEEP-04 補完：主動學習回饋迴路 ✅

**現狀**: `NudgeEngine.generate_questions()` 可生成問題，但答案無法回饋更新信心值。

**補完目標**:

```bash
# MCP 工具呼叫流程
generate_questions(task="implement payment")
# 返回: [{"node_id": "n42", "question": "JWT session timeout 目前規定是多少秒?",
#          "current_confidence": 0.38}]

answer_question(node_id="n42", answer="30 分鐘", new_confidence=0.9)
# 效果: update nodes SET confidence=0.9 WHERE id="n42"
#        add_episode(content="[學習迴路] JWT timeout 已確認: 30 分鐘", ...)
```

**新增 MCP 工具**: `answer_question(node_id, answer, new_confidence)` — 將使用者回答存回 `content`，更新 `confidence`，並建立 episode 記錄。

**工作量**: 小（2 天）  **差異化**: 高

---

### DEEP-05：時序邊自動建立 ✅

### DEEP-03 補完：反事實推理強化 ✅

**現狀**: `temporal_edges` 表存在，`temporal_query` MCP 工具存在，但沒有任何代碼自動填充此表。

**補完目標**: `brain sync` / `archaeologist.py` 在解析 git commit 時，自動建立 temporal_edges：

```python
# archaeologist.py — 解析 commit 時加入
for file_path in files_changed:
    component_nodes = graph.find_nodes_by_source(file_path)
    for n in component_nodes:
        brain_db.add_temporal_edge(
            source_id=commit_node_id,
            relation="MODIFIED",
            target_id=n["id"],
            valid_from=commit_time,
            content=commit_message,
        )
```

**效果**: `brain ask "3 個月前這個模組的規則是什麼？"` 可透過 `temporal_query` 真正返回歷史快照。

**工作量**: 中（3-4 天）  **差異化**: 高

---

## 優先矩陣總覽

| ID | 項目 | 類別 | 優先級 | 影響 | 工作量 |
|----|------|------|--------|------|--------|
| DEF-03 | 延遲初始化執行緒鎖 | 缺陷 | ✅ 已完成 | Crash | 小 |
| BUG-09 | 雙 FTS5 索引不同步 | Bug | ✅ 已完成 | 搜尋錯誤 | 中 |
| BUG-12 | Scope 過濾無效 | Bug | ✅ 已完成 | 查詢污染 | 小 |
| DEF-07 | CJK 查詢路徑召回率差 | 缺陷 | ✅ 已完成 | 中文可用性 | 中 |
| DEF-09 | SessionStore 無跨進程鎖 | 缺陷 | ✅ 已完成 | 資料遺失 | 小 |
| BUG-10 | Session 非持久條目不過期 | Bug | ✅ 已完成 | 記憶體洩漏 | 小 |
| BUG-11 | emotional_weight 未用於排名 | Bug | ✅ 已完成 | 排名失準 | 小 |
| DEF-08 | FTS5 遷移非冪等 | 缺陷 | ✅ 已完成 | 索引損壞 | 中 |
| DEF-10 | SR 執行緒競態 | 缺陷 | ✅ 已完成 | 計數不準 | 小 |
| OPT-07 | 消除重複 _ngram() | 優化 | ✅ 已完成 | 維護性 | 小 |
| OPT-08 | FTS5 查詢字串轉義 | 優化 | ✅ 已完成 | 穩定性 | 小 |
| OPT-09 | 排名重複計算 confidence | 優化 | ✅ 已完成 | 性能 | 小 |
| OPT-10 | 向量快取不失效 | 優化 | ✅ 已完成 | 正確性 | 小 |
| DEEP-02 補完 | 貝葉斯傳播實作 | 深度 | ✅ 已完成 | 差異化 | 中 |
| DEEP-04 補完 | 主動學習回饋迴路 | 深度 | ✅ 已完成 | 差異化 | 小 |
| DEEP-05 | 時序邊自動建立 | 深度 | ✅ 已完成 | 時序查詢 | 中 |
| FEAT-12 | 匯入衝突互動式解決 | 功能 | ✅ 已完成 | UX | 中 |
| FEAT-13 | 節點生命週期管理 | 功能 | ✅ 已完成 | 治理 | 中 |
| FEAT-11 | Neo4j/Cypher 匯出 | 功能 | ✅ 已完成 | 生態 | 小 |
| FEAT-14 | 使用率 CSV 匯出 | 功能 | ✅ 已完成 | 分析 | 小 |
| DEEP-03 補完 | 反事實推理強化 | 深度 | ✅ 已完成 | 差異化 | 小 |

---

## 執行時程建議

```
2026-04 Week 2  v1.0.1 Critical Fixes
         ├── DEF-03 (engine.py 延遲初始化執行緒鎖)
         ├── BUG-09 (雙 FTS5 索引統一)
         └── BUG-12 (Scope 過濾實作)

2026-04 Week 3  v1.0.2 Stability
         ├── DEF-07 (CJK 查詢路徑 n-gram)
         ├── DEF-09 (SessionStore 跨進程鎖)
         ├── DEF-08 (FTS5 遷移冪等性)
         ├── BUG-10 (Session 過期修復)
         └── BUG-11 (emotional_weight 加入排名)

2026-05  v1.1.0 Polish & Completions
         ├── OPT-07 ~ OPT-10 (4 項優化)
         ├── DEF-10 (SR 競態)
         ├── DEEP-02 補完 (貝葉斯傳播)
         ├── DEEP-04 補完 (主動學習回饋)
         └── DEEP-05 (時序邊自動建立)

2026-06  v1.2.0 Ecosystem
         ├── FEAT-11 (Neo4j 匯出)
         ├── FEAT-12 (匯入衝突解決)
         ├── FEAT-13 (節點生命週期)
         └── FEAT-14 (CSV 匯出)
```

---

## 附錄：P3 補完進度追蹤

> **最後更新**: 2026-04-03 — P3 全部完成

| P3 功能 | 骨架 | 核心邏輯 | 整合 | 狀態 |
|---------|------|---------|------|------|
| DEEP-01 推理鏈條 | ✅ | ✅ | ✅ 已整合 | ✅ 完成 |
| DEEP-02 貝葉斯傳播 | ✅ | ✅ BFS 多跳 | ✅ | ✅ 完成 (P2) |
| DEEP-03 反事實推理 | ✅ | ✅ + impact_score | ✅ | ✅ 完成 (P3) |
| DEEP-04 主動學習 | ✅ | ✅ 含回饋閉環 | ✅ answer_question | ✅ 完成 (P2) |
| DEEP-05 時序推理 | ✅ | ✅ temporal_edges | ✅ archaeologist | ✅ 完成 (P2) |
| OPT-02 自適應權重 | ✅ | ✅ CJK+長度啟發 | ✅ hybrid_search | ✅ 完成 |
| OPT-03 向量快取 | ✅ | ✅ | ✅ OPT-10 失效修復 | ✅ 完成 (P2) |
| OPT-05 CQRS | ✅ | ✅ | ✅ api_server _read_conn | ✅ 完成 |
| OPT-06 同義詞索引 | ✅ | ✅ | ✅ expand_query O(1) DB | ✅ 完成 |
| FEAT-11 Neo4j 匯出 | ✅ | ✅ Cypher gen | ✅ brain export --format neo4j | ✅ 完成 (P3) |
| FEAT-12 匯入衝突 | ✅ | ✅ 4 策略 | ✅ --merge-strategy interactive | ✅ 完成 (P3) |
| FEAT-13 生命週期 | ✅ | ✅ deprecate/lifecycle | ✅ brain deprecate/lifecycle | ✅ 完成 (P3) |
| FEAT-14 CSV 匯出 | ✅ | ✅ | ✅ brain analytics --export csv | ✅ 完成 (P3) |

### 全域進度總結

| 版本 | 範圍 | 項目數 | 狀態 |
|------|------|--------|------|
| v0.1.1 ~ v1.0.0 | 原始 P0~P3 | 34 | ✅ 全部完成 |
| v1.0.1 | P0 Critical Fixes | 3 | ✅ 全部完成 |
| v1.0.2 | P1 Stability | 5 | ✅ 全部完成 |
| v1.1.0 | P2 Polish & Deep | 8 | ✅ 全部完成 |
| v1.2.0 | P3 Ecosystem | 5 | ✅ 全部完成 |
| **合計** | | **55** | **✅ 全部完成** |

---

## 附錄：參考文件

- `COMPLETED_HISTORY.md` — 已完成改善項目歸檔（v0.1.1 ~ v1.2.0，共 55 項）
- `PROJECT_BRAIN.md` — 核心架構說明
- `CHANGELOG.md` — 版本歷史
- `COMMANDS.md` — CLI 指令參考
- `SECURITY.md` — 安全模型說明
- `tests/` — 測試套件

---

*深度代碼審查於 2026-04-03 完成。全部 55 項改善均已落地（P0~P3 原始 34 項 + 審查後新增 21 項）。*

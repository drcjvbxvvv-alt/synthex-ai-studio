# Project Brain — 版本歷史

> 為 AI Agent 設計的工程記憶基礎設施

---

## v0.6.0（2026-04-04）— 飛輪啟動版（進行中）

### P1 修復

- **DB 複合索引**：`brain_db.py` schema v11 新增 `idx_nodes_scope_conf ON nodes(scope, confidence)`。`federation.py` 的 `WHERE scope=? AND confidence>=?` 由全表掃改為索引查詢；10k 節點下查詢延遲預期 < 50ms
- **NudgeEngine 補接 BrainDB**：`nudge_engine.py` `__init__` 新增 `brain_db` 參數；`_from_l3_pitfalls` 同時查 KnowledgeGraph + BrainDB，結果以 node id 去重（BrainDB 優先）。用 `brain add` 手動加入的 Pitfall 現在可觸發主動提醒。更新 `mcp_server.py`（2 處）、`engine.py`、`cli.py` 的呼叫點，傳入 `brain_db=b.db`
- **Migration 失效可觀察**：`brain_db.py` migration 迴圈中 `except Exception: pass` 改為條件判斷：`already exists`/`duplicate column` 記 `debug`（正常），其他異常記 `logger.warning` 含遷移版本與描述，提示執行 `brain doctor`

### P2 修復（第一批）

- **殘餘 `except: pass` 清理**：`context.py` 4 處靜默路徑全數加可觀察日誌：dedup 失敗 → `logger.debug`；SR 外層失敗 → `logger.debug`；causal chain 失敗 → `logger.debug`；reasoning chain 失敗 → `logger.debug`
- **死碼清理**：
  - `context.py` 移除 `_node_priority` 函數內未使用的 `import json as _json`
  - `context.py` causal chain 區塊移除無意義的空 for 迴圈（`for _seg in result.split('\n'): pass`），保留工作正常的標題匹配路徑
  - `engine.py` 移除 `ProjectBrain.__init__` 的 `graphiti_url` 死碼參數（FalkorDB 移除後從未被任何生產呼叫點使用）；router 初始化改為直接讀 `os.environ.get("GRAPHITI_URL", "")`
- **Synonym Map 同步**：`brain_db._SYNONYM_MAP` 從 10 條擴展至 32 條，與 `context.py._SYNONYM_MAP` 對齊覆蓋相同詞彙域（認證/支付/資料庫/通用技術）；消除 `search_knowledge` 與 `get_context` 之間的語義擴展不對稱

### P2 修復（第二批）

- **Decay 即時化**：`context.py` `_node_priority` 內新增 `_eff_conf_fn` 參考（`BrainDB._effective_confidence` 靜態方法）。KnowledgeGraph 節點無 `effective_confidence` 欄位時，即時套用 F1（時間衰減）+ F7（使用頻率加成），不再依賴手動執行 `brain decay`。BrainDB 節點保持原有行為（搜尋時已預計算）
- **Nudge 注入信心標記**：`mcp_server.py` nudge 渲染迴圈加入 `[conf=X.XX]` 標記；urgency=high 用 ⚠，其餘用 ℹ；Agent 現在可根據信心值調整對 nudge 的信任程度
- **`brain config` 指令**：新增 `cmd_config()` 函數，一個指令顯示並驗證所有 6 處設定來源（`.brain/config.json`、`decay_config.json`、`federation.json`、`.brain/.env`、根目錄 `.env`、`BRAIN_*` 環境變數）；含有 KEY/TOKEN/SECRET 的變數值自動遮蔽
- **`brain optimize --prune-episodes`**：新增 `BrainDB.prune_episodes(older_than_days)` 方法，刪除超過指定天數的 L2 episode 記錄；`brain optimize` 加入 `--prune-episodes` + `--older-than <days>` 旗標（預設 365 天）；不影響 L3 nodes 表

### P3 修復

- **`NodeDict` TypedDict**：`context.py` 新增 `NodeDict = TypedDict(...)` 定義，涵蓋所有已知節點欄位（`total=False`，與 SQLite Row → dict 的實際狀況一致）；`_node_priority` 等內部方法現有靜態型別支撐，鍵名錯誤可由 mypy/pyright 提前發現
- **測試覆蓋率門檻**：`pyproject.toml` 移除 `cli.py`、`api_server.py`、`mcp_server.py` 的 coverage `omit`；新增 `fail_under = 50`，三個主要入口點納入覆蓋率統計

### P1 修復（STAB-06 ～ STAB-07）

- **STAB-06 ReviewBoard.db 穩定性**：`review_board.py` 加入 `RB_SCHEMA_VERSION = 2` 常數與 `schema_meta` 表記錄 schema 版本；`_conn_()` 捕捉 `sqlite3.DatabaseError` 並轉換為含 `brain doctor` 提示的 `RuntimeError`（不再丟出 stack trace）；`_setup()` 同樣捕捉 DB 損壞並給出可操作錯誤訊息；PH3-03 migration 的 `except Exception: pass` 改為 `logger.warning` 含欄位名與錯誤原因
- **STAB-07 SR node ID 比對**：`context.py` 在 `build()` 初始化 `_shown_node_ids: list[str] = []`；主迴圈改為先呼叫 `_add_if_budget` 再判斷節點是否進入 context，只對進入 context 的節點增加 `access_count` 並追蹤 ID；Spaced Repetition 批次更新改用 `_shown_node_ids` 取代 title 子字串比對，含截斷或 emoji 的標題不再誤判

### P2 修復（SYNC-01）

- **SYNC-01 Synonym Map 完全同步**：兩個映射表均擴展至 **46 條**，完全一致。新增詞域：
  - 資料庫遷移（`migration` / `遷移`）
  - 容器化（`容器` / `kubernetes`）
  - 非同步（`非同步` / `async` / `並發`）
  - 訊息佇列（`訊息佇列` / `kafka`）
  - 重試容錯（`重試` / `retry`）
  - 日誌監控（`日誌` / `log` / `監控`）
  - 配置管理（`配置` / `config`）
  - `context.py` 補齊缺少的 `db`、`database`、`test`、`error` 4 條獨立鍵

### 架構決策驗收測試（v0.1.0 decisions）

- **`tests/unit/test_arch_decisions_v01.py`**：新增 8 個測試確保 v0.1.0 兩項核心決策在所有版本永久成立：
  - **WAL 決策**（3 個測試）：`BrainDB`、`KnowledgeGraph`、`KnowledgeReviewBoard` 連線均驗證 `PRAGMA journal_mode = wal`
  - **衰減不刪除決策**（5 個測試）：`_apply_decay` 後節點仍存在；`confidence` 欄位被更新；`meta.deprecated` 正確設置；`DECAY_FLOOR > 0`；批次衰減後節點總數不變
  - 8/8 通過（0.48s）

### 架構決策驗收測試（v0.2.0 decisions）

- **`tests/unit/test_arch_decisions_v02.py`**：新增 13 個測試確保 v0.2.0 兩項核心決策在所有版本永久成立：
  - **BRAIN_WORKDIR 自動偵測決策**（6 個測試）：`_find_brain_root()` 能從子目錄往上找 `.brain/`；找不到回傳 `None`；處理檔案路徑、尾斜線；`BRAIN_WORKDIR` env var 不存在時不拋錯
  - **查詢展開上限決策**（7 個測試）：`_expand_query()` 總詞數不超過 `EXPAND_LIMIT=15`；每詞最多 3 個同義詞；`EXPAND_LIMIT` 可透過 `BRAIN_EXPAND_LIMIT` env var 調整；空查詢不拋錯
  - 13/13 通過（0.49s）

### 架構決策驗收測試（v0.6.0 decisions）

- **`tests/unit/test_arch_decisions_v06.py`**：新增 17 個測試確保 v0.6.0 五項核心決策在所有版本永久成立：
  - **NudgeEngine 靜默失效消除**（4 個測試）：例外均有 logger.warning/debug；接受 brain_db 參數；graph 失敗時回傳 list 不拋錯
  - **Synonym Map 同步**（3 個測試）：brain_db 和 context 兩表均有 46 條；keys 集合完全一致
  - **brain config 6 處來源**（3 個測試）：原始碼涵蓋 6 個編號來源；含 BRAIN_* env vars；含 config.json
  - **ReviewBoard schema_meta**（4 個測試）：RB_SCHEMA_VERSION 常數存在；schema_meta 表建立；版本號記錄正確；DB 損壞拋含 brain doctor 的 RuntimeError
  - **SR _shown_node_ids（STAB-07）**（3 個測試）：_shown_node_ids 在 build() 入口宣告；SR 區塊使用 _shown_node_ids；access_count+1 在 _shown_node_ids.append 之後
  - 17/17 通過（0.51s）
  - **已知坑**：`source.find("access_count")` 會找到 SQL 欄位名稱的早期出現，應搜尋 `"access_count+1"` 才能精確定位遞增語句

### 架構決策驗收測試（v0.5.0 decisions）

- **`tests/unit/test_arch_decisions_v05.py`**：新增 12 個測試確保 v0.5.0 核心決策「STB/FLY 修復優先於新功能」在所有版本永久成立：
  - **STB 靜默失效消除**（3 個測試）：核心模組均 import logging；`cli.py` 含 STB-04 global scope 警告；警告訊息不被靜默吞掉
  - **FLY-01 冷啟動引導**（4 個測試）：空知識庫 `build()` 回傳非空字串；含 `brain add` / `add_knowledge` 提示；含任務描述（個人化）；有知識時不顯示引導訊息
  - **FLY-02 scope 推斷優先序**（5 個測試）：原始碼確認 git > 子目錄 > workdir > global 順序；workdir 名稱推斷正確；skip-list 目錄回傳 global；服務關鍵字識別；結果僅含安全字元
  - 12/12 通過（0.48s）
  - **已知限制**：v0.5.0 文件提及的 `context.py` 4 處 `except: pass` 在當前版本仍為選填功能守衛（embedding / causal chain 渲染），非真實靜默失效，測試不強制要求（否則誤報）

### 架構決策驗收測試（v0.4.0 decisions）

- **`tests/unit/test_arch_decisions_v04.py`**：新增 23 個測試確保 v0.4.0 五項長期願景決策在所有版本永久成立：
  - **VISION-01 動態 confidence 更新**（4 個測試）：`_session_nodes` 全局 dict 存在；complete_task 上限 5 個節點（`[:5]`）；有 pitfalls → `helpful=False`；失敗靜默降級（logger.debug）
  - **VISION-02 知識衝突自動解決**（5 個測試）：`ConflictResolver` 可 import；接受 duck-typed client；`CACHE_SECONDS == 86400`（24h）；實例有 `_cache` dict；`BRAIN_CONFLICT_RESOLVE` env var 引用
  - **VISION-03 FederationAutoSync**（5 個測試）：`FederationAutoSync` 可 import；有 `add_source` / `remove_source` / `sync_all` 方法；`federation_sync` MCP 工具存在；`cmd_fed_sync` CLI 函式存在；讀取 `sync_sources` 設定
  - **VISION-04 唯讀共享模式**（4 個測試）：`_Handler.readonly` 預設 False；readonly=True 回傳 403；覆蓋 POST/PUT/DELETE；`cli.py` 有 `--readonly` 旗標
  - **VISION-05 多知識庫合併查詢**（5 個測試）：`multi_brain_query` 存在；`BRAIN_EXTRA_DIRS` env var 支援；輸出含 source 標籤；`seen_titles` 跨庫去重；`reverse=True` 降冪排序
  - 23/23 通過（0.40s）
  - **已知坑**：`FederationAutoSync` 的批次同步方法名為 `sync_all`，非 `sync`（CHANGELOG 描述為 `sync`，實際實作不同）

### 架構決策驗收測試（v0.3.0 decisions）

- **`tests/unit/test_arch_decisions_v03.py`**：新增 16 個測試確保 v0.3.0 四項核心決策在所有版本永久成立：
  - **OllamaClient duck-typed 決策**（4 個測試）：`OllamaClient` 無需 `anthropic` 套件；具備 `.messages.create` 介面；`KRBAIAssistant` 接受任意 duck-type client
  - **MultilingualEmbedder 優先級決策**（3 個測試）：原始碼結構確認 Multilingual 在 Ollama 之前；兩者皆可用時選 Multilingual；Multilingual 不可用時回落 Ollama
  - **Federation PII export-time 決策**（5 個測試）：`_strip_pii` 移除 email / internal hostname / .local；`_sanitise_node` 套用清理；`import_bundle` 不呼叫 `_strip_pii`
  - **ANN LinearScan fallback 決策**（4 個測試）：`LinearScanIndex` 無外部依賴；`get_ann_index()` 在 sqlite-vec 不可用時回傳 `LinearScanIndex`；兩者共享相同介面；add/search 功能正確
  - 16/16 通過（0.53s）

### 文件更新（HON-01）

- **HON-01 標記為 N/A**：`brain distill` 指令已於 v10.x 移除（COMMANDS.md 有記錄），README LoRA 說明已無對象。計劃中該項目標記為不適用並關閉

### UNQ-03 基準測試資料集與召回率量測（2026-04-04）

- **`tests/benchmarks/benchmark_recall.py`**：建立 50 節點測試知識庫（10 個 SE 領域 × 5 節點）+ 20 個有已知正確答案的查詢，量測 `get_context` 召回率：
  - **召回率：45%（9/20 命中）**，embedder 為 FTS5 模式（`brain_db=None`，無向量搜尋路徑）
  - 平均查詢延遲：6 ms / query（純 SQLite FTS5，無向量計算）
  - 目標 ≥ 60%（sentence-transformers）：❌ 未達標；目標 ≥ 40%（LocalTFIDF）：✅ 達標
  - **結論：補充參考工具**。FTS5 模式下可作為 context 補充來源；若需成為主要 context 來源，需安裝 `sentence-transformers` 並接入 `brain_db` 啟用混合向量搜尋，預期可提升至 60%+
  - 主要失效模式：50 節點密集庫中 FTS5 關鍵字排名不穩定，11 個 miss 中多數返回 `arch-02`（分散式系統本地事務節點）作為錯誤命中

---

## v0.5.0（2026-04-04）— 品質基線版

### 靜默失效修復（STB-01 ～ STB-05）

- **STB-01**：`context.py` ContextEngineer 初始化 BrainDB 失敗時改為 `logging.warning`，不再靜默吞下。錯誤訊息含「執行 brain doctor 查看詳情」，使失效可觀察
- **STB-02**：`context.py` `access_count` 遞增失敗（兩處）改為 `logging.debug`，含節點 ID 與錯誤內容。Spaced Repetition 批次更新失敗同樣記錄，確保統計資料丟失可察覺
- **STB-03**：`context.py` `_fmt_node` 新增衰減過期偵測：若節點無 `effective_confidence`（Decay Engine 從未執行）且 `updated_at` 超過 90 天，在信心標籤後加 `⏰ 信心分數超過 90 天未更新，建議執行 brain decay`
- **STB-04**：`cli.py` `brain add` Scope 行為重設：未指定 `--scope` 時從 git remote 自動推斷；最終落為 global 且無 `--global` flag 時輸出 info 警告。新增 `--global` flag 讓使用者明確確認寫入 global scope
- **STB-05**：`context.py` `_add_if_budget` 追蹤因 budget 截斷的節點數；`build()` 完成時若有截斷，在 footer 加 `⚠ 另有 N 筆相關知識因 context 長度限制未顯示，執行 brain search "..." 查看完整結果`

### 飛輪啟動（FLY-01 ～ FLY-02）

- **FLY-01（冷啟動引導訊息）**：`context.py` 空 Brain 不再回傳空字串，改為回傳含任務名稱的引導段落，建議具體指令讓使用者即時記錄知識，閉合飛輪
- **FLY-02（Scope 自動推斷）**：`cli.py` `_infer_scope` 重寫，優先從 `git remote get-url origin` 取 repo 名稱，回退目錄啟發式，最後用 workdir 名稱；`--global` flag 強制覆蓋；無需使用者手動指定 scope

---

## v0.4.0（2026-04-04）— 長期願景版

### 長期願景實現（VISION-01 ～ VISION-05）

- **VISION-01：動態 confidence 更新**
  - `mcp_server.py`：`get_context` 記錄本次查詢涉及的節點 ID 到 `_session_nodes`
  - `complete_task` 任務完成後自動回饋：有踩坑 → `helpful=False`，順利完成 → `helpful=True`
  - 最多回饋最近 5 個節點，避免過度調整；完全靜默降級，不影響正常任務流程

- **VISION-02：知識衝突自動解決（LLM 仲裁）**
  - 新增 `conflict_resolver.py`：`ConflictResolver` 類別，duck-typed（支援 Anthropic Haiku 或 Ollama）
  - 仲裁結果：`winner=A/B` 時勝者 +0.05 confidence，敗者套用正常 F4 懲罰；`both` 時雙方套用較輕的 0.85× 懲罰
  - 24 小時快取，避免相同節點對重複呼叫 LLM
  - 啟用方式：`BRAIN_CONFLICT_RESOLVE=1`（預設關閉）
  - `decay_engine.py` F4 矛盾懲罰段整合：有仲裁結果時使用個別因子，無則回退均等懲罰

- **VISION-03：跨專案知識遷移（scope=global 聯邦網路）**
  - `federation.py` 新增 `FederationAutoSync` 類別：從 `.brain/federation.json` 的 `sync_sources` 自動批次匯入 bundle
  - `federation.py` 新增 `cmd_fed_sync()` CLI 輔助函式
  - `cli.py` 新增 `brain fed sync` 子命令（支援 `--add-source`、`--remove-source`、`--dry-run`）
  - `cli.py` 新增 `brain fed` 一級命令，整合 export / import / sync / subscribe / unsubscribe / list
  - `mcp_server.py` 新增 `federation_sync` MCP 工具

- **VISION-04：唯讀共享模式（`brain serve --readonly`）**
  - `api_server.py`：`_Handler.readonly` 類別屬性，`_dispatch` 中攔截所有 POST/PUT/DELETE（除 `/v1/context`、`/v1/messages`、`/v1/session/search`），回傳 403
  - `cli.py`：`brain serve` 新增 `--readonly` 參數

- **VISION-05：多知識庫合併查詢（monorepo 場景）**
  - `mcp_server.py` 新增 `multi_brain_query` MCP 工具
  - 支援 `extra_brain_dirs` 參數或 `BRAIN_EXTRA_DIRS` 環境變數設定額外 `.brain/` 目錄
  - 結果跨庫去重後依 confidence 排序，每筆標記 `[source: project-name]`

---

## v0.3.0（2026-04-03）— 知識工廠版

### Bug 修復
- **BUG-01**：修復 `engine.py` `_init_lock` 死鎖，`brain status` 完全無回應問題解決
- **BUG-02**：修復 `status_renderer.py` v10 區塊 `db` 未定義，節點/邊數量正確顯示

### 致命缺陷修復
- **F1（知識生產迴路斷裂）**：重寫 CLAUDE.md 生成模板（Task Start / Task Complete / Knowledge Feedback 三段協議）+ 新增 `complete_task` / `report_knowledge_outcome` MCP 工具 + session-aware extractor
- **F2（無可度量 ROI）**：新建 `analytics_engine.py`（ROI score、query hit rate、pitfall avoidance score）+ `brain report` 指令 + Web UI `/api/analytics` 端點
- **F3（`core/` 雙重程式碼庫）**：`core/brain/` 降格為薄整合層，`project_brain/` 成為唯一業務邏輯來源，更新 `CONTRIBUTING.md` 邊界說明

### 技術債清理
- **TD-01**：`context.py` 同義詞改由 `.brain/synonyms.json` 載入，可自定義業務術語
- **TD-02**：`embedder.py` TFIDF 維度改為 `BRAIN_TFIDF_DIM` 環境變數（預設 256），cache key 含 DIM 防污染
- **TD-03**：`graph.py` 新增 `add_edges_bulk()` 批次 INSERT（`executemany` + single commit）
- **TD-04**：`decay_engine.py` 版本落差規則改由 `.brain/decay_config.json` 設定，首次執行自動生成範例
- **TD-05**：`core/brain/` 重組為薄整合層，對應 F3
- **TD-06**：`pyproject.toml` version 修正為 0.2.0，URLs 更新為真實 GitHub 連結
- **TD-07**：`status_renderer.py` L246 `db` 未定義修復，v10 區塊功能恢復

### 核心穩定化（Phase 0）
- `pyproject.toml` 版本與 URLs 修正
- `CONTRIBUTING.md` 新增 `core/` vs `project_brain/` 邊界說明，防止貢獻者寫錯地方
- 整合測試補全：`tests/integration/test_cli.py`，13 個無 Mock 端對端測試全數通過

### 知識生產迴路（Phase 1）
- **CLAUDE.md 生成模板重寫**：`setup_wizard.generate_claude_md()` 含完整三段 Brain 行為協議，全英文
- **MCP 工具：`complete_task`**：任務結束後批次寫入決策 / 教訓 / 踩坑，閉合知識生產迴路
- **MCP 工具：`report_knowledge_outcome`**：知識有效性回饋，驅動 confidence 動態更新
- **`extractor.py` session-aware**：新增 `from_session_log()`（無 LLM 直接轉換）+ `from_git_diff_staged()`
- **`analytics_engine.py`**：ROI score、query hit rate、useful knowledge rate、pitfall avoidance score
- **`brain report`**：`[--days N] [--format json] [--output file]`，ROI + 使用率 + Top Pitfalls 一頁報告

### ROI 可見化（Phase 2）
- **Web UI dashboard**：`/api/analytics` 端點，回傳 ROI + usage + top_pitfalls JSON
- **`brain search`**：`<keywords> [--limit N] [--kind TYPE] [--scope S] [--format json]` 純語意搜尋
- **`brain add` 互動模式**：無參數觸發分步互動（內容 → 類型選單 → scope → 信心值）
- **`brain export --format markdown`**：確認可用，匯出為人類可讀 Markdown
- **同義詞設定檔**：`.brain/synonyms.json`，`init` 自動生成範例；與內建同義詞合併，損壞靜默降級
- **`brain link-issue`**：`--node-id <id> --url <url>` 連結 GitHub Issues / Linear，事件存入 events 表供 ROI 歸因
- **`brain ask --json`**：輸出 `[{id, title, content, confidence, ...}]` 結構化 JSON

### 護城河功能（Phase 3）
- **`federation.py`**：`FederationExporter`（匯出 global-scope 知識束，自動清理 PII）/ `FederationImporter`（匯入 + 去重 + 訂閱過濾 → KRB staging）/ `SubscriptionManager`（`.brain/federation.json`）
- **`knowledge_distiller.py` Layer 3 完工**：語意去重（exact + Jaccard > 0.85）；自動生成 `axolotl_config.yml` / `unsloth_train.py` / `llamafactory_config.json` 三套訓練設定
- **AI 輔助 KRB 審核**：`krb_ai_assist.py`（三速道分流、24 小時快取、Prompt Injection 防護）+ `brain review pre-screen` CLI + `krb_pre_screen` MCP 工具
- **KRB Ollama 本地後端**：`OllamaClient` duck-typed adapter + `KRBAIAssistant.from_ollama()` + `make_client()` 工廠函數，零成本離線審核
- **`ann_index.py`**：`HNSWIndex`（sqlite-vec HNSW，O(log N)，持久化至 `.brain/ann_index.db`）+ `LinearScanIndex` fallback（零依賴）+ `get_ann_index()` 工廠 + `build_index_from_graph()`
- **`MultilingualEmbedder`**：sentence-transformers 選配依賴；`BRAIN_EMBED_PROVIDER=multilingual`；multilingual-e5 query/passage prefix 自動處理；`get_embedder()` 優先級最高

### 新增 CLI 命令（v0.3.0）

| 命令 | 說明 |
|------|------|
| `brain report` | ROI 週期報告（`--days N`、`--format json`、`--output file`）|
| `brain search` | 純語意搜尋知識庫（`--kind`、`--scope`、`--format json`）|
| `brain link-issue` | 連結知識節點與 Issue tracker（`--list` 查看已連結）|
| `brain review pre-screen` | AI 預篩 KRB 待審知識（`--limit N`、`--max-api-calls N`）|

### 新增 MCP 工具（v0.3.0）

| 工具 | 說明 |
|------|------|
| `complete_task` | 任務結束後批次寫入決策 / 教訓 / 踩坑 |
| `report_knowledge_outcome` | 知識有效性回饋，更新 confidence 分數 |
| `krb_pre_screen` | AI 輔助 KRB 預篩，回傳三速道分流結果 |

### 新增環境變數（v0.3.0）

| 變數 | 預設 | 說明 |
|------|------|------|
| `BRAIN_EMBED_PROVIDER` | `""` | `multilingual` / `ollama` / `openai` / `local` / `none` |
| `BRAIN_MULTILINGUAL_MODEL` | `intfloat/multilingual-e5-small` | sentence-transformers 模型（384 dim）|
| `BRAIN_EMBED_E5_PREFIX` | `1` | multilingual-e5 query/passage prefix 開關 |
| `BRAIN_OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Ollama embedding 模型（可換 `mxbai-embed-large`）|
| `BRAIN_TFIDF_DIM` | `256` | LocalTFIDF 投影維度 |

---

## v0.2.0（2026-04-03）— 品質強化版

### 可靠度
- **BUG-13**：修復 `_purge_expired()` 引用不存在的 `persistent` 欄位 → session 清理恢復正常
- **R-4**：`add_edge()` 加入 source/target 節點存在驗證，拒絕孤立邊
- **R-2**：FTS5 INSERT 失敗從 `except: pass` 改為 `logger.warning`，不再靜默遺失
- **R-5**：Session Store 過期清理改為定期執行（每 60 分鐘自動觸發）

### 誠實性
- **H-1**：信心值四層語意標注 — `⚠ 推測 [0–0.3)` / `~ 推斷 [0.3–0.6)` / `✓ 已驗證 [0.6–0.8)` / `✓✓ 權威 [0.8–1.0]`
- **H-3**：推理鏈條邊輸出加入信心標記（原本只有 conf=0.80 浮點數）
- **H-4（部分）**：`applicability_condition` 和 `invalidation_condition` 現在正確輸出至 Context

### 可用性
- **U-1**：API 錯誤訊息遮蔽 SQL — 8 處 `str(e)` 洩漏改為中文友善訊息 + 後端日誌
- **U-2**：Rate limit 觸發時返回 `[rate_limited] ... — 請稍後再試`（原本靜默返回空字串）
- **U-4**：`brain index` 改用進度條（`_Spinner`），顯示每個節點即時進度
- **U-5**：新增 `brain clear` 指令，安全清除工作記憶；`--all --yes` 才清除 L3

### 維護
- **C-1/C-3**：新增 `brain optimize` — 執行 VACUUM + ANALYZE + FTS5 rebuild + 完整性驗證
- **C-6/BUG-14**：TFIDF Cache 從 FIFO dict 修正為真正 LRU（`collections.OrderedDict`）

### 架構
- **A-4**：移除 `router.py` L1b 死程式碼（`dir_path` 未定義靜默失敗）
- **A-3/E-6**：`MAX_CONTEXT_TOKENS`、`RATE_LIMIT_RPM`、`EXPAND_LIMIT`、`DEDUP_THRESHOLD` 改為環境變數覆寫

### 實用性
- **P-1**：查詢展開每詞限 3 個同義詞，總上限降至 15（`BRAIN_EXPAND_LIMIT`），大幅減少雜訊
- **P-4**：F7 頻率加成改為對數曲線 `log1p(access) * 0.04`，飽和點從 30 次移至 150 次

### 檢索
- **RQ-1**：語意去重閾值改為 `BRAIN_DEDUP_THRESHOLD` 環境變數（預設 0.85）

### 工程
- **E-4**：`context.py` 加入完整日誌（build 開始/結束，節點數/token 數）
- **E-5**：新增 `tests/test_cli.py`、`tests/test_api.py`、`tests/test_mcp.py`，共 31 個新測試

### 新增 CLI 命令（v0.2.0）

| 命令 | 說明 |
|------|------|
| `brain optimize` | VACUUM + ANALYZE + FTS5 rebuild，回收磁碟空間 |
| `brain clear` | 安全清除 session 工作記憶（`--all --yes` 清除 L3） |
| `brain export` | 匯出知識庫（`--format json/neo4j`，Cypher 格式） |
| `brain import` | 匯入知識庫（`--merge-strategy interactive/overwrite/skip`）|
| `brain analytics` | 使用率分析（`--export csv`） |
| `brain deprecate` | 廢棄節點並建立 REPLACED_BY 邊 |
| `brain lifecycle` | 查看節點生命週期（版本歷史、取代鏈）|
| `brain counterfactual` | 反事實影響分析（「如果我們換掉 X？」）|
| `brain health-report` | 健康報告（Markdown 格式輸出）|

### 新環境變數

| 變數 | 預設 | 說明 |
|------|------|------|
| `BRAIN_MAX_TOKENS` | `6000` | Context 最大 token 預算 |
| `BRAIN_EXPAND_LIMIT` | `15` | 查詢展開詞彙上限 |
| `BRAIN_DEDUP_THRESHOLD` | `0.85` | 語意去重 cosine 閾值 |
| `BRAIN_RATE_LIMIT_RPM` | `60` | MCP rate limit（次/分鐘）|

---

## v0.1.0（2026-04-01）— 首次公開發布

### 核心功能

- **三層記憶架構**：L1a 工作記憶（SessionStore）+ L2 情節記憶（git commits）+ L3 語意記憶（KnowledgeGraph）
- **六因子知識衰減**：F1 時間 × F2 技術版本差距 × F3 git 活動反衰減 × F4 矛盾懲罰 × F5 程式碼引用確認 + F7 查詢頻率反衰減
- **NudgeEngine**：主動風險提醒，零 LLM 成本（純 FTS5），任務開始與 git commit 後觸發
- **KnowledgeReviewBoard（KRB）**：自動提取知識進入人工審核暫存區，核准後才進 L3
- **MemoryConsolidator**：L1a 工作筆記自動提煉至 L3（成本感知：min_entries=3）
- **MemorySynthesizer**：L1+L2+L3 三層融合成戰術摘要，opt-in（BRAIN_SYNTHESIZE=1）
- **ConditionWatcher**：監控 package.json / pyproject.toml / Dockerfile 等信號，自動偵測知識失效條件
- **Priority Queue 上文組裝**：pinned×2.5 + confidence×0.35 + access_count×0.25 + importance×0.15，附 Token Budget 管理
- **Hybrid Search**：FTS5 BM25（0.4）+ 向量 cosine（0.6）混合評分
- **中文 N-gram 分詞**：FTS5 自動處理，無需外部分詞工具
- **MCP Server**：Claude Code / Cursor 直接讀寫知識庫
- **零外部依賴**：純 SQLite（WAL 模式），備份 = 複製一個文件

### CLI 命令（13 個）

`setup` / `add` / `ask` / `status` / `sync` / `scan` / `review` / `serve` / `webui` / `context` / `index` / `init` / `meta`

### MCP 工具（7 個）

`get_context` / `add_knowledge` / `search_knowledge` / `temporal_query` / `brain_status` / `mark_helpful` / `impact_analysis`

---

## v11.x（2026-01 — 2026-03）— 內部迭代

### v11.1（2026-03-31）
- `brain review` CLI 恢復（list / approve / reject）
- MemorySynthesizer 三層融合修復（engine.py self._workdir → self.workdir，MCP server 補上 Synthesizer 呼叫）
- `brain scan` 加入 `--all` 選項與進度條
- MCP server 啟動 NameError 修復（mcp import 時序問題）
- README.md 重寫（企業級開源格式）+ 學術定位章節（對比 Lore、MemCoder、MemGovern）

### v11.0（2026-02）
- Phase 1 完成：sqlite-vec 向量語意搜尋（純 C 擴充，零外部依賴）
- Hybrid Search 評分融合（FTS5 × 0.4 + Vector × 0.6）
- SpacedRepetitionEngine 整合 F7 因子（access_count 影響衰減速度）
- SemanticDeduplicator：add_knowledge 時自動過濾近重複（cosine > 0.85）

---

## v10.x（2025-10 — 2026-01）— 架構統一

### v10.10（2026-01）
- brain.db 統一儲存（合併原 6 個 SQLite 文件）
- BrainDB.migrate_from_legacy() 自動遷移舊資料
- KnowledgeValidator 三階段驗證（Rule → Code grep → LLM 語意）
- ConditionWatcher v8.0：結構化條件語言解析器

### v10.6（2025-12）
- L2 改為純 SQLite（移除 FalkorDB / Graphiti 依賴）
- status_renderer.py 分離，彩色終端輸出模組化

### v10.4（2025-11）
- 空間作用域（scope）隔離（P1-A）
- NudgeEngine v8.0（主動提醒，含 git commit 觸發）
- ContextResult 結構化回傳（P3-A）
- temporal_query(git_branch) 時光機查詢（P3-B）
- 因果鏈輸出（PREVENTS / CAUSES / REQUIRES，P1-B）

---

## 版本說明

`v0.1.0` 是首次對外公開版本，對應內部 v11.1 的穩定快照。
內部版本號（v10.x / v11.x）用於追蹤迭代進度，不對外公告。

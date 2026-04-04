# Project Brain — 版本歷史

> 為 AI Agent 設計的工程記憶基礎設施

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

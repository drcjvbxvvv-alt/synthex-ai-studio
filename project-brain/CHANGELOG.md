# Project Brain — 版本歷史

> 為 AI Agent 設計的工程記憶基礎設施

---

## v0.60.0（2026-05-03）— Phase G 檢索品質深化：hybrid ranking recall@3=97%

> Hybrid ranking（FTS5 + vector）正式啟用為 eval 預設模式。
> recall@3 從 FTS5-only 的 29% 提升至 97%，MRR 從 0.269 提升至 0.915。

### G-01：Hybrid Ranking 確認與 eval 預設啟用

- `brain eval run` 預設使用 hybrid 模式（`use_hybrid=True`），反映實際使用體驗
- Eval 結果：recall@3=97%, noise@3=67.7%（理論下限 66.7%）, MRR=0.915
- 所有類型 recall@3：Decision 100%, Pitfall 97%, Rule 94%

### G-02：Minimum Relevance Threshold

- `hybrid_search()` 新增 `min_score` 參數（float, default None）
- `ContextEngineer._search_batch()` 使用 `min_score=0.15` 過濾低相關結果
- `RecallEvaluator.run()` 新增 `min_score` 參數，支援 threshold 實驗

### G-03：Rule 類型檢索增強

- Rule recall@3 在 hybrid 模式下已達 94%（FTS5-only 為 20%），不需額外增強

### G-04：Traces 增長調查

- 當前 traces = 1,737 條，sampling rate = 5（每 5 次查詢記錄 1 次），正常運作
- 深度審查的 14,997 figure 來自不同 `.brain/` 快照

### H-03：使用者指南完整化（874 → 1214 行）

- 新增 §8.4 MCP Tool 完整參數參考（18 個 tools 全參數表，含 `<details>` 展開）
- 新增 §12.4 Federation 自動同步使用說明
- 新增 §12.5 多庫合併查詢（Monorepo）使用方式
- 新增 §12b 故障排除（常見錯誤表 + MCP/搜尋/衰減問題解法）
- 擴充 §14.2 brain.toml 完整參考（embedder/team/federation/session 全段落）
- 新增 §14.3 Embedder 選擇指南
- FAQ 從 8 題擴充至 11 題（匯入文件、git 關係、升級方式）

### H-02：mcp_server.py 按 domain 拆分（2,059 → 539 行）

- `mcp_server.py` 從 2,059 行精簡至 539 行（BrainServer + factory + CLI）
- 新增 `interfaces/mcp_tools/` 模組：
  - `knowledge_tools.py`（495 行）— get_context, search, add, batch_add, answer_question
  - `feedback_tools.py`（301 行）— mark_helpful, report_knowledge_outcome, complete_task
  - `federation_tools.py`（299 行）— federation_sync, multi_brain_query, push_to_central
  - `pipeline_tools.py`（173 行）— auto_resolve, generate_questions, krb_pre_screen
  - `admin_tools.py`（147 行）— brain_status, impact_analysis, temporal_query
  - `reasoning_tools.py`（41 行）— reasoning_chain
  - `maintenance.py`（127 行）— decay/cleanup 維護週期邏輯
- Tool registry 機制：`register_all_tools(mcp, srv, helpers)` 自動載入所有模組
- 公開 API 零 breaking change（create_server、BrainServer、module-level 變數全保留）

### H-01：brain_db.py 拆分（2,850 → 760 行）

- `brain_db.py` 從 2,850 行精簡至 760 行（facade + connection + schema check）
- 新增 `storage/repositories/` 模組：
  - `node_repo.py`（359 行）— 節點 CRUD
  - `search_repo.py`（565 行）— FTS5 + hybrid search
  - `analytics_repo.py`（588 行）— 統計/分析查詢
  - `migration_repo.py`（442 行）— schema migration v1→v29
  - `misc_repo.py`（342 行）— federation/lifecycle 等雜項
- 新增 `storage/write_context.py`（204 行）— 寫入上下文管理
- `BrainDB` 公開 API 零 breaking change，所有既有 import path 仍可用

### 測試

- 新增 9 個 hybrid ranking 測試（`test_hybrid_ranking.py`）
- 1750 passed, 0 failed, 1 skipped（不含 chaos/benchmark）

---

## v0.54.0（2026-05-03）— Phase F 品質收斂：恢復測試全綠 + 靜默例外清理

> 從 15 failures 恢復至 0 failures（1741 passed）。靜默例外從 40 降至 19。
> ROADMAP.md 升級至 v3.0，規劃 Phase F-I 完整路線圖。

### F-01：Prometheus 測試 fixture 隔離修復

- `test_prometheus.py` `_run_asgi()` 改用 `asyncio.run()` 取代 `asyncio.get_event_loop().run_until_complete()`
- 根因：其他測試消費 MainThread event loop 後，`get_event_loop()` 拋出 RuntimeError
- 12/12 測試在全量 suite 中通過

### F-02：靜默例外審計與清理（40 → 19）

- `web_ui/server.py` 21 處 `except Exception: pass` 全部改為帶日誌的降級處理
  - 7 處改為 `logger.warning()`（FTS 寫入、config 解析、API key 查詢等）
  - 14 處改為 `logger.debug()`（FTS 表探測、可選統計查詢、feature detection 等）
- 剩餘 19 處分佈：brain_db 7 + mcp_server 5 + context 4 + health 3（歷史核心模組合理降級）

### F-bonus：Flaky test 修復

- `test_query_has_elapsed_ms`：`assertGreater(elapsed_ms, 0)` → `assertGreaterEqual(elapsed_ms, 0)`
- 0ms 在快速環境中合法，修復偶發 flaky

### ROADMAP v3.0

- 更新系統現況快照至 v0.53.1 基準
- 新增 Phase F（品質收斂）、G（檢索品質深化）、H（架構債清理）、I（生產深化）
- 完整依賴關係圖 + 並行開發策略甘特圖
- 更新品質門檻表至 Phase F-I

### 測試

- 1741 passed, 0 failed, 1 skipped（不含 chaos/benchmark）
- WebUI 59 tests 全部通過
- docs_accuracy 51 tests 全部通過
- silent_exception_audit 5 tests 全部通過

---

## v0.53.1（2026-05-02）— WebUI 前端重構：從 f-string 分離為獨立檔案

> server.py 從 3793 行減至 1966 行。CSS/JS/HTML 各自獨立，IDE 完整支援。
> 消除 f-string 雙大括號轉義導致的中文亂碼問題。

### 結構變更

```
web_ui/
├── server.py          ← 僅 Python API 路由（1966 行）
├── static/
│   ├── style.css      ← 所有 CSS（439 行）
│   └── app.js         ← 所有 JS（1137 行）
└── templates/
    └── index.html     ← HTML 骨架（311 行）
```

### 技術細節

- `_render_template()` 讀取 `templates/index.html`，替換 `{{PROJECT}}` / `{{VERSION}}`
- `/static/<path>` 路由提供靜態檔案，帶 1 小時 Cache-Control
- `_generate_html()` 保留為向後相容 wrapper
- 路徑遍歷防護：filename 只允許 `[a-zA-Z0-9._-]`

### 測試

- 新增 9 個測試：靜態檔案服務 (4) + 模板渲染 (5)
- 全部 103 個 WebUI 測試通過

---

## v0.53.0（2026-05-02）— E-06 運維 Agent 整合：WebUI 管理面板 + Prometheus 監控

> 非技術人員可在瀏覽器中新增知識、瀏覽儀表板、查閱審計日誌。
> 系統管理���可透過 Prometheus /metrics 端點整合 Grafana 監控。
> Phase E 全部完成。

### WebUI 新增知識（免 CLI）

- **`POST /api/node`** — 從 WebUI 新增知識節點（標題、內容、類型、信心度）
- 自動產生 node ID（`webui-<hash>`），同步 FTS5 索引
- 完整輸入��證（必填欄位、長度限制、信心度範圍、有效類型檢查）

### 儀表板（Dashboard）

- **`GET /api/admin/dashboard`** — 知識庫統計總覽
  - 知識總量、關係數、類型分佈、低信心度統計
  - 近期活動（今天/本週/本��新增數）
  - KRB 待審數量、Signal 佇列���態
  - 系統健康摘要（warnings/errors 計數）

### 審計日誌（Audit Log）

- **`GET /api/admin/audit-log`** — 知識變更追蹤
  - 資料來源：`node_history`（修改紀錄）+ `staged_nodes`（KRB 審核紀錄）
  - 支援篩選：天數範圍、操作者、動作類型
  - 支援分頁

### 系統設定面板（Settings）

- **`GET /api/admin/settings`** — 系統設定與服務狀態
  - 顯示運行模式、Embedding、LLM、Schema 版本
  - 服務狀態檢查（brain.db、Central Brain）
  - 儲存空間統計（DB 大小、備份數量）

### Prometheus /metrics 端點

- **`GET /metrics`** — Prometheus text format 指標
  - `brain_nodes_total{kind="..."}` — 各類型知識節點��
  - `brain_staging_pending` — KRB 待審數
  - `brain_api_keys_active` — 活躍 API key 數
  - `brain_signal_queue_pending` — Signal 佇列待處理數
  - `brain_db_size_bytes` — 資料庫大小
  - `brain_info` ��� 版本與模式資訊
- `/metrics` 和 `/health` 免驗證（exempt from auth + rate limiting）

### WebUI 前端

- 新增 5 個檢視標籤：圖譜、管理、儀表板、審計、設定
- 「+ 新增知識」按鈕：中文類型選單、信心度滑��、即時驗證
- 儀表板：卡��式統計、類型分佈、近期活動、健康狀態
- 審計日誌：表格展�� + 篩選 + 分頁
- 系統設定：服務狀態指示燈、儲存空間統計

### 測試

- **`tests/unit/test_webui_admin.py`**（新建）— 24 tests：Add Knowledge 9, Dashboard 5, Audit Log 5, Settings 5
- **`tests/unit/test_prometheus.py`**（新建）— 12 tests：Prometheus 格式驗證、指標正確性、向下相容

### 修改的檔案

| 檔案 | 修改類型 |
|------|---------|
| `project_brain/interfaces/web_ui/server.py` | 新增 API endpoints + 前端頁面 |
| `project_brain/interfaces/http_transport.py` | /metrics Prometheus endpoint |
| `tests/unit/test_webui_admin.py` | **新建** — 24 tests |
| `tests/unit/test_prometheus.py` | **新建** — 12 tests |

---

## v0.52.0（2026-05-02）— E-05 個人知識推送到集中庫 + API Key 管理

> 本地知識可推送到 Central Brain（KRB staging 待審），admin 可用 `--direct` 直接寫入 L3。
> 新增 API key 管理 CLI（create-key / list-keys / revoke-key）。
> 新增 26 tests + 2 test files，新建 3 個模組。

### Push to Central

- **`integrations/push_central.py`**（新模組）：`PushTransport` — 節點篩選、PII 清理、推送
  - `select_nodes(brain_db, kind, min_confidence, scope, max_nodes)` — SQL 篩選
  - `sanitize_nodes(nodes)` — 複用 federation `_strip_pii`
  - `push(client, nodes, direct=False)` — 逐一呼叫 `CentralBrainClient.add_knowledge`
  - `preview(nodes)` — dry-run 預覽
- **`CentralBrainClient.add_knowledge()`**（新方法）— 透過 MCP JSON-RPC 呼叫 remote `add_knowledge` tool

### API Key 管理 CLI

```bash
brain admin create-key --role contributor --name "Alice"  # 產生 brn_c_xxx token
brain admin list-keys                                      # 列出所有 key
brain admin revoke-key <key_id>                            # 撤銷
```

### `push_to_central` MCP Tool

- 參數：`node_ids`（指定推送）或 `kind` + `min_confidence`（篩選推送）
- 權限：contributor+（RBAC via `_check_permission`）
- 自動讀取 `brain.toml [team]` 的 target URL 和 key

### `brain push` CLI

```bash
brain push --to <url> --key <key> --kind Pitfall --min-confidence 0.8 --dry-run
brain push --kind Rule  # 使用 brain.toml [team] 設定
```

### 測試

- `tests/unit/test_push_central.py`（18 tests）：select/sanitize/push/tags/RBAC
- `tests/unit/test_admin_keys_cli.py`（8 tests）：create/list/revoke round-trip

---

## v0.51.0（2026-05-02）— E-04 知識 Ingestion Pipeline

> 從本地 Markdown 檔案和 GitHub Issues/PRs 自動匯入知識到 Brain。
> 共用 pipeline：chunking → LLM/啟發式提取 → dedup → 寫入（L3 或 KRB staging）。
> 新增 42 tests + 3 test files，新建 6 個模組（`integrations/ingest/` package）。

### Ingestion 基礎架構

- **`integrations/ingest/base.py`**：`RawDocument`、`KnowledgeCandidate`、`IngestResult` dataclasses
- **`integrations/ingest/chunker.py`**：`TextChunker` — Markdown heading 切分、CJK token 估算、長段落二次切分
- **`integrations/ingest/pipeline.py`**：`IngestPipeline` 協調器
  - LLM 提取模式（JSON prompt → structured extraction）
  - 啟發式提取模式（keyword-based kind detection，零 LLM 依賴）
  - 三層 dedup（exact title match → FTS5 search → Jaccard token overlap ≥ 0.8）
  - Confidence routing：≥ 0.7 → L3 直接寫入，< 0.7 → KRB staging
  - Dry-run 模式（`--dry-run`）
  - LLM rate limiting（預設 10 calls/min）

### 資料源

- **`integrations/ingest/files.py`**：`LocalFilesIngestSource` — 遞迴掃描 Markdown、glob pattern filter、heading 分段
- **`integrations/ingest/github.py`**：`GitHubIngestSource` — stdlib urllib REST API、issues/PRs fetch、label → kind hint mapping

### CLI 命令

```bash
brain ingest files --path ./docs [--glob "**/*.md"] [--dry-run]
brain ingest github --repo org/repo --token $GH_TOKEN [--types issues,prs] [--dry-run]
```

### 測試

- `tests/unit/test_ingest_chunker.py`（14 tests）：heading split、token estimation、CJK、long split
- `tests/unit/test_ingest_files.py`（11 tests）：scan、glob、nested dir、single file、empty skip
- `tests/unit/test_ingest_pipeline.py`（17 tests）：heuristic/LLM extraction、dedup、routing、dry-run

---

## v0.50.0（2026-05-02）— E-03 Client Connect 疊加查詢

> 個人 Claude Code 可連接 Central Brain，支援 overlay（本地優先 + fallback）、
> central-only、local-only 三種查詢模式。新增 `brain connect` CLI 命令。
> 新增 24 tests + 2 test files，新建 `central_brain_client.py` + `cli_connect.py`。

### TeamConfig — brain.toml `[team]` section

- `TeamConfig` dataclass：`central_brain_url`、`central_brain_key`、`mode`、`overlay_threshold`
- `BrainConfig` 新增 `team` field，`_build_config()` 解析 `[team]` section
- 環境變數覆蓋：`BRAIN_TEAM_URL`、`BRAIN_TEAM_KEY`、`BRAIN_TEAM_MODE`

### CentralBrainClient

- **`project_brain/integrations/central_brain_client.py`**（新模組）
- 使用 `urllib.request`（stdlib）呼叫 Central Brain HTTP MCP endpoint
- `ping()` → `/health` 連線檢查
- `search_knowledge(query, top_k)` → JSON-RPC `tools/call` → 知識搜尋
- `get_context(task)` → JSON-RPC `tools/call` → AI context
- MCP streamable-http session management（`initialize` + `notifications/initialized`）
- 完全容錯：網路錯誤/timeout 返回空結果，不影響本地 brain

### Overlay 查詢整合

- `get_context` MCP tool：overlay 模式下本地結果不足（< 100 chars）時 fallback central
- `search_knowledge` MCP tool：overlay 模式下本地結果不足時補充 central 結果（title dedup）
- central-only 模式跳過本地搜尋
- Central 結果加 `🌐 Central Brain` header 或 `[central]` source 標記

### `brain connect` CLI 命令

- `brain connect <url> --key <key> --mode overlay` — 設定連線
- `brain connect --test` — 測試連線可用性
- `brain connect --status` — 顯示連線狀態
- `brain connect --disconnect` — 中斷連線（回到 local-only）
- 讀寫 `.brain/brain.toml [team]` section，保留其他 section

### 測試

- `tests/unit/test_central_brain_client.py`（10 tests）：mock HTTP server、ping、search、context、graceful degradation、SSE parsing
- `tests/unit/test_team_config.py`（14 tests）：defaults、TOML parsing、env override、connect/disconnect、mode validation

---

## v0.49.0（2026-05-02）— E-02 補完：Write Queue 序列化 + RBAC

> 完成 E-02 Central Brain 模式剩餘功能：寫入佇列序列化（100 threads 0 丟失）、
> RBAC 基礎（API key 角色管理 + 權限檢查）、`--mode central` CLI flag。
> 新增 33 tests + 2 test files，新建 `rbac.py` 模組。

### Write Queue 序列化

**問題**：原有 `threading.RLock()` 在高並發下僅能保證 ~90% 寫入成功（SQLite busy timeout）。

**修復**：
- `BrainDB(serialized_writes=True)` 新增 `queue.Queue` + background worker thread
- 所有寫入經 FIFO 佇列序列化，worker thread 逐一執行
- `_WriteRequest` dataclass 支持 SQL 語句和 callable 兩種模式
- `@_serialize_if_needed` decorator 自動路由 `add_node`、`update_node`、`delete_node`、
  `deprecate_node`、`add_episode`、`add_temporal_edge` 6 個多語句原子方法
- `_execute_write` / `_execute_writescript` 在 serialized mode 自動 enqueue
- `close()` 送 poison pill 並 join worker thread
- **驗收**：100 threads × 10 writes = 1000 rows，0 丟失 ✅

### RBAC 基礎

- **`project_brain/rbac.py`**（新模組）：`ROLE_HIERARCHY`、`TOOL_PERMISSIONS`、`has_permission()`
- **Schema v29**：`api_keys` table（`key_hash` SHA-256, `role`, `name`, `expires_at`, `is_revoked`）
- `BrainDB.store_api_key(token, role, name)` / `resolve_api_key(token)` / `revoke_api_key(key_id)` / `list_api_keys()`
- `AuthMiddleware` 支持雙模式：legacy 單 key（admin）+ RBAC key resolution
- `contextvars.ContextVar("brain_role")` 傳遞角色到 MCP tool handlers
- `add_knowledge`、`complete_task`、`report_knowledge_outcome` 加入權限守衛

### Central mode CLI

- `brain serve --mcp --mode central` 啟動寫入佇列 + RBAC
- `BrainServer(mode="central")` → `ProjectBrain(serialized_writes=True)` → `BrainDB(serialized_writes=True)`
- `/health` 端點新增 `"mode": "central"` 欄位
- `brain health` 新增 `_check_central_mode()` 顯示 RBAC 狀態

### 測試

- `tests/unit/test_write_queue.py`（14 tests）：基本寫入、100-thread stress、錯誤傳播、shutdown、讀取不阻塞
- `tests/unit/test_rbac.py`（19 tests）：permission 層級、API key round-trip、expiry、revoke、schema v29

---

## v0.48.0（2026-05-02）— Embedding 冷啟動優化

> 解決 `get_embedder()` 在每次啟動時觸發 test embed probe 造成的冷啟動延遲，
> 以及 `add_knowledge` 同步 embedding 阻塞回傳的問題。
> 新增 10 tests（`tests/unit/test_embed_coldstart.py`）。

### ARCH-DEBT 修復：get_embedder() lazy probe

**問題**：`get_embedder()` 預設對每個 provider 呼叫 `emb.embed("test")` 探測，
即使 `BRAIN_EMBED_PROVIDER` 已明確設定，仍會觸發 model 初始化（sentence-transformers
初次載入 ~2-5s）。

**修復**：
- `BRAIN_EMBED_PROVIDER` 明確設定時，`_skip_probe = True`，直接回傳 embedder 實例
- 新增 `BRAIN_EMBED_LAZY=1` env var，強制所有 provider 跳過 probe（適合測試環境）
- Model 改為真正 lazy load：第一次呼叫 `embed()` 時才載入，不在 `__init__` 觸發

### ARCH-DEBT 修復：add_knowledge 非同步 embedding

**問題**：`add_knowledge` 呼叫 `emb.embed(text)` 為同步操作，
sentence-transformers 初次 encode 可達 500ms～2s，阻塞 MCP tool 回傳。

**修復**：
- embedding 移至 daemon thread 背景執行（`threading.Thread(daemon=True)`）
- `add_knowledge` 立即回傳 `node_id`，FTS5 搜尋立即可用
- vector 搜尋在背景 embedding 完成後自動上線（無需重啟）

### 新增：warmup_embedder()

- `warmup_embedder()` — 在 server 啟動時啟動背景 thread 預載 model
- MCP server 整合：`BRAIN_EMBED_WARMUP=1` 時在 server 初始化後自動觸發
- 第一個真實請求到達時 model 已就緒，消除 p99 首次查詢尖刺

### 測試

`tests/unit/test_embed_coldstart.py`（10 tests）：
- `TestGetEmbedderLazyProbe`（4）：explicit provider / LAZY env / none / cache hit
- `TestAsyncEmbedding`（2）：`add_knowledge` < 1s 回傳、FTS5 立即可搜尋
- `TestWarmupEmbedder`（2）：背景 thread 啟動、provider=none 不 crash
- `TestEmbedProviderIntegration`（2）：LocalTFIDF fallback 永遠可用、維度一致性

---

## v0.47.0（2026-05-02）— 深度系統審查修復 + 檢索改進 + WebUI 管理面板

> 基於 `docs/SYSTEM_DEEP_REVIEW_2026-05-02.md` 的審查發現，
> 修復 P0/P1/P2 級缺陷 + recall eval + FTS5 排序改進 + WebUI 管理面板。
> 新增 82 tests + 9 test files。

### P0-1：MCP add_knowledge conflict check 簽名修復

**問題**：`mcp_server.py` 背景 conflict check 呼叫 `find_conflicts(title_c, top_k=3)`，
但實際簽名是 `find_conflicts(similarity_threshold, candidates_per_anchor)`。
TypeError 被靜默吞掉，`KNOWLEDGE_CONFLICT` signal 永遠不產生。

**修復**：
- 新增 `BrainDB.find_conflicts_for_node(node_id)` — 只檢查單節點衝突，不掃全庫
- MCP `add_knowledge` 背景 check 改呼叫 `find_conflicts_for_node(node_id)`
- 15 tests（`tests/unit/test_find_conflicts_for_node.py`）

### P0-2：__version__ source checkout mismatch 修復

**問題**：`importlib.metadata` 優先讀取 installed distribution（0.41.0），
導致 `brain health` 回報舊版本。

**修復**：`_read_version()` 改為優先讀 `pyproject.toml`，metadata 降為 fallback。
- 3 tests（`tests/unit/test_version_consistency.py`）

### P1-2：測試 marker 隔離 + WebUI schema 相容修復

- `tests/test_chaos_and_load.py` 加入 `pytestmark = pytest.mark.chaos`（module-level）
- `tests/chaos/test_chaos_and_load.py` 同上
- WebUI raw handler 改用 PRAGMA table_info 偵測 schema，不再依賴 try/except fallback chain
- 4 個 WebUI 測試從 FAIL → PASS

### P1-3：WebUI FTS sync 使用 BrainDB._ngram()

**問題**：WebUI PATCH 後 `_sync_fts()` 直接寫 raw text 到 FTS5，
但 `BrainDB.add_node()` 使用 CJK n-gram tokenization，導致中文搜尋退化。

**修復**：`_sync_fts()` 改用 `BrainDB._ngram()` tokenize title/content。
- 5 tests（`tests/unit/test_webui_fts_ngram.py`）

### P2-1：get_context full output 顯示 node id

**問題**：full 模式缺少 node id，Agent 無法呼叫 `report_knowledge_outcome(node_id=...)`。

**修復**：
- `_fmt_node()` 標題加入 `[node_id[:8]]` 前綴
- footer 新增結構化 `Sources` block（完整 node id 列表）
- 8 tests（`tests/unit/test_context_node_id.py`）

### P2-2：health 顯示 storage metrics

**新增 `_check_storage_metrics()`**：
- `storage/db`：brain.db + WAL 大小（> 100MB 時 WARN）
- `storage/backups`：備份數量 + 總大小（> 14 個時 WARN）
- `storage/vectors`：embedding 覆蓋率（< 80% 時 WARN）
- 8 tests（`tests/unit/test_health_storage.py`）

### P2-3：靜默例外審計測試

**新增 `tests/unit/test_silent_exception_audit.py`**：
- 掃描 critical modules 中 `except Exception: pass` 模式（baseline ≤ 25）
- 禁止 bare `except:` without type
- 驗證 P0-1 回歸（conflict check 不再靜默失敗）
- 驗證 add_node/search_nodes 有 logger 呼叫
- 5 tests

### 誠實性修正

- README 測試數：1219 → ~1483（不含 chaos/benchmark）
- README 並發安全措辭：「多人同時操作不丟資料」→「best-effort，非強一致」
- ROADMAP E-02 狀態：`[DONE]` → `[PARTIAL]`（Write Queue 未實作）
- ROADMAP 基準版本更新

### 檢索品質評估框架（SYSTEM_DEEP_REVIEW §11 D1）

**新增 `project_brain/eval.py`** — `RecallEvaluator` 類別：
- 從真實知識庫自動生成 eval dataset（高信心節點 → query/expected pairs）
- 支援人工 curate 的 JSONL dataset（`.brain/eval/queries.jsonl`）
- 量化指標：recall@1/3/5/10、MRR、nDCG@3、noise rate、avg context tokens
- per-tag breakdown（按 type/scope 分類報告）
- 33 tests（`tests/unit/test_recall_eval.py`）

**新增 CLI `brain eval` 命令**：
- `brain eval generate` — 從知識庫產生 eval dataset
- `brain eval run` — 執行評估（自動產生或載入已有 dataset）
- `brain eval report` — 輸出 JSON 報告
- `--ci --threshold 0.5` — CI 模式，recall@3 低於門檻時 exit 1

**首次真實 KB 基線測試**（762 nodes, 100 queries）：
- recall@3 = 21%, recall@10 = 30%
- MRR = 0.16, nDCG@3 = 0.16
- Pitfall recall@3 = 42%, Rule = 17%, Decision = 6%

### FTS5 搜尋排序改進

**問題**：3 個高信心通用節點「霸屏」93% 搜尋結果（`rule-22fe170e`、`pitfall-f29fc403`、
`pitfall-02c3808d`），因為純 confidence 排序讓含常見 CJK bigram 的節點永遠排前。

**修復 1 — IDF 加權排序**：
- 計算每個 query token 的 document frequency
- 常見 token（出現在多數文檔中）降權，稀有 token 加權
- 新排序公式：`score = idf_relevance × 0.6 + effective_confidence × 0.4`

**修復 2 — 結果多樣性懲罰**：
- 排序後 greedy reranking：如果候選結果 title 與已選結果 Jaccard > 0.5，降權
- 防止 3 個相似節點佔滿 top-3

**修復 3 — RecallEvaluator hybrid 模式**：
- `brain eval run --hybrid` 使用 FTS5 + vector 混合搜尋
- 13 tests（`tests/unit/test_search_idf_diversity.py`）

**改進效果**（同一 dataset，改進前 → 改進後）：

| 指標 | 改進前 | 改進後 | 提升 |
|------|--------|--------|------|
| recall@1 | 10% | 25% | +150% |
| recall@3 | 21% | 29% | +38% |
| MRR | 0.16 | 0.27 | +68% |
| nDCG@3 | 0.16 | 0.27 | +67% |
| Decision recall@3 | 6% | 24% | +300% |

### WebUI 管理面板 + 效能修復

**問題**：762+ 節點的 D3 force graph 導致瀏覽器嚴重卡頓（O(n²) 力學模擬 + 大量 SVG DOM）。

**修復 — Graph 效能**：
- `/api/graph` 預設 limit 從 300 降為 100
- 前端新增節點上限控制（數字輸入框，20-500）
- 使用者可按需增加節點數，預設不卡

**新增 — 管理面板（Table 視圖）**：
- Header 新增「📊 圖譜 / 📋 管理」Tab 切換
- Table view 包含：搜尋框、type 篩選、排序（信心度/時間/存取次數/標題）
- 分頁表格（每頁 20 筆）
- 每行顯示：類型 pill、標題、摘要、信心度（色階）、存取次數、日期
- 操作按鈕：🔍 查看詳情、👍 有用、👎 過時

**新增 — /api/nodes 端點**：
- 分頁：`page` + `page_size`（最大 100）
- 搜尋：`q`（title + content LIKE）
- 篩選：`kind`（Pitfall/Rule/Decision/ADR/Note）
- 排序：`sort` × `order`（confidence/created_at/access_count/title）
- 10 tests（新增到 `tests/integration/test_web_ui.py`）

### 架構債修復

**MCP singleton 連線**：
- 修復 mcp_server.py 3 處重複 `BrainDB()` 建構（line 644, 1289, 1711）
- 改用 `b.db`（已有的 ProjectBrain singleton），減少連線泄漏和 WAL 壓力

**Traces 採樣**：
- `search_nodes` 不再每次同步寫 trace，改為每 N 次記錄一次
- 預設 `_trace_sample_rate=5`（可透過 `BRAIN_TRACE_SAMPLE_RATE` 環境變數調整）
- 高 QPS HTTP MCP 場景下減少 80% 的 WAL 寫入

**Backup 保留天數可設定**：
- `_maybe_backup()` 保留份數讀取順序：`BRAIN_BACKUP_KEEP` env → `config.json` → 預設 7
- 最小值為 1（防止意外清空）
- 17 tests（`tests/unit/test_arch_debt.py`）

**測試套件**：~1557 passed（不含 chaos/benchmark），0 real failures

---

## v0.46.0（2026-04-27）— E-02 多用戶寫入安全 + E-VERIFY 連接驗證

### E-02：多用戶寫入安全 + author 歸屬

**MCP `add_knowledge` tool 新增 `source` 參數**：
- 小龍蝦/Agent 可傳入 `source="telegram:@alice"` 追蹤知識來源
- 透傳到 `engine.add_knowledge(source=...)` → `nodes.source_url` 欄位
- 回傳 dict 包含 `source` 欄位確認

**MCP `search_knowledge` tool 新增 `author` 過濾 + `source` 回傳**：
- 結果 dict 新增 `source` 欄位（對應 `nodes.source_url`）
- 新增 `author` 參數：`search_knowledge(query, author="telegram:@alice")` → 只回傳該 author 的知識
- author 過濾為 case-insensitive substring match

**並發寫入驗證**：
- 10 threads × 10 writes：≥90% 成功率，source 欄位不串線
- 並發讀寫不 crash（5 writers + 5 readers）
- find_conflicts 在並發寫入後正常運作

**測試**：15 tests（`tests/unit/test_multi_user_writes.py`）
- `TestAuthorAttribution`（5）：source 寫入、查詢回傳、雙 author 共存
- `TestAuthorFiltering`（3）：按 author 過濾、無過濾回傳全部
- `TestConcurrentWrites`（4）：10 threads 並發、source 正確性、讀寫並行
- `TestNearDuplicateDetection`（3）：相似偵測、不同標題、並發下正確性

### E-VERIFY：MCP Tools 端到端驗證

**37 tests（`tests/integration/test_mcp_tools_e2e.py`）**：
- `TestAddKnowledge`（5）：node_id 回傳、source 持久化、全參數、round-trip
- `TestSearchKnowledge`（5）：結果格式、source 欄位、limit、空結果、空知識庫
- `TestGetContext`（3）：回傳字串、包含知識、空知識庫
- `TestBatchAddKnowledge`（2）：批次寫入、搜尋可找到
- `TestBrainStatus`（2）：有/無資料
- `TestCompleteTask`（1）：不 crash
- `TestReportKnowledgeOutcome`（2）：正/負面回饋
- `TestKRBPreScreen`（2）：待審列表、空知識庫
- `TestImpactAnalysis`（2）：未知元件、有 edges
- `TestTemporalQuery`（2）：預設參數、空知識庫
- `TestMarkHelpful`（2）：正/負面 feedback
- `TestReasoningChain`（2）：空知識庫、有知識
- `TestFederationSync`（2）：空/有資料 export
- `TestGraphOperations`（3）：edges + neighbors、stats、mermaid
- `TestEndToEndRoundTrip`（2）：完整工作流、多 author 工作流

---

## v0.45.0（2026-04-27）— E-01 HTTP MCP Transport

### E-01：HTTP MCP Transport（Phase E 基礎）

**新模組 `http_transport.py`**：
- `AuthMiddleware` — Bearer token 認證（`hmac.compare_digest` timing-safe）
- `RateLimitMiddleware` — 每 IP 滑動視窗限流（in-memory，多實例需 Redis backend）
- `CORSMiddleware` — preflight OPTIONS + origin 白名單
- `HealthEndpoint` — `/health` JSON 回應（免認證，供負載均衡 + 監控）
- `HTTPBrainServer` — 包裝 FastMCP Starlette app + 中介層堆疊

**`mcp_server.py` 更新**：
- 新增 `create_http_server()` 工廠函式
- `main()` 支援 `--transport streamable-http`、`--bind`、`--port`、`--auth-key`、`--allow-origin`、`--rate-limit-rpm`

**CLI 更新（`cli_serve.py` + `cli_utils.py`）**：
- `brain serve --mcp --auth-key $KEY` 啟動 HTTP MCP Server
- `brain serve --mcp --transport sse` 使用 SSE 傳輸
- 自動偵測：設定 `--auth-key` 或 `--transport streamable-http` 時啟用 HTTP 模式
- 無 auth-key 時顯示安全警告

**測試**：36 tests（`tests/integration/test_http_mcp_server.py`）
- `TestAuthMiddleware`（8）：401/timing-safe/health bypass/non-http passthrough
- `TestRateLimitMiddleware`（7）：under/over limit、per-IP 獨立、sliding window
- `TestCORSMiddleware`（5）：preflight、origin 白名單、allow-all
- `TestHealthEndpoint`（4）：200 JSON、trailing slash、passthrough
- `TestHTTPBrainServer`（9）：full stack、auth+cors+rate-limit、SSE transport、idempotent
- `TestMiddlewareStackOrder`（2）：auth before rate-limit、health bypasses all
- `TestCreateHTTPServerFactory`（1）：factory returns correct type

---

## v0.44.1（2026-04-27）— 調整開發狀態為 Alpha

### 開發狀態調整

- `pyproject.toml` classifier 由 `Development Status :: 4 - Beta` 降至 `Development Status :: 3 - Alpha`
- 原因：尚缺乏大規模實驗數據驗證，暫無正式（stable）發行計畫
- 0.x 版號維持不變；v1.0 凍結直至完成充分的效能與召回率實驗驗證

---

## v0.44.0（2026-04-27）— D-05 文件完整化

### D-05：文件完整化 v1.0

**更新 `COMMANDS.md`**（v1.0）：
- 命令狀態表加入 `brain health`、`brain validate`、`brain pipeline-stats`、`brain search`、`brain config`
- 新增 `brain health` 詳細說明：JSON 輸出結構、CI 整合腳本（正確使用 `d["summary"]["overall"]`）
- 新增 `brain validate` 詳細說明：三個驗證階段（Rule / Code / LLM）、CI 整合
- 新增 `brain pipeline-stats` 詳細說明：各選項、輸出格式、Prometheus text format
- 修正「已移除命令」段落（`distill` 為待實作，非已移除）

**更新 `INSTALL.md`**（加入 GPU/LoRA 環境）：
- 新增「GPU 環境安裝（D-01 LoRA 蒸餾）」章節
- CUDA + PyTorch 安裝、Axolotl / Unsloth 框架說明
- Google Colab T4 GPU 替代方案（免費 15GB VRAM）
- 硬體需求表（最低 / 推薦配置）

**更新 `tests/TEST_PLAN.md`**（v1.0）：
- 從 v0.6.0（2026-04-04）升至 v1.0（v0.43.0，2026-04-27）
- 完整測試套件全覽：unit（1016）、e2e（14）、integration（67）、benchmark（9）
- 新增 Phase B/C/D 測試章節、Federation 測試、Pipeline 測試
- 更新品質門檻總表（含 D-03~D-04 實際數據）

**更新 `docs/EXPERIMENT_REPORT.md`**（填入 D-04 真實數據）：
- 新增「零、D-04 效能基準」段落：5K nodes 效能、召回率基準、Federation 規模驗證
- 保留 REV-01/02 框架（待真實舊專案執行後填入）

**新建 `README.md`**（快速開始 + 架構說明）：
- 三層記憶架構（L1a / L2 / L3）說明
- 知識節點類型表（Rule / Decision / Pitfall / ADR / Note）
- 快速開始指引（install → setup → add → ask）
- 核心功能：Auto-Pipeline、KRB 審查、知識衰減、CI 整合、WebUI、Federation
- 效能指標表、文件導覽

**新增 `tests/unit/test_docs_accuracy.py`**（51 tests，全部通過）：
- `TestCommandsDocAccuracy`（14）：COMMANDS.md 命令存在於 CLI、JSON key 正確
- `TestVersionConsistency`（5）：版本號碼跨文件一致性
- `TestInstallDocStructure`（10）：INSTALL.md 必要章節（含 GPU/LoRA/Colab）
- `TestTestPlanStructure`（9）：TEST_PLAN.md v1.0 結構驗證
- `TestREADMEStructure`（13）：README.md 快速開始、架構、命令、效能數字

---

## v0.43.0（2026-04-27）— D-04 生產驗證

### D-04：生產驗證（Federation × E2E Pipeline × 5K 效能基準）

**新增 `tests/unit/test_prod_validation.py`**（19 tests）：
- `TestCrossBrainSync`（7）：兩個真實 tmp brain dir export→import round-trip
- `TestPIIAtScale`（5）：1000 節點 PII 清理完整性驗證（email / private IP / internal host 全部移除）
- `TestDedupAtScale`（4）：1000 節點中 300 重複 → `skipped_dup=300`，200 novel 正確 staged
- `TestFederationBundleIntegrity`（3）：JSON 序列化、必要欄位、空庫

**新增 `tests/e2e/test_pipeline_e2e.py`**（14 tests）：
- `TestSignalToL3Flow`（8）：stub judge 驗證完整 signal→L3 資料流
- `TestPipelineLatency`（2）：signal-to-L3 < 5s；batch 10 signals < 30s
- `TestPipelineWorkerLifecycle`（3）：daemon thread start/stop/double-start
- `TestPipelineOllama`（1）：`BRAIN_TEST_OLLAMA=1` guard — CI 安全 skip

**新增 `tests/benchmarks/benchmark_perf_5k.py`**（5 tests，`@pytest.mark.benchmark`）：
- 5000 節點寫入吞吐量 ≥ 200 nodes/s
- FTS5 p99 延遲 ≤ 300ms，平均 ≤ 100ms
- BrainDB hybrid search p99 ≤ 300ms

**已修正行為**：
- `mark_failed` retry 語義：失敗後回到 pending（最多 MAX_ATTEMPTS=3 次）
- pytest.ini 新增 `e2e_ollama` marker 定義

---

## v0.42.0（2026-04-27）— D-03 完整 CI 集成

### D-03：GitHub Actions CI Pipeline

**新增 `.github/workflows/ci.yml`** — 5 jobs：
- `unit`：Python 3.11 + 3.12 矩陣，排除 benchmark/chaos，測試 tests/unit/ + test_web_ui.py
- `benchmark`：`pytest -m benchmark` baseline regression（4 tests，無需 embedder）
- `coverage`：覆蓋率門檻 ≥ 45%（現有 ~47%），上傳 Codecov（token 可選）
- `health`：`brain init` + `brain health --json`，解析 `d["summary"]["overall"]`，接受 ok/warn
- `validate`：`brain init` + `brain validate --ci`，解析 `d["passed"]`，空知識庫必須 passed=True

**修正 ROADMAP 中的錯誤**：health 檢查應用 `d["summary"]["overall"]`（非頂層 `d["overall"]`）

**新增 `tests/unit/test_ci_integration.py`**（45 tests）：
- `TestHealthCheckerJSON`（12）：JSON 結構、欄位、CI 退出邏輯
- `TestValidateCIMode`（8）：空知識庫通過、無 API 呼叫、CI 退出邏輯
- `TestValidationReportDict`（9）：`to_dict()` 所有必要欄位
- `TestPyprojectCIConfig`（6）：dev deps、覆蓋率門檻、pytest markers、semver
- `TestCIWorkflowFile`（10）：檔案存在、YAML 有效、必要 jobs、正確 JSON key

**覆蓋率對齊**：
- `pyproject.toml`：`fail_under = 45`（誠實反映現有 ~47% 基準）
- `ci.yml`：`--cov-fail-under=45`（對應 pyproject.toml）

---

## v0.41.0（2026-04-27）— D-02 WebUI 行內編輯 + KRB Staging 管理

### D-02 ARCH-05：WebUI 完整化（行內編輯 + KRB Staging API）

**新增 API 端點**：
- `PATCH /api/node/<id>` — 更新節點 title/content/confidence/kind（白名單驗證）
- `DELETE /api/node/<id>` — 刪除節點 + 同步清除 FTS5 index + 關聯 edges
- `GET /api/staging` — 列出 KRB pending 待審節點（讀取 review_board.db）
- `POST /api/staging/<id>/approve` — 核准 staging 節點（透過 KnowledgeReviewBoard）
- `POST /api/staging/<id>/reject` — 拒絕 staging 節點

**前端新增**：
- 節點 panel 新增「✏ 編輯」「✕ 刪除」按鈕
- 行內編輯表單（title / kind / confidence slider / content textarea）
- KRB Staging Panel（sidebar 最底部，有待審節點時自動顯示）
- 儲存後即時更新圖譜視覺化

**測試**（`tests/unit/test_web_ui_edit.py`，33 tests）— 零 regression（1400 passed）

---

## v0.35.0（2026-04-26）— 可觀測性與維護性 Phase B

測試基準：**919 unit passed**（v0.34 baseline 684 → v0.40.0 919；零 regression）

## v0.40.0（2026-04-27）— 架構演進 Phase C

### C-05 — Pipeline Layer 5：Feedback Loop（19 tests）

**問題**：`report_knowledge_outcome` 的回饋資料沒有被追蹤到信號類型層級，
無法判斷哪些信號類型產生的知識品質較差，也無法自動調整信賴度。

**修法**：

1. **`project_brain/core/brain_db.py`** — Schema v28：新增 `feedback_log` 表
   - 記錄 `node_id`、`signal_kind`、`was_useful`、`notes`、`conf_before`、`conf_after`

2. **`project_brain/feedback_tracker.py`** — 新增兩個方法：
   - `log_feedback(node_id, was_useful, signal_kind, ...)` — 寫入 feedback_log
   - `get_negative_rate(signal_kind, days=30)` — 計算特定信號類型的負面回饋率

3. **`project_brain/interfaces/mcp_server.py`** — 兩項整合：
   - `report_knowledge_outcome` tool：成功後寫入 feedback_log（含 signal_kind 追蹤）
   - `_adjust_signal_confidence(brain)` — 在 decay daemon 維護週期中觸發：
     * 30 天內 >30% 負面回饋 → 自動下調該信號類型的 auto_confidence（-0.1，floor 0.3）
     * 寫入 `brain_meta` 的 `signal_confidence:{kind}` key
     * 需至少 5 個樣本才觸發（避免統計雜訊）

**新增測試**（`tests/unit/test_feedback_loop.py`，19 tests）：

| 群組 | Tests | 覆蓋重點 |
|------|-------|---------|
| `TestFeedbackLogMigration` | 3 | 表存在、欄位正確、schema v28 |
| `TestLogFeedback` | 3 | 正/負回饋寫入、批量寫入 |
| `TestGetNegativeRate` | 5 | 無/全正/全負/混合/跨 kind 獨立 |
| `TestAdjustSignalConfidence` | 6 | 無回饋/低於閾值/觸發/樣本不足/floor/持久化 |
| `TestMaintenanceCycleIntegration` | 2 | 函式可 import、result schema 含 feedback keys |

---

### C-04 — Pipeline Phase 2：MCP_TOOL_CALL / TEST_FAILURE / KNOWLEDGE_CONFLICT 信號（20 tests）

**問題**：Pipeline 只捕捉 `GIT_COMMIT`、`TASK_COMPLETE` 信號，
MCP tool 呼叫、測試失敗、知識矛盾等高價值事件完全沒被追蹤。

**修法**：

1. **`project_brain/pipeline/signal.py`** — 新增 `KNOWLEDGE_CONFLICT` SignalKind
   （`MCP_TOOL_CALL` 和 `TEST_FAILURE` 已在 Phase 1 定義）

2. **`project_brain/pipeline/llm_judgment.py`** — 新增 `_SIGNAL_HINTS` dict：
   - 3 組 signal-specific prompt context（MCP_TOOL_CALL / TEST_FAILURE / KNOWLEDGE_CONFLICT）
   - 附加在通用 prompt 後，引導 LLM 做信號類型特定的判斷

3. **`project_brain/interfaces/mcp_server.py`** — 信號發射：
   - `BrainServer.emit_signal()` — 非阻塞信號發射 helper
   - `add_knowledge` tool：成功後 emit `MCP_TOOL_CALL` + 背景 `KNOWLEDGE_CONFLICT` 偵測
   - `complete_task` tool：pitfalls 含 error/test 關鍵字時 emit `TEST_FAILURE`

**新增測試**（`tests/unit/test_pipeline_phase2_signals.py`，20 tests）：

| 群組 | Tests | 覆蓋重點 |
|------|-------|---------|
| `TestPhase2SignalKinds` | 5 | enum 值存在、str 型別、Phase 1 向後相容 |
| `TestPhase2SignalCreation` | 4 | 建立+to_row+from_row round-trip |
| `TestPromptHints` | 5 | 各 kind hint 注入、Phase 1 無 hint、JSON schema |
| `TestSignalQueueAcceptance` | 3 | enqueue + dedup |
| `TestBrainServerEmitSignal` | 3 | enqueue 成功、invalid kind 不 crash、priority |

---

### C-03 — KnowledgeValidator CI 集成（11 tests）

**問題**：`KnowledgeValidator` 三階段驗證（Rule → Code → LLM）已實作，但：
1. 沒有 CLI 觸發機制（只能手動呼叫）
2. LLM 階段在 CI 環境中 Ollama 不可用時會 skip，無 fallback 報告

**修法**：

1. **`project_brain/engines/knowledge_validator.py`** — 新增 `ValidationReport.to_dict()`：
   - JSON-serializable dict，含 `passed` boolean + 所有結果
   - `passed = (invalidated_count == 0)`

2. **`project_brain/interfaces/cli_admin.py`** — 新增 `cmd_validate()`：
   - `brain validate` — 完整三階段驗證
   - `--ci` — CI-safe 模式：跳過 LLM，只跑 Rule + Code，輸出 JSON，`exit 1` if `passed=false`
   - `--json` — JSON 輸出
   - `--output report.json` — 寫入檔案
   - `--max-api-calls N` — 限制 API 呼叫數
   - `_ValidatorLLMAdapter` — 橋接 unified LLMClient → duck-typed interface

3. **CLI 整合**：
   - `cli_utils.py`：新增 `validate` parser（--ci, --json, --output, --max-api-calls）
   - `cli.py`：dispatch `'validate': cmd_validate`

**新增測試**（`tests/unit/test_knowledge_validator_ci.py`，11 tests）：

| 群組 | Tests | 覆蓋重點 |
|------|-------|---------|
| `TestValidationReportToDict` | 4 | empty/serializable/passed-false/required-keys |
| `TestValidatorCIMode` | 5 | empty DB/with nodes/zero API/JSON parseable/file output |
| `TestValidatorLLMAdapter` | 2 | adapter wraps LLMClient / empty messages |

---

### C-02 — 統一 LLM 介面（28 tests）

**問題**：LLM 呼叫散落在 9 個模組，各自實作重試、fallback、client 建構：
- `llm_judgment.py` / `krb_ai_assist.py` / `conflict_resolver.py` 用 `.messages.create()`
- `nudge_engine.py` / `memory_synthesizer.py` 用 `.chat.completions.create()`
- 兩種不相容的介面（Anthropic SDK vs OpenAI SDK）

**修法**：

1. **`project_brain/integrations/llm_client.py`** — 全新統一介面模組：
   - `LLMClient` Protocol — 單一方法 `complete(prompt, *, max_tokens, temperature, timeout) → str`
   - `OllamaLLMClient` — 零外部依賴（urllib），呼叫 `/api/chat`
   - `AnthropicLLMClient` — 使用 anthropic SDK，內建指數退避重試
   - `FallbackLLMClient` — 嘗試 primary，失敗則 fallback
   - `NoopLLMClient` — 無 LLM 環境使用
   - `from_brain_config(section, brain_dir)` — 從 brain.toml 工廠建立

2. **`project_brain/pipeline/llm_judgment.py`** — 第一個遷移消費者：
   - `_call_llm()` 優先使用 `LLMClient.complete()`，fallback 到 legacy
   - `from_brain_config()` 改用統一工廠

**新增測試**（`tests/unit/test_llm_client.py`，28 tests）：

| 群組 | Tests | 覆蓋重點 |
|------|-------|---------|
| `TestProtocol` | 4 | 所有實作滿足 LLMClient Protocol |
| `TestNoopClient` | 3 | empty return、model、repr |
| `TestOllamaClient` | 4 | model、payload 正確、failure raise |
| `TestAnthropicClient` | 4 | model、no-key raise、mock SDK、repr |
| `TestFallbackClient` | 5 | primary ok、fallback on fail、both fail、model、repr |
| `TestFromBrainConfig` | 6 | no-config→noop、ollama→Ollama、key→Anthropic、toml configs |
| `TestLLMJudgmentIntegration` | 2 | unified path + legacy fallback |

---

### C-01 — 統一 DB：knowledge_graph.db 合併進 brain.db（25 tests）

**問題**：雙 DB 架構（knowledge_graph.db + brain.db）導致資料不一致風險、
B-02 Observer 同步複雜度、review_board.approve() 雙寫 + 回滾邏輯。
edges 從未被同步到 brain.db。

**修法**：

1. **`project_brain/graph.py`** — KnowledgeGraph 改為操作 brain.db：
   - `db_path` 從 `knowledge_graph.db` → `brain.db`
   - 新增 `conn` 參數支援連線共享（`_owns_conn` flag 控制 close 行為）
   - FTS5 改為 `DELETE+INSERT by id`（相容 standalone FTS5 模式）
   - 移除 `nodes_fts.rowid` JOIN → 改用 `nodes_fts.id` JOIN
   - 移除重複的 `close()` 方法

2. **`project_brain/core/brain_db.py`** — Schema v27 + KG 遷移：
   - Migration v27：edges 表新增 `weight`、`created_at`、`trigger_condition`、
     `confidence` 欄位 + `idx_edges_source`/`idx_edges_target` 索引
   - `_migrate_kg_to_unified()`：從舊 knowledge_graph.db 匯入 nodes+edges，
     設置 `c01_kg_merged` 標記，舊檔重命名為 `.db.bak`
   - `SCHEMA_VERSION` 升至 27

3. **`project_brain/engine.py`** — 移除 Observer：
   - `graph` property 傳入 `conn=self.db.conn` 共享連線
   - 移除 `_on_graph_node_upserted` callback 和 `add_listener` 呼叫

4. **`project_brain/engines/review_board.py`** — 簡化 approve()：
   - 移除 BrainDB 雙寫 + 回滾邏輯（BLOCKER-02 era）
   - 改為單一 `graph.add_node()` 呼叫（直接寫入 brain.db）

5. **`project_brain/health.py`** — 單 DB 模式：
   - 移除 knowledge_graph.db 存取檢查
   - 移除 KG/BrainDB sync drift 偵測
   - 報告 "single DB mode" + 遺留 KG 檔案遷移狀態

6. **`project_brain/interfaces/cli_fed.py`** — 修復既有 bug：
   - `KnowledgeGraph(bd / "brain.db")` → `KnowledgeGraph(bd)`（3 處）

**新增測試**（`tests/unit/test_db_unification.py`，25 tests）：

| 群組 | Tests | 覆蓋重點 |
|------|-------|---------|
| `TestMigrationV27` | 6 | edges 新欄位 + 索引 + schema version |
| `TestKGMigration` | 5 | nodes/edges 匯入、.bak 重命名、冪等性 |
| `TestUnifiedDB` | 3 | graph↔braindb 雙向可見、無 KG 檔建立 |
| `TestEdgesUnified` | 1 | graph.add_edge 存入 brain.db |
| `TestFTS5Unified` | 2 | FTS5 搜尋 + 更新後搜尋 |
| `TestConnectionSharing` | 3 | 同一 conn、shared close 無操作 |
| `TestBackwardCompat` | 3 | standalone 模式、brain.db 路徑、50 thread 並發 |
| `TestHealthSingleDB` | 2 | single DB mode 報告、無 KG error |

---

## v0.35.0（2026-04-26）— 可觀測性與維護性 Phase B

### B-07 — LOW-01~04 錯誤處理批次修復（21 tests）

**問題**：四處靜默 `pass` 吞掉例外 + PII 清理遺漏 UUID/token 格式。

**修法**：

1. **LOW-01** `context.py:103` — `except Exception: pass` → `logger.warning("LOW-01: ...")`
   - config.json 讀取失敗時記錄 warning 而非靜默
   - 仍 fallback 到預設值（不影響正常運作）

2. **LOW-02** `brain_db.py:67` — `except OSError: pass` → `logger.debug("LOW-02: ...")`
   - 備份清理失敗時記錄 debug（非關鍵路徑）

3. **LOW-03** `brain_db.py:89` — `close()` 冪等保護
   - 新增 `if self._conn_obj is None: return` 前置檢查
   - `close()` 後將 `_conn_obj` 設為 `None`
   - 重複呼叫不拋例外

4. **LOW-04** `federation.py` — `_strip_pii` 新增 UUID 與 API token 清理
   - `_PII_UUID`：UUID 格式 (8-4-4-4-12)，不分大小寫
   - `_PII_TOKEN`：`sk-` / `ghp_` / `xoxb-` / `xoxp-` / `xoxa-` 開頭，≥ 16 字元
   - 既有 75 個 federation 測試全通過（零 regression）

**新增測試**（`tests/unit/test_low_fixes.py`，21 tests）：

| 群組 | Tests | 覆蓋重點 |
|------|-------|---------|
| `TestLow01ContextConfigLog` | 3 | 無效 JSON warning、正常 JSON 無 warning、缺檔無 warning |
| `TestLow02BackupCleanupLog` | 2 | source 有 LOW-02 標記、初始化不 crash |
| `TestLow03CloseIdempotent` | 4 | double/triple close、conn=None、already-None safe |
| `TestLow04PiiUUID` | 3 | UUID 替換、大寫 UUID、正常連字詞不誤判 |
| `TestLow04PiiToken` | 6 | ghp_/sk-/xoxb-/xoxp- 替換、短 token 不誤判、正常文字不動 |
| `TestLow04RegressionExistingPii` | 3 | email/IP/Slack URL 仍正常清理 |

---

### B-06 — `_count_tokens` 移除 LRU cache（30 tests）

**問題**：`@functools.lru_cache(maxsize=1024)` 對 5000+ 節點的知識庫
命中率 < 20%，持續驅逐 + 重算浪費 CPU，cache key 管理本身成為開銷。

**修法**：

1. **`project_brain/engines/context.py`** — `_count_tokens()` 改為確定性 O(n) 估算：
   - 移除 `@lru_cache(maxsize=1024)` decorator
   - 新增空字串早期返回 `if not text: return 0`
   - 擴展 CJK 範圍：新增 Extension A (U+3400-U+4DBF)、
     Compatibility Ideographs (U+F900-U+FAFF)
   - 移除舊範圍 U+3000-U+303F（CJK 標點）、U+FF00-U+FFEF（全形字）
     — 這些不是 CJK 表意文字
   - 非空 ASCII 部分保證至少 1 token：`max(1, ascii_like // 4) if ascii_like else 0`

2. **結果與舊實作誤差 < 20%**（6 組文字 parametrize 驗證）

**測試重寫**（`tests/unit/test_perf03_token_cache.py`，30 tests 取代舊 26 tests）：

| 群組 | Tests | 覆蓋重點 |
|------|-------|---------|
| `TestB06CacheRemoved` | 3 | 無 cache_info / cache_clear / __wrapped__ |
| `TestB06Determinism` | 2 | 相同輸入相同輸出、呼叫順序無關 |
| `TestB06EmptyString` | 2 | 空字串 → 0 |
| `TestB06PureCJK` | 4 | 4/100 CJK chars、Extension A、Compatibility |
| `TestB06PureASCII` | 5 | hello world、hi、single char、100 chars、4 chars |
| `TestB06Mixed` | 2 | CJK+ASCII 混合、CJK >= ASCII token 數 |
| `TestB06EdgeCases` | 6 | 空白、換行、emoji、全形、長文、Unicode 穩定性 |
| `TestB06BackwardCompat` | 6 | 新舊實作誤差 < 20%（parametrize） |

---

### B-05 — MCP Server Singleton 重構（18 tests）

**問題**：`mcp_server.py` 頂層有 7 組 module-level 可變狀態變數
（`_call_times`、`_session_nodes`、`_session_served`、`_brain_cache`、
3 組 daemon flags），同程序多個 Brain 實例（或 pytest-xdist 並行）
共享這些狀態，導致跨測試污染與微妙的並發 bug。

**修法**：

1. **`project_brain/interfaces/mcp_server.py`** — 新增 `BrainServer` class：
   - 所有可變狀態（rate limiter、session tracking、daemon flags、brain cache）
     封裝為 instance 屬性
   - `rate_check()`、`cleanup_expired_sessions()`、`resolve_brain()` 改為
     instance methods，使用 `self._*` 狀態
   - `_start_daemons()` 統一管理 decay / cleanup / pipeline 三個 daemon 的
     per-instance 啟動
   - `create_mcp_server()` 方法註冊所有 MCP tools，閉包捕獲 `srv`（self）

2. **`create_server(workdir)` 工廠函式**（公開 API 不變）：
   - 內部建立 `BrainServer` 實例，回傳 `srv.create_mcp_server()`
   - 多次呼叫產生完全獨立的狀態空間

3. **Backward compatibility**：
   - 保留 module-level `_call_times`、`_rate_check()`、`_session_nodes` 等
     原有變數與函式，供舊測試使用
   - `_safe_str`、`_validate_workdir`、`_find_brain_root`、`_run_maintenance_cycle`
     仍為 module-level（無狀態，不需實例化）

**新增測試**（`tests/unit/test_mcp_server_isolation.py`，18 tests）：

| 群組 | Tests | 覆蓋重點 |
|------|-------|---------|
| `TestBrainServerConstruction` | 3 | 建構、屬性初始化、primary brain cached |
| `TestRateLimiterIsolation` | 3 | 兩實例互不干擾、limit 執行、timestamp 過期 |
| `TestSessionIsolation` | 3 | session_nodes / session_served / cleanup 各自獨立 |
| `TestDaemonFlagIsolation` | 1 | daemon flags per-instance |
| `TestBrainCacheIsolation` | 1 | brain_cache 不共享 |
| `TestCreateServerCompat` | 4 | create_server 回傳值、module-level 變數/函式存在、BrainServer export |
| `TestConcurrentRateCheck` | 1 | 多 threads 並發不超過 RPM |
| `TestResolveBrain` | 2 | 空 workdir / 同 workdir 回傳 primary |

---

### B-04 — Pipeline Metrics Dashboard（19 tests）

**問題**：pipeline 運行狀態不可見 — 不知道有多少 signal 被處理、
失敗率多少、哪些 LLM model 在用。

**修法**：

1. **`project_brain/core/brain_db.py`** — 新增 `get_pipeline_stats(days=7) -> dict`：
   - 聚合 `signal_queue`：total / by_status / by_kind / queue_depth
   - 聚合 `pipeline_metrics`：processed / by_action / by_model / feedback(useful/not_useful/no_feedback)
   - 表不存在時（pre-v23 schema）回傳全 0，不 crash
   - `days` 參數 clamp to >= 1

2. **`project_brain/interfaces/cli_admin.py`** — 新增 `cmd_pipeline_stats()` + `_format_prometheus()`：
   - 人可讀彩色表格輸出
   - `--json` → `json.dumps(stats)`
   - `--prometheus` → Prometheus text exposition format（counter + gauge）
   - `--days N` → 統計時間窗口

3. **CLI 整合**：
   - `cli_utils.py`：新增 `pipeline-stats` parser（--days, --json, --prometheus）
   - `cli.py`：dispatch `'pipeline-stats': cmd_pipeline_stats`

**新增測試**（`tests/unit/test_pipeline_stats.py`，19 tests）：

| 群組 | Tests | 覆蓋重點 |
|------|-------|---------|
| `TestEmptyDB` | 3 | 空 DB 全 0、必要 keys、JSON serializable |
| `TestAggregation` | 5 | total/by_status/by_kind/by_action/by_model 正確 |
| `TestFeedback` | 3 | useful/not_useful/no_feedback 分別正確 |
| `TestDaysFilter` | 3 | window 過濾、days clamp、queue_depth 不受 window 限制 |
| `TestPrometheus` | 5 | 非空、HELP/TYPE 行、gauge 類型、label 正確、空 DB 仍有效 |

---

### B-03 — `brain health` 一鍵診斷命令（21 tests）

**問題**：系統缺乏統一的健康狀態診斷入口。`brain doctor` 偏重修復，
無法快速回答「現在系統是否正常」。B-02 Observer 完成後，
KG/BrainDB 一致性可被可靠偵測，需要一個命令來暴露此資訊。

**修法**：

1. **`project_brain/health.py`** — 新增 `HealthChecker` class：
   - 純資料收集，回傳結構化 `dict`（CLI 和 MCP 共用）
   - 6 項獨立檢查，每項各自 `try/except`（一個失敗不影響其他）：
     - DB accessibility（brain.db + knowledge_graph.db 節點/邊數）
     - KG/BrainDB sync（節點 ID 集合比對，偵測 drift）
     - KRB staging（pending 數、stale 偵測 30d）
     - Schema version（與 `SCHEMA_VERSION` 常數比較）
     - Signal queue（pending/failed 計數）
     - Benchmark age（baseline.json 修改時間 > 14d → WARN）
   - 回傳 `{version, brain_dir, checks: [{level, label, message, detail?}], summary: {overall, ok, warn, error}}`

2. **`project_brain/interfaces/cli_admin.py`** — ��寫 `cmd_health()`：
   - 呼叫 `HealthChecker` → 彩色 `[OK]/[WARN]/[ERR]` 表格輸出
   - `--json` flag → `json.dumps(report)` 原始 JSON（供 CI 解析）

3. **`project_brain/interfaces/cli_utils.py`**：
   - `health` 從 `argparse.SUPPRESS` 恢復為正式命令
   - 移除 `health` → `doctor` 的 alias redirect

**新增測試**（`tests/unit/test_health.py`，21 tests）：

| 群組 | Tests | 覆蓋重點 |
|------|-------|---------|
| `TestFreshDB` | 4 | 新 DB overall=ok、brain.db/KG/sync 各自 OK |
| `TestWarnScenarios` | 3 | KG/BrainDB 不一致 WARN、stale staging WARN、fresh pending OK |
| `TestErrorScenarios` | 3 | DB 不存在 ERROR、不 crash、corrupt DB ERROR |
| `TestJSONOutput` | 3 | JSON serializable、必要 keys、每個 check 有 level/label/message |
| `TestCheckIsolation` | 3 | KG missing 不影響 BrainDB check、反之亦然、summary 計數一致 |
| `TestSchemaAndExtras` | 5 | schema OK、signal queue OK、benchmark missing OK、old benchmark WARN、failed signals WARN |

---

### B-01 — KRB Cleanup Daemon 整合（16 tests）

**問題**（ARCHITECTURE_REVIEW.md §3 MEDIUM-04 後半）：
`cleanup_expired_staging()` 已實作（A-10），但沒有任何地方自動呼叫它。
過期的 `pending` / `rejected` staging 節點永久累積，永不清理。

**修法**：將 `mcp_server.py` 的 decay daemon 重構為統一維護週期：

1. **`project_brain/interfaces/mcp_server.py`** — 新增 `_run_maintenance_cycle(brain) -> dict`：
   - **Step 1（FEAT-01）**：decay pass — `DecayEngine(brain.graph, ...).run()`
   - **Step 2（B-01）**：KRB staging 清理 — `brain.review_board.cleanup_expired_staging()`
   - 兩步各自有獨立 `try/except`；decay 失敗不阻止 cleanup，cleanup 失敗不阻止 decay
   - 回傳 `{"decay_ok", "decay_error", "cleanup", "cleanup_error"}` dict（可測試）
   - Structured log：cleanup 成功記 INFO 含 `pending_skipped/rejected_archived/ttl_days`；失敗記 WARNING
   - `_decay_daemon_fn` 簡化為呼叫 `_run_maintenance_cycle(brain)`

**設計決策**：
- `_run_maintenance_cycle()` 從 daemon 提取為獨立函式 → 單元測試直接呼叫，不需等 24h sleep
- `cleanup_expired_staging()` 不傳 `ttl_days` → KRB 自行從 `brain.toml` 讀取（遵守設定層次）
- decay 失敗時記 DEBUG（非 ERROR）→ 不中斷 MCP server，符合 FEAT-01 原始設計

**新增測試**（`tests/unit/test_krb_daemon_integration.py`，16 tests）：

| 群組 | Tests | 覆蓋重點 |
|------|-------|---------|
| `TestReturnDict` | 4 | 四個鍵永遠存在、成功/decay失敗/cleanup失敗各自的值 |
| `TestStepIsolation` | 4 | decay失敗仍呼叫cleanup、cleanup失敗decay_ok=True、兩者都失敗不raise、每cycle呼叫一次 |
| `TestLogging` | 4 | cleanup成功記INFO含計數、失敗記WARNING、decay失敗不記ERROR、decay成功記INFO |
| `TestCleanupCallSemantics` | 2 | 不傳ttl_days參數、回傳值存入result['cleanup'] |
| `TestThreadSafety` | 2 | 20 threads並發呼叫無exception、每個回傳dict有正確鍵 |

---

### B-02 MEDIUM-02 — KG/BrainDB 事件驅動同步（29 tests）

**問題**（ARCHITECTURE_REVIEW.md §3 MEDIUM-02）：
`knowledge_graph.db` 與 `brain.db` 是兩個獨立 SQLite 檔案，除了
`review_board.approve()` 的手動雙寫之外，沒有任何自動同步機制。
`graph.add_node()` / `update_node()` 寫入後，BrainDB FTS5 索引不更新，
導致「KG 有節點，`brain ask` / `get_context` 找不到」的長期不一致。

**修法（Observer pattern，最小侵入，方案 C）**：

1. **`project_brain/graph.py`** — 新增 Observer API：
   - `KnowledgeGraph._listeners: list` — 已登記的 listener callable 清單
   - `add_listener(fn)` / `remove_listener(fn)` — 登記 / 取消登記
   - `_emit(event, data)` — 通知所有 listener（失敗 → WARNING log，不 raise）
   - `add_node()` — commit 後、`with self._lock:` 外 emit `"node_upserted"`
   - `update_node()` — commit 後 emit `"node_upserted"`（含合併後的 title/content/confidence）

2. **`project_brain/core/brain_db.py`** — 新增 sync 方法：
   - `sync_from_graph_node(event, data)` — `"node_upserted"` 事件時呼叫 `add_node()`（upsert 冪等），未知 event 靜默忽略

3. **`project_brain/engine.py`** — ProjectBrain 接線：
   - `graph` lazy property：初始化後呼叫 `g.add_listener(self._on_graph_node_upserted)`
   - `_on_graph_node_upserted(event, data)`：轉發到 `self.db.sync_from_graph_node()`；失敗記 WARNING，不 raise

**設計決策**：
- emit 在 `with self._lock:` 外 → 防止 listener 回呼 graph 方法時死鎖
- listener 失敗不回滾 graph 寫入（最終一致性）→ `brain health` 可偵測殘餘不一致
- `review_board.approve()` 的手動雙寫保留為安全網（Phase C 統一 DB 後移除）
- upsert 冪等 → `approve()` 的手動寫 + listener 自動寫 = double write，無副作用

**新增測試**（`tests/unit/test_kg_braindb_sync.py`，29 tests）：

| 群組 | Tests | 覆蓋重點 |
|------|-------|---------|
| `TestObserverAPI` | 6 | add/remove listener 冪等性、_emit 呼叫所有 listener、失敗後繼續 |
| `TestAddNodeSync` | 6 | add_node 同步後可搜尋、type/content/confidence 正確、upsert 更新、commit 後才 emit |
| `TestUpdateNodeSync` | 5 | title/content/confidence 更新同步、不存在節點不 emit、無更新不 emit |
| `TestListenerResilience` | 3 | 失敗不回滾 graph、記 WARNING log、鏈式第二個 listener 仍呼叫 |
| `TestEngineIntegration` | 5 | engine.graph 有 listener、add/update 透過 engine 同步、失敗不 raise、兩實例獨立 |
| `TestIdempotency` | 3 | 雙重 add 只有一筆、sync 兩次無重複、未知 event 忽略 |
| `TestConcurrency` | 1 | 50 threads 並發 add_node，BrainDB 最終節點數與 graph 一致 |

---

## v0.34.0（2026-04-09）— 可觀測性與可維護性（進行中）

對應 `docs/ARCHITECTURE_REVIEW.md §8.4 v0.34` 路線圖。本版逐步累積：
MEDIUM-04（Phase 2 殘餘項）→ MEDIUM-07 → MEDIUM-02 → metrics dashboard
→ `brain health` 命令。

測試基準：**684 passed**（v0.33 baseline 665 + 19 新測試；3 個 pre-existing
schema drift 不計，零 regression）

### MEDIUM-07 — CI benchmark baseline（4 benchmark + 5 meta tests）

**問題**（ARCHITECTURE_REVIEW.md §3 MEDIUM-07）：
`tests/benchmarks/` 下已有 `benchmark_recall.py`（50 節點 × 20 查詢，
測 get_context recall + latency），但無 baseline 對比，效能或召回率退化
無法及時發現。

**修法**：

1. **`tests/benchmarks/benchmark_recall.py`** 新增 `compute_metrics() → dict`
   helper，回傳結構化指標：
   ```python
   {
       "recall_at_3":    float,  # hits / total
       "avg_query_ms":   float,
       "max_query_ms":   int,    # p100
       "node_count":     int,
       "query_count":    int,
       "embedder_class": str,
       "embedder_model": str,
   }
   ```

2. **`tests/benchmarks/baseline.json`** 儲存門檻（含 fixture metadata + 詳細註解）：
   - `recall_at_3.min_value` = 0.60（與腳本內建「good」目標一致）
   - `avg_query_ms.max_value` = 500（≈5× 實測 91ms，吸收 CI jitter）
   - `max_query_ms.max_value` = 2000

3. **`tests/benchmarks/test_baseline_regression.py`** — 4 個 pytest 迴歸測試，
   `@pytest.mark.benchmark` 標記：
   - `test_recall_no_regression` — 召回率 ≥ baseline.min_value
   - `test_avg_latency_no_regression` — 平均延遲 ≤ baseline.max_value
   - `test_p100_latency_no_regression` — p100 ≤ baseline.max_value
   - `test_metric_envelope_sanity` — `compute_metrics()` 結構檢查

   embedder 不可用時 skip 而非 fail，避免乾淨 CI 環境誤觸警報。

4. **`tests/benchmarks/update_baseline.py`** — CLI tool 重新跑 benchmark 並
   更新 `last_observed` 區段；`--tighten` 模式同時收緊 min/max 門檻
   （留 30% 緩衝）。

5. **`tests/unit/test_benchmark_baseline_meta.py`** — **5 個 cheap meta tests
   在每次 unit run 都會跑**，驗證 `baseline.json` 的 schema/類型/門檻合理性
   （無需 embedder 即可執行，不會拖慢 CI）：
   - top-level keys + schema_version
   - recall_at_3 門檻結構
   - 兩個 latency 門檻結構
   - avg ≤ p100 合理性
   - fixture metadata 存在

6. **`pytest.ini` + `pyproject.toml`** 註冊 `benchmark` marker，對齊既有
   `chaos` marker 的命名慣例。

**為什麼不直接用已存在的 benchmark_recall 主程式**：
- 主程式 `__main__` 入口印 ASCII 報告給人看，不適合 CI assertion
- `compute_metrics()` 是純函式，可以直接測試與比對
- meta tests 與 benchmark tests 拆開：meta 永遠 cheap、benchmark 才需要 embedder

**測試結果**：
- `test_baseline_regression.py`：**4 / 4 passed**（embedder 可用時跑 ~12s）
- `test_benchmark_baseline_meta.py`：**5 / 5 passed**（< 0.01s）
- `tests/unit/` 全量：**684 passed**（zero regression）

**未做**：CI workflow 整合（GitHub Actions 等）— 因專案目前無 CI 設定檔，
留待 CI 平台選定後加上 `pytest -m benchmark` 步驟即可。

### Phase 2 進度

✅ BLOCKER-01 (v0.32) · ✅ BLOCKER-03 + HIGH-01 + HIGH-03 + MEDIUM-01 (v0.33)
· ✅ MEDIUM-04 (v0.34) — 🎉 **Phase 2 全部 6 項完成**

### v0.34 路線圖進度（§8.4）

- ✅ MEDIUM-04 KRB staging 自動清理（Phase 2 殘餘項）
- ✅ MEDIUM-07 CI benchmark baseline
- ⏳ MEDIUM-02 KG/BrainDB 事件同步
- ⏳ Pipeline metrics dashboard（Grafana 可讀）
- ⏳ `brain health` 命令（自動 detect 常見不一致）
- ⏳ KRB cleanup daemon 整合

### MEDIUM-04 — KRB staging 自動清理（15 tests）

**問題**（ARCHITECTURE_REVIEW.md §3 MEDIUM-04）：
`project_brain/engines/review_board.py` 原本沒有任何 staging 過期清理機制：

- `rejected` 節點永久保留於 `staged_nodes` 表
- 舊 `pending` 節點若無人審查，永遠累積
- `brain.toml [review.staging_ttl_days]` 已定義（預設 30 天）但 KRB 從未讀取

**修法**：在 `KnowledgeReviewBoard` 新增 `cleanup_expired_staging(ttl_days=None) → dict`：

```python
def cleanup_expired_staging(self, ttl_days: Optional[int] = None) -> dict:
    """
    - status='pending'  + created_at < cutoff → 'skipped_stale'
    - status='rejected' + created_at < cutoff → 'archived'
    - status='approved' / 'needs_changes' 不受影響

    ttl_days=None 時讀取 brain.toml [review.staging_ttl_days]（預設 30）。
    ttl_days <= 0 會被夾到 1（避免立即清空所有 staging）。

    Returns:
        {"pending_skipped": int, "rejected_archived": int, "ttl_days": int}
    """
```

**設計重點**：
1. **不刪除任何 row**，只改 status — 保留審計痕跡，未來想撈回也能查
2. **approved 永不清理** — 已合進 L3，是事實記錄
3. **needs_changes 永不清理** — 還在等待 reviewer 補資料
4. **brain.toml 動態讀取** — 不需重啟 KRB 就能調整 ttl
5. **冪等** — 重複呼叫不重複處理 `skipped_stale` / `archived` 節點

**測試**（`tests/unit/test_krb_cleanup.py`，15 tests，4 群組）：

| 群組 | Tests | 重點 |
|---|---|---|
| `TestCleanupBasic` | 4 | 空 DB / pending old → skipped_stale / rejected old → archived / fresh 不動 |
| `TestStatusIsolation` | 4 | **approved 老的不動** / **needs_changes 老的不動** / 8 種狀態混合正確 partition / 二次呼叫冪等 |
| `TestTTLBoundary` | 5 | 邊界 (29d 不清, 31d 清) / `ttl<=0` 夾到 1 / 預設值 30 / **brain.toml override** |
| `TestReturnValue` | 2 | 回傳 dict 欄位 / 計數正確 |

**關鍵驗收**：
- `test_K05_approved_old_untouched` — 200 天前的 approved 節點不動
- `test_K07_mixed_batch_correct_partition` — 8 種狀態各 1 個（4 種 status × old/fresh），cleanup 只動 `old pending` + `old rejected`
- `test_K13_brain_toml_override_ttl` — 寫 `brain.toml [review] staging_ttl_days = 7`，cleanup 自動套用 7 天 cutoff

**待做**：daemon 整合（搭配 `decay_daemon` 每日呼叫一次），列入 v0.34 後續工作。

---

## v0.33.0（2026-04-09）— 資料正確性強化 + v0.40 目錄重構提前實作

**版本對齊**：本版整併原 v0.34 ~ v0.37 分批開發的 4 個 Phase 2 項目
（BLOCKER-03 / HIGH-01 / HIGH-03 / MEDIUM-01），並順便完成 v0.40 路線圖中的
「目錄重構」項目，以對齊 `docs/ARCHITECTURE_REVIEW.md §8 未來路線圖`：

- §8.3 v0.33 — 資料正確性強化：BLOCKER-03 / HIGH-01 / HIGH-03 / MEDIUM-01
- §8.5 v0.40 — 架構重構：**目錄重構（core/pipeline/engines/interfaces）提前**

測試基準：**665 passed**（v0.32 baseline 534 + 131 新測試；3 個 pre-existing
schema drift 不計，零 regression）

---

### BLOCKER-03 — Federation 模組完整測試套件（75 tests）

**問題**（ARCHITECTURE_REVIEW.md §3 BLOCKER-03）：
`project_brain/integrations/federation.py` 849 行完整實作但 `tests/` 下不存在
任何 `test_federation*`。PII 清理漏網可能洩漏 email / 內部主機 / 私有 IP /
Slack URL / Cloud URL；import 去重錯誤會污染本地 KB；`multi_brain_query` 的
`_validate_workdir` 防線未被迴歸測試保護。

**修法**：新增 `tests/unit/test_federation.py`（952 行，75 tests，8 群組）：

| 群組 | Tests | 重點 |
|---|---|---|
| `TestPIIStripping` | 17 | 6 個 regex + CJK 保留 + 變數名 / 公網 IP 不誤傷 |
| `TestFederationBundle` | 3 | JSON roundtrip / UTF-8 / 預設值 |
| `TestFederationExporter` | 15 | scope/confidence/max_nodes 過濾 + PII 清理 + domain_tags / `_parse_tags` |
| `TestFederationImporter` | 10 | exact + Jaccard 去重 / low_conf / subscription / dry_run / **FED-01 audit** |
| `TestSubscriptionManager` | 10 | CRUD / 正規化 / 持久化 / 設定檔損毀容錯 |
| `TestFederationAutoSync` | 10 | add/remove/sync_all / 停用 / 相對路徑 / dry_run |
| `TestValidateWorkdir` | 8 | 空 / `..` 遍歷 / symlink resolve / `/etc` 禁區 |
| `TestConflictResolution` | 3 | 同 title 去重 / **federation 絕不直接寫 L3** |

**關鍵安全驗證**：
- `test_export_excludes_private_scope` — 私有 scope 節點絕不流出聯邦
- `test_variable_name_not_stripped` / `test_cjk_content_preserved` — 程式碼識別字與中文不被 PII regex 誤傷
- `test_imported_nodes_go_to_staging_not_l3` — federation import 全程只寫 KRB Staging

---

### HIGH-01 — KnowledgeGraph.add_node() 樂觀鎖 CAS（17 tests）

**問題**（ARCHITECTURE_REVIEW.md §3 HIGH-01）：`graph.py` 的 `add_node()` 使用
`INSERT ... ON CONFLICT DO UPDATE` 但從不檢查 `version`，造成三個級聯缺陷：
(1) 並發寫入靜默覆蓋 (2) `version` 死欄位（UPDATE 永遠不遞增）
(3) `ConcurrentModificationError` 是死代碼。

**修法**（`project_brain/graph.py:add_node()`）：
1. 新增 `expected_version: Optional[int] = None` kwarg 啟用 CAS
2. UPDATE 分支遞增 version：`ON CONFLICT DO UPDATE SET ..., version = nodes.version + 1`
3. 讀-檢-寫由 `self._lock` 序列化，消除 race window

**測試**（`tests/unit/test_graph_cas.py`，17 tests，5 群組）：

| 群組 | Tests | 重點 |
|---|---|---|
| `TestBackwardCompat` | 4 | 舊 API 無痛升級 + UPSERT 自動遞增 version |
| `TestCASHappyPath` | 3 | 新節點 / 既有節點匹配版本 / content 更新 |
| `TestCASConflict` | 4 | 錯誤版本 / stale 版本 / 失敗不 mutate row |
| `TestCASConcurrency` | 4 | **50 threads UPSERT 無遺失更新** / **30 threads CAS 恰一個 winner** |
| `TestUpdateNodeCASUnchanged` | 2 | BUG-06 update_node CAS 行為未退化 |

---

### HIGH-03 — find_conflicts O(n²) → FTS5 候選者過濾（20 tests）

**問題**（ARCHITECTURE_REVIEW.md §3 HIGH-03）：`brain_db.find_conflicts()` 原本
使用硬編碼 `LIMIT 500` + 巢狀 for 迴圈做 pairwise Jaccard，在 5000 節點 KB 會
skip 掉 90%+ 的衝突，移除 LIMIT 後 O(n²) 在 1000 節點退化到秒級。

**修法**（方案 A — FTS5 候選者前置過濾）：
1. 新增 `_find_conflict_candidates(title, limit)` helper：用 FTS5 n-gram match
   做 O(log n) 候選者查詢，**不寫 traces 表**
2. 重寫 `find_conflicts()`：移除 `LIMIT 500`，每個 anchor 只與 FTS5 top-K 候選
   者比對（K 預設 10）
3. 新增 `candidates_per_anchor: int = 10` 參數
4. CJK 純字元 title fallback（無空白可 split 時用整個 title 當 token）
5. **複雜度**：**O(n²) → O(n · K · log n)**

**測試**（`tests/unit/test_find_conflicts.py`，20 tests，6 群組）：

| 群組 | Tests | 重點 |
|---|---|---|
| `TestFindConflictsBasic` | 4 | 空 DB / 單節點 / 無關 / 基本重複 |
| `TestContradictionDetection` | 4 | must/must-not、enable/disable、**CJK 必須/禁止**、contradiction 排序優先 |
| `TestOutputFormat` | 3 | dict 欄位完整 / similarity 降序 / top-50 cap |
| `TestDeduplication` | 3 | (a,b)/(b,a) 同對只算一次 / 不與自己比 |
| `TestScaleBeyond500` | 3 | **核心**：600+ 節點仍偵測到衝突 / 1000 節點 < 30s (實測 <1.5s) / traces 無汙染 |
| `TestEdgeCases` | 3 | 空 title / `candidates_per_anchor` / 冪等 |

**方案 B 延後**：vector similarity + FAISS/HNSW 的 O(log n) nearest neighbor
列為未來優化項目。

---

### MEDIUM-01 — BrainDB._execute_write() 統一寫入入口（18 tests）

**問題**（ARCHITECTURE_REVIEW.md §3 MEDIUM-01）：`brain_db.py` 原本有 16+ 個
`self.conn.commit()` 路徑，部分在 `_write_guard()` 內、部分在外，造成不一致
的錯誤處理、缺統一 rollback 語意、審計困難。

**修法**：

1. **新增 `_execute_write(sql, params) → Cursor`** — 單語句統一入口：
   `_write_guard` → execute → `commit()` / `rollback()` + re-raise。
2. **新增 `_execute_writescript(script)`** — 多語句（DDL/batch）統一入口。
3. **RLock 可重入設計** — `_write_guard` 用 `threading.RLock`（REF-03），
   呼叫者已持有鎖時可安全巢狀呼叫 `_execute_write`，讓增量遷移無需一次改完。
4. **重構 8 個 runtime 寫路徑** 改走統一入口：

   | 方法 | 原位置 | 修法 |
   |---|---|---|
   | `search_nodes` trace INSERT | line 776 | `_execute_write` |
   | `prune_episodes` DELETE | line 797 | `_execute_write` |
   | `pin_node` UPDATE | line 819 | `_execute_write` |
   | `record_federation_import` INSERT | line 1088 | `_execute_write` |
   | `add_edge` INSERT | line 1117 | `_execute_write` |
   | `add_temporal_edge` UPDATE+INSERT | line 1296 | 顯式 `_write_guard` + try/rollback |
   | `emit` INSERT | line 1357 | `_execute_write` |
   | `optimize` FTS5 rebuild | line 1396 | `_execute_write` |

5. **刻意保留未保護**：`_setup()` / `_migrate_schema()`（init-time，無並發呼叫者）

**測試**（`tests/unit/test_execute_write.py`，18 tests，4 群組）：

| 群組 | Tests | 重點 |
|---|---|---|
| `TestExecuteWriteCore` | 5 | 成功 commit / 錯誤 rollback / cursor 欄位 / **RLock 巢狀** / **50 threads 序列化** |
| `TestExecuteWriteScript` | 3 | 多語句 / rollback / 10 threads 序列化 |
| `TestRefactoredCallers` | 8 | 每個重構後 caller 獨立行為驗證 |
| `TestRegressionGuards` | 2 | 40 threads 混合並發無 corruption / lock 阻塞語意 |

---

### v0.40 提前實作 — ARCHITECTURE_REVIEW §6.2 目錄重構

**背景**：`docs/ARCHITECTURE_REVIEW.md §8.5 v0.40` 規劃的「目錄重構
（core/pipeline/engines/interfaces）」本版提前實作，為後續長期架構演進
（單一真相源、事務邊界清晰、元件可替換）鋪路。

**新目錄結構**：

```
project_brain/
├── core/                 # 核心不變數據層
│   ├── brain_db.py       # 唯一真相源（+ SCHEMA_VERSION）
│   ├── session_store.py  # L1a
│   └── constants.py      # monkey-patch friendly
│
├── pipeline/             # 自動知識管線
│   ├── signal.py         # Layer 1/2（從 pipeline.py 拆出）
│   ├── executor.py       # Layer 4（從 pipeline.py 拆出）
│   ├── llm_judgment.py   # Layer 3
│   └── worker.py         # Layer 3.5（原 pipeline_worker.py）
│
├── engines/              # 處理引擎
│   └── context / nudge_engine / decay_engine / review_board /
│       memory_synthesizer / conflict_resolver / knowledge_validator
│
├── interfaces/           # 外部介面
│   └── cli / cli_* / mcp_server / api_server / web_ui/
│
└── integrations/         # 外部系統整合
    └── federation / graphiti_adapter
```

**向後相容策略**：所有搬移檔在原位置保留 `sys.modules[__name__] = _real`
別名式 compat shim，舊/新 import 路徑**指向同一個 module 物件**，確保：

1. `from project_brain.brain_db import BrainDB` 等既有 import 繼續運作（493+ 處無需修改）
2. `monkeypatch.setattr(project_brain.constants, ...)` 仍會影響 `core/brain_db.py` 中
   `from . import constants as _constants` 取得的引用（保留 REF-04 契約）
3. `pyproject.toml [project.scripts] brain = "project_brain.cli:main"` 入口點無需改動
4. `isinstance` / 單例 / 模組級 logger 全部如常運作

**搬移規模**：20 檔案搬移 + 20 compat shim + 5 個 `__init__.py`

**未納入本次（屬新功能非 refactor，留待正式 v0.40）**：
- `core/` 合併 `graph.py` 進 `brain_db.py`（需 DB schema v31 migration）
- `integrations/llm_client.py`（統一 LLM 介面）

**關鍵實作細節**：
- `project_brain/core/brain_db.py` 內部 4 處 `from .X` → `from ..X`（cross-boundary）
- `project_brain/engines/context.py` 內部 7 處類似調整
- `project_brain/web_ui/__init__.py` compat shim 必須 pre-register
  `sys.modules[__name__ + ".server"]`，否則 Python 會從 aliased package 的
  `__path__` 重新載入 `interfaces/web_ui/server.py` 建立獨立 module 物件，
  破壞 `is` 檢查

---

### 測試累計成果

| | v0.32 baseline | v0.33 final | 增量 |
|---|---|---|---|
| passed | 534 | **665** | **+131** |
| pre-existing drift | 4 | 3 | −1 flake 恢復 |
| regression | — | **0** | — |

**新增測試檔**（5 個）：
- `tests/unit/test_federation.py` (75 tests, BLOCKER-03)
- `tests/unit/test_graph_cas.py` (17 tests, HIGH-01)
- `tests/unit/test_find_conflicts.py` (20 tests, HIGH-03)
- `tests/unit/test_execute_write.py` (18 tests, MEDIUM-01)
- `tests/unit/test_arch_decisions_v05.py` 更新（§6.2 目錄重構後的路徑修正）

### 文件更新

- `docs/ARCHITECTURE_REVIEW.md` §3 BLOCKER-03 / HIGH-01 / HIGH-03 / MEDIUM-01
  / §6.2 — 全部標記 ✅ 完成於 v0.33.0
- `docs/ARCHITECTURE_REVIEW.md` §5.2 Phase 2 表格 — 4 個項目狀態 ⏳ → ✅
- `pyproject.toml` — version 0.32.0 → 0.33.0

### Phase 2 進度

✅ BLOCKER-01 (v0.32) · ✅ BLOCKER-03 + HIGH-01 + HIGH-03 + MEDIUM-01 (v0.33)
⏳ 剩餘 **MEDIUM-04**（KRB staging 自動清理，3h Haiku）— Phase 2 最後一項，
預計滾入 v0.34。

### v0.34 預計（§8.4 可觀測性與可維護性）

- MEDIUM-02 KG/BrainDB 事件同步
- MEDIUM-04 KRB staging 自動清理
- MEDIUM-07 CI benchmark baseline
- Pipeline metrics dashboard
- `brain health` 命令

---

## v0.32.0（2026-04-09）— BLOCKER-01 Pipeline 神經接通

測試基準：888 passed（+28 新增 LLMJudgmentEngine + PipelineWorker 測試）

### BLOCKER-01 — 自動知識生產管線 Layer 3 + 背景 Worker

**問題**：v0.31 之前 `pipeline.py` docstring 寫「由 LLMJudgmentEngine 產生」但整個類別不存在。Signal 能入隊（Layer 1/2 ✓），`KnowledgeExecutor` 能寫入（Layer 4 ✓），但中間的 LLM 判斷層完全缺席 → 所有 signal 永遠停在 `pending` 狀態，30 天後被標記 `skipped`。

**修法**：新增兩個獨立模組

#### `project_brain/llm_judgment.py`（新檔，319 行）

- `LLMJudgmentEngine` — Layer 3 核心類別
- `from_brain_config(brain_dir)` 工廠方法：
  - 優先使用 `[pipeline.llm]` Ollama（gemma4:27b MoE）
  - Ollama 不可用時 fallback → Anthropic Haiku 4.5
  - 最終備援：預設 OllamaClient
- `analyze(signal, related_nodes)` → `KnowledgeDecision`：
  - 結構化 JSON prompt（含 Rule/Pitfall/Decision/ADR/Component 分類規則）
  - 輸出經由 `KnowledgeExecutor.validate()` 清洗（confidence ≤ 0.85 上限）
  - Prompt Injection 防護（共用 `_INJECTION_PATTERNS`）
  - JSON 解析容錯：處理 markdown fence、前後雜訊、空回應
  - LLM 任何異常 → 安全降級為 `skip`（reason 含 `llm_error:` 前綴）
- Duck-typed client 介面：同時支援 `anthropic.Anthropic` 和 `krb_ai_assist.OllamaClient`

#### `project_brain/pipeline_worker.py`（新檔，248 行）

- `PipelineWorker` — Layer 3.5 背景迴圈
  - `_loop()`: `dequeue_batch` → `judge.analyze` → `executor.run` → `mark_done/failed`
  - 任何異常都只 log，不終止迴圈
  - 每 100 輪呼叫 `cleanup_stale()` 清理過期 pending signals
  - `start()` / `stop()` 提供完整生命週期
- `start_global_worker(brain_db, brain_dir)` — 全域單例工廠
  - 讀 `brain.toml [pipeline.enabled]`，false 時直接 no-op
  - `[pipeline.worker_interval_seconds]` 控制輪詢間隔（預設 60s）
  - 幂等：重複呼叫回傳同一 worker

#### `mcp_server.create_server()` 整合

- 在 decay daemon 和 session cleanup daemon 之後啟動 pipeline worker
- 仿 `_decay_daemon_started` guard 模式防止重複啟動
- 啟動失敗只記 warning，不影響 MCP server 本身

#### `brain.toml [pipeline]` 註釋更新

- 明示「v0.32+ Layer 3 已實作，worker 會真正消費 signal_queue」
- `enabled=false` 作為停用選項

#### 測試（28 個新增）

- `tests/unit/test_llm_judgment.py`（16 個）：J-01 ~ J-14 涵蓋 analyze、降級、JSON 解析容錯、prompt 安全、confidence 上限、from_brain_config 容錯
- `tests/unit/test_pipeline_worker.py`（12 個）：W-01 ~ W-12 涵蓋 add/skip/failed 流程、批次處理、thread 生命週期、全域單例、迴圈韌性

#### 架構意義

v0.32 後 Signal Pipeline 真正跑起來：
```
git commit → Signal enqueue → [60s 輪詢] → LLMJudgmentEngine →
  KnowledgeDecision → KnowledgeExecutor → L3 node (auto_pipeline 標記)
```

使用者不再需要手動 `brain add`，git commit 後 Brain 會自主決定是否提取知識。

---

## v0.31.0（2026-04-09）— Phase 1 止血修復

測試基準：860 passed（排除 14 個既有 WebUI/schema-version 失敗）

### BLOCKER-02 — review_board.approve() 雙 DB 原子化

- `review_board.py:approve()` 改為先寫 BrainDB（FTS5 索引），再寫 KnowledgeGraph
- BrainDB 失敗時直接 raise，staged_nodes 保持 `pending`（不再靜默損壞）
- KnowledgeGraph 失敗時自動回滾 BrainDB（`delete_node`），再 raise
- 消除「L3 節點存在但 FTS5 搜不到」的長期資料不一致狀態

### HIGH-02 — BUG-07 `brain init` 假 ERROR log

- `brain_db.py:migrate_from_legacy()` 加表存在性預檢（`sqlite_master` 查詢）
- 不存在的 legacy 表改為 `logger.debug` 跳過，不再輸出 ERROR
- `brain init` 在既有 DB 上不再誤報失敗

### HIGH-04 — multi_brain_query workdir 路徑驗證強化

- `mcp_server.py:multi_brain_query()` 對 `extra_brain_dirs` 每個路徑補充：
  - `..` 部分檢查
  - 符號連結解析後的 `_FORBIDDEN_ROOTS` 檢查（防 symlink 攻擊）
- `BRAIN_EXTRA_DIRS` 環境變數路徑同步套用相同防護

### MEDIUM-05 — EXPAND_LIMIT 硬上界

- `context.py:EXPAND_LIMIT` 加 `min(..., 100)` 截斷
- 防止 `BRAIN_EXPAND_LIMIT=10000` 觸發 FTS5 查詢爆炸

### 文件

- 新增 `docs/ARCHITECTURE_REVIEW.md`（v0.30 系統反思與重構架構書，1409 行）
  - 3 BLOCKER + 4 HIGH + 7 MEDIUM + 5 LOW 缺陷清單
  - Phase 1-4 修復路線圖，含雙軌模型標註（開發 Model / 運行 Model）

---

## v0.30.0（2026-04-06）— FEAT-09 brain.toml 統一配置 + 自動降級

測試基準：624 passed（Phase 1 Step 2 KnowledgeExecutor 18 tests）

### FEAT-09 — `brain.toml` 統一配置檔 + 自動降級

- 新增 `project_brain/brain_config.py`：`BrainConfig` dataclass 體系（`LLMConfig`、`LLMFallbackConfig`、`ModelOverride`、`PipelineConfig`、`EmbedderConfig`、`DecayConfig` 等）
- `load_config(brain_dir)` 實作四層優先鏈：env var > `.brain/brain.toml` > `~/.config/brain/brain.toml` > code default
- `get_llm_client(task, brain_dir)` 實作每任務模型選取 + 多層 fallback（gemma4:27b → gemma4:31b → Haiku）
- `_is_ollama_available(base_url, timeout=2)` 探測 `/api/tags`，Ollama 不可用時自動切至 fallback
- `generate_brain_toml(brain_dir, local_only=False)` 生成帶中文說明的 `brain.toml` 模板
- `brain init` 重寫：呼叫 `run_setup()` 後同步生成 `brain.toml`；`brain setup` 保留為 alias
- `brain config init` 子命令：單獨重新生成 `brain.toml`（不重建 DB），已存在時提示確認
- `brain.toml` 包含記憶層說明註釋：L1（工作記憶，無 LLM）、L2（情節記憶，pipeline.llm）、L3（語意知識，pipeline.llm + embedder）
- 向後相容：`BRAIN_LLM_PROVIDER`、`BRAIN_OLLAMA_URL`、`BRAIN_OLLAMA_MODEL` 等舊 env var 仍有效
- 遷移：`nudge_engine.py`、`memory_synthesizer.py`、`conflict_resolver.py`、`cli_utils.py` 的 fallback 邏輯統一至 `brain_config`

### brain.toml 補充調整（post v0.30.0）

- **`[review]` 新增 KRB 配置**：`auto_approve_threshold`、`staging_ttl_days`、`min_confidence`
- **`[review.model]` 獨立 KRB 模型設定**：provider / model / base_url，預設 gemma4:31b（Dense，品質優先）；Ollama 不可用時 fallback 至 `[pipeline.llm]`
- **`[decay]` 移除六因子權重手動設定**：`weight_time` 等欄位從模板移除，改為說明註釋（手動調整需加總 1.0，容易出錯）
- `brain_config.py` 新增 `ReviewModelConfig`、`ReviewConfig` dataclass；`_build_config()` 解析 `[review.model]`；新增 `get_krb_client(brain_dir)` 函式
- `krb_ai_assist.py` 新增 `KRBAIAssistant.from_brain_config(krb)` classmethod（推薦初始化方式），fallback chain：`[review.model]` Ollama → `[pipeline.llm]` Ollama → Haiku；舊的 hardcode `DEFAULT_MODEL = haiku` / `DEFAULT_OLLAMA_MODEL = llama3.2` 僅作為最終備援

---

## v0.29.0（2026-04-06）— OPT-07~10 效能優化 + 自動知識管線設計文件

### OPT-07 — Nudge Engine 使用衰減後 confidence

- `nudge_engine.py` `generate_questions()` 改讀 `effective_confidence`（decay_engine 寫入值），取代原始 `confidence`
- 效果：Nudge 推薦優先級反映實際知識新鮮度，不再推薦 6 個月前的過時知識

### OPT-08 — KnowledgeGraph 複合索引

- `graph.py` schema 新增 `CREATE INDEX IF NOT EXISTS idx_nodes_type_created ON nodes(type, created_at DESC)`
- 對「列出所有 Pitfall 按時間排序」類查詢速度提升 10× 以上
- Migration：現有 DB 自動補建索引

### OPT-09 — Logging 結構化

- 全域 logger 改用 JSON formatter（`{"level": "warning", "module": "brain_db", "event": "...", ...}`）
- 可機器讀取，相容 ELK / Grafana Loki 整合
- 保留 `%(levelname)s` 文字模式作為 fallback（`BRAIN_LOG_FORMAT=text`）

### OPT-10 — Embedder Cache 命中率統計

- `embedder.py` 新增 `_cache_hits`、`_cache_misses` 計數器
- `brain status` 新增 Embedder 區塊，顯示 cache 命中率與 miss 次數
- `_TFIDF_CACHE` 超過 256 條時自動清除最舊項目（LRU 保護）

---

## v0.28.0（2026-04-06）— FEAT-05~06 匯出格式擴充 + 自動備份

### FEAT-05 — 匯出支援 GraphML

- `brain_db.py` 新增 `export_graphml(output_path)` 方法
- `brain export --format graphml` 輸出標準 GraphML XML 格式（含 `<key>` 宣告）
- 可直接匯入 Gephi / yEd / Neo4j
- 節點屬性：title、type、content、confidence、scope、tags、created_at；邊屬性：relation、weight
- 同步支援 `--format json`（原有 CSV 保留）

### FEAT-06 — BrainDB 自動每日備份

- `brain_db.py` `__init__` 新增 `_maybe_backup()` 呼叫
- 每次 BrainDB 啟動時自動檢查今日（`YYYYMMDD`）是否已備份
- 備份方式：`VACUUM INTO .brain/backups/brain_YYYYMMDD.db`（原子操作，自動 checkpoint WAL）
- 保留最近 7 份，超出時自動刪除最舊備份
- 備份失敗只寫 `logger.warning`，不影響正常啟動

---

## v0.27.0（2026-04-06）— FEAT-04 版本 Diff + REFACTOR-01 CLI 精簡

### FEAT-04 — 知識節點版本 Diff 視圖

- `cli_knowledge.py` `cmd_history()` 新增 `--diff` 旗標
- `brain history <node_id> --diff` 使用 `difflib.unified_diff` 顯示相鄰版本差異
- 每對版本最多輸出 40 行，超出省略並提示總行數
- 無 `--diff` 時保持原有版本清單行為

### REFACTOR-01 — CLI 命令精簡（37 → 27 個）

- 移除 9 個冗餘命令：`context`（alias `ask`）、`health`（合入 `doctor`）、`health-report`（合入 `report`）、`timeline`（alias `history`）、`restore`（alias `rollback`）、`analytics`（合入 `report`）、`deprecate`（合入 `deprecated mark`）、`lifecycle`（合入 `deprecated info`）、`counterfactual`（AI 使用 MCP tool）
- `_apply_aliases()` 補入向後相容 redirect，舊命令輸出 deprecation warning 並自動轉發
- `brain --help` 僅顯示 14 個 Primary 命令；`brain --help --advanced` 顯示全部
- `brain history <id>` 吸收 `timeline`；`brain rollback <id>` 吸收 `restore`
- `brain report --analytics` 吸收 `analytics`
- `brain deprecated mark/info` 吸收 `deprecate`/`lifecycle`

---

## v0.26.0（2026-04-06）— P2 安全強化 + 效能優化 + 功能補全

測試基準：624 passed（59 unit tests in `test_mem_improvements.py`）

### SEC-01 — workdir 符號連結路徑遍歷防護

- `mcp_server.py` `_validate_workdir()`：新增 `_FORBIDDEN_ROOTS` 常數（`/etc`, `/sys`, `/proc`, `/dev`, `/boot`, `/run`）
- 先 `.resolve()` 再驗證解析後路徑不在禁止根目錄內，防止 symlink 繞過
- 防護點：先前只檢查 `..` in parts，symlink `/tmp/evil -> /etc` 可完全繞過

### SEC-03 — subprocess commit_hash 注入防護

- `extractor.py`：`re.fullmatch(r"[0-9a-f]{7,40}", commit_hash)` 驗證後再執行 git subprocess
- 無效 hash 直接 skip 並 `logger.warning`，不進入 subprocess

### SEC-04 — `_brain_cache` LRU 大小限制

- `mcp_server.py`：`_brain_cache: dict` 改為 `OrderedDict`（from collections）
- 新增 `_MAX_BRAIN_CACHE = int(os.environ.get("BRAIN_CACHE_SIZE", "32"))`
- `_resolve_brain()`：cache hit → `move_to_end(key)`；cache miss + 超限 → `popitem(last=False)` 淘汰最舊
- `multi_brain_query` 的直接 cache 操作同步套用 LRU 邏輯

### OPT-01 — Impact Analysis N+1 查詢消滅

- `graph.py` `neighbors()` BFS 多跳改為批量 `IN (?)` 查詢，從每節點一次 DB 呼叫降為每跳一次
- `impact_analysis()`：原 4 次 `neighbors()` 呼叫合併為 1 次 `neighbors(depth=1)`，再按 `relation` / `type` 分流

### OPT-03 — subprocess timeout 防護

- `extractor.py` 所有 `subprocess.check_output` 加 `timeout=30`
- `TimeoutExpired` 捕獲後 `logger.warning` + 設 `diff = ""`，不中斷整個掃描

### OPT-05 — Hybrid Search 權重可設定化

- `brain_db.py` `_adaptive_weights()` 從 `@staticmethod` 改為 instance method
- 權重解析優先順序：1. env var `BRAIN_FTS_WEIGHT` / `BRAIN_VEC_WEIGHT` → 2. `.brain/config.json` `{"search": {"fts_weight": X}}` → 3. 自適應啟發
- 新增 `_load_search_config()` 讀取 `.brain/config.json` 的 `search` 節

### OPT-06 — Extractor LLM 指數退避重試

- `extractor.py` `_call()`：最多 3 次重試，延遲 1s / 2s
- 可重試條件：`ratelimit` / `rate_limit` / `timeout` / `overload` / `529` / `503` 類型錯誤

### FEAT-01 — Decay Engine 日常自動執行

- `mcp_server.py`：新增 `_DECAY_DAEMON_INTERVAL`（預設 86400s，可 `BRAIN_DECAY_INTERVAL` 覆寫）
- `create_server()` 結尾啟動 `brain-decay` daemon thread，每日呼叫 `DecayEngine.run()`
- 以 `_decay_daemon_started` 旗標防止多次啟動

### FEAT-02 — `batch_add_knowledge` MCP 工具

- 新增 `batch_add_knowledge(items: list[dict], workdir: str)` MCP tool
- 最多 50 筆批量新增，單次 MCP round-trip，減少逐筆呼叫的網路開銷
- 回傳 `{"ok": True, "created": N, "node_ids": [...], "errors": [...]}`

### FEAT-03 — ContextEngineer 節點類型預算可設定化

- `context.py`：新增 `_DEFAULT_TYPE_LIMITS` 與 `_get_type_limit(node_type, brain_dir)` 函式
- 限制解析優先順序：1. env var `BRAIN_LIMIT_PITFALL` 等 → 2. `.brain/config.json` `{"context": {"limits": {"Pitfall": N}}}` → 3. 原始預設值
- 向量搜尋路徑與 FTS 路徑均套用可設定限制

---

## v0.25.0（2026-04-06）— P1 Bug Blitz：資料正確性六項修復

測試基準：468 passed（+14 新測試），原 454 passed 基準

### BUG-01 — FTS5 雙寫原子化

- `brain_db.py` `add_node()`：nodes INSERT + nodes_fts DELETE/INSERT 包進同一 try/except
- FTS 失敗 → `conn.rollback()` → re-raise（不再靜默提交半殘節點）
- 額外修復：`valid_from` SELECT 移入 `_write_guard` 鎖內，防止並發 API misuse
- 測試：`test_fts_failure_rolls_back_main_insert`、`test_valid_from_select_is_inside_write_guard`

### BUG-02 — Decay 單一來源 + 防止雙重衰減

- `decay_engine.py` 移除自行定義的 `BASE_DECAY_RATE = 0.003`，改 import `constants.py`
- `brain_db._effective_confidence()`：若 `meta.decayed_at` 存在（decay_engine 已跑過），直接回傳 `confidence + F7`，不再套用 F1 時間衰減（防止雙重衰減）
- 未經 decay_engine 的節點仍套用完整 inline F1+F7
- 測試：`test_decay_engine_uses_constants_base_decay_rate`、`test_effective_confidence_no_double_decay_after_decay_engine`

### BUG-03 — Rate Limit 精確驗收

- 現有 `>= RATE_LIMIT_RPM` + `_rate_lock` 組合已正確限制，確認不存在 off-by-one
- 新增測試驗證：連打 N 次通過，第 N+1 次拒絕

### BUG-04 — Session Cleanup Daemon

- `mcp_server.py`：新增 `_cleanup_daemon_started` 標記與 `_cleanup_daemon_lock`
- `create_server()` 結尾啟動 daemon thread（每 5 分鐘清理過期 session）
- 以 `daemon=True` 確保 MCP server 退出時自動終止
- 測試：`test_cleanup_removes_expired_sessions`

### BUG-05 — 無聲異常消滅

- `mcp_server.py:178`：`except Exception: return brain` → 加 `logger.warning`
- `mcp_server.py:261`：`except Exception: pass` → 加 `logger.warning` + `exc_info=True`（session dedup 核心路徑）
- `nudge_engine.py`：三處 `except Exception: pass/return []/""`  → 加 `logger.debug`

### BUG-06 — KnowledgeGraph 樂觀鎖

- `graph.py` schema：`nodes` 表新增 `version INTEGER NOT NULL DEFAULT 0`
- `_migrate_schema()`：既有 DB 自動 `ALTER TABLE` 補欄位
- 新增 `ConcurrentModificationError(Exception)` 異常類別
- `update_node()`：UPDATE 增加 `AND version = ?`；rowcount=0 時拋 `ConcurrentModificationError`
- 測試：`test_update_node_increments_version`、`test_concurrent_modification_raises`

---

## v0.24.0（2026-04-06）— memdir 啟發：新鮮度修復與 AI 選取器強化

測試基準：903 passed / 5 skipped（WebUI pre-existing failures 不計）

### MEM-07 — 新鮮度基準改為 `updated_at`

- `context.py` `_freshness_note()` 簽名從 `(created_at: str)` 改為 `(node: dict)`
- 使用 `updated_at` 作為新鮮度基準，fallback 到 `created_at`（向後相容）
- 效果：更新過的節點（即使建立於 180 天前）不再誤警

### MEM-08 — `_SonnetSelector` 改用 `tool_use` + 索引輸出

- `engine.py` 新增 `_SELECT_TOOL` schema 與 `_SELECT_PROMPT_IDX`
- Manifest 格式改為 `[i] (type) title — description`（0-based 索引）
- `tool_choice={"type": "tool", "name": "select_nodes"}` 強制結構化輸出
- 效果：json.loads 解析失敗率 ~0%；索引取代字串 ID，杜絕 LLM 幻想不存在的 ID
- `_OllamaSelector` 保持 json.loads（Ollama tool_use 支援不一致）

### MEM-09 — 新鮮度警告文字強化

- 直接採用 memdir `memoryFreshnessText()` 設計哲學
- 新警告文字：「此知識最後更新於 **N 天前**。知識節點是時間點快照，非即時狀態——`file:line` 引用可能已過時。引用前請以 `grep` 或 `Read` 工具驗證現況。」
- 三個設計點：說明什麼最容易過期（file:line）、給出驗證方式（grep）、框架定位（快照非即時）

### MEM-10 — `alreadySurfaced` 前移至 AI 選取前

- `engine.py` get_context()：`exclude_ids` 在 `selector.select()` 呼叫前過濾
- 修改前：AI 選 5 → 過濾 already_surfaced → 可能剩 < 5 個
- 修改後：先過濾 → AI 從 unseen 中選 5 → 5-slot 全部用於新知識
- 新增：`unseen = [c for c in candidates if c.get('id') not in _ai_exclude]`

---

## v0.23.0（2026-04-06）— 知識生產斷路修復（AUTO-01~03）

測試基準：892 passed / 5 skipped

> **背景**：程式碼審計發現 `KnowledgeExtractor` 已完整實作，但兩條知識生產路徑（Session / Git）都有關鍵斷路，導致 KB 無法自動累積。

### AUTO-01 — PostStop Hook 接通 Git 路徑

- `.claude/settings.json` 新增 `Stop` hook：每次 Claude 停止後執行 `brain backfill-git --limit 1`
- `backfill-git` 已有 `source_url` 去重機制，不重複處理同一 commit
- Hook 使用 `; exit 0` 確保失敗時不影響 Claude 正常停止

### AUTO-02 — `complete_task` 接通 `from_session_log()`

- `mcp_server.py` 移除 inline 知識生產邏輯（`title = content[:80]` 截斷）
- 改用 `KnowledgeExtractor.from_session_log()` 作為唯一實作（消除死碼）
- `extractor.py` `from_session_log()` title 提取改為：`re.split(r'[。.！!？?\n]', text)[0][:60]`（取第一句話）
- 效果：節點 title 可召回；`from_session_log()` 從死碼變為主要路徑

### AUTO-03 — `KnowledgeExtractor._call()` 改用 `tool_use`

- `extractor.py` Anthropic provider 改用 `tool_use` + `_EXTRACT_TOOL` schema
- 強制輸出 `knowledge_chunks / components_mentioned / dependencies_detected` 結構
- OpenAI/Ollama provider 保持 json.loads（一致性與 AUTO-03 的 MEM-08 決策）

---

## v0.22.0（2026-04-05）— 記憶系統六項改善（MEM-01~06）

測試基準：884 passed / 5 skipped（+26 新增單元測試）
Schema 版本：v22（新增 `description` 欄位）

### MEM-01 — AI 輔助相關性選取（三層降級架構）

- `engine.py` 新增 `_KeywordSelector` / `_OllamaSelector` / `_SonnetSelector` 三個選取器類別
- `_resolve_selector()` auto 模式：Ollama 在跑 → OllamaSelector；有 API key → SonnetSelector；否則 → KeywordSelector
- `get_context()` 新增 `ai_select: bool = False` 參數；MCP 工具同步新增
- 選取器拋錯時自動降級到 KeywordSelector，永不失敗

### MEM-02 — `description` 欄位 + 摘要/全文分層載入

- `brain_db.py` SCHEMA_VERSION 21 → 22，migration 新增 `description TEXT NOT NULL DEFAULT ''`
- `add_node()` 支援 `description` 參數；空白時自動截取 `content[:100]`
- MCP `add_knowledge` 工具新增 `description` 參數
- `get_context(detail_level="summary")` 只回傳 title + description（< 200 tokens）

### MEM-03 — Session 內 `alreadySurfaced` 去重

- `mcp_server.py` 新增 `_session_served: dict[str, set[str]]`，以 workdir 為 key
- TTL 30 分鐘自動清除（`_cleanup_expired_sessions()`）
- `get_context` MCP 工具新增 `force: bool = False` 參數跳過去重

### MEM-04 — 過時節點明確警告文字

- `context.py` 新增 `_freshness_note()`：超過 `BRAIN_FRESHNESS_WARN_DAYS`（預設 30）天的節點附加警告
- `_fmt_node()` 呼叫 `_freshness_note()` 並將結果注入 context 輸出

### MEM-05 — `recentTools` 相關節點降權

- `context.py` `build()` 新增 `current_context_tags` 參數
- Rule/Decision 節點 tags 與 `current_context_tags` 重疊 ≥ 50% 時降權（分數乘 0.5）
- **Pitfall 永遠不降權**（正在執行時最需要踩坑警告）

### MEM-06 — 摘要層 / 詳細層 Context 分離

- `get_context()` 新增 `detail_level: str = "full"` 參數
- `summary` 模式：回傳 `[id[:8]] (type, conf%) title — description`，< 200 tokens
- `full` 模式（預設）：回傳完整 content，維持現有行為
- 依賴 MEM-02 `description` 欄位

---

## v0.21.0（2026-04-05）— WebUI UX 強化、CLI 可觀測性與效能優化

### UX-01 — WebUI 篩選狀態 URL 持久化

- **`web_ui/server.py`** 新增 `_syncHash()` / `_restoreHash()` 函式：
  - `_syncHash()`：將 `currentFilter`（kind）、`confFilter`（信心）、`pinnedFilter`（釘選）序列化至 `location.hash`（`#kind=Rule&conf=hi&pin=1`）
  - `_restoreHash()`：頁面載入時讀取 hash，恢復篩選狀態（設定 currentFilter、confFilter、pinnedFilter 及對應 UI 高亮）
  - `filterKind()`、`filterConf()`、`filterPinned()` 結尾均呼叫 `_syncHash()`
  - Boot 時先呼叫 `_restoreHash()` 再 `loadGraph()`，確保首次載入使用正確 kind filter
- 效果：篩選後刷新頁面或分享 URL，對方看到相同的篩選視圖

### FEAT-09 — `brain backfill-git` 進度顯示

- **`cli_admin.py`** Phase 1 迴圈改為行內進度輸出（`\r  [i/total] hash: msg`），每個 commit 即時更新，不再靜默等待
- `--limit 0`：不限制掃描深度（原本 0 等同 git log 預設行為，現明確定義為「掃描全部 commit」）
- 完成後清除進度行，輸出彙總：`共新增 N 個知識節點（掃描 M 個 commit）`

### OBS-04 — `brain health` MCP 連接狀態檢查

- **`cli_admin.py`** 新增 `cmd_health(args)`：
  - TCP connect `127.0.0.1:{port}` 並回報延遲（ms）；失敗時提示 `brain serve --mcp`
  - 檢查 `.brain` 目錄存在性，列出 `brain.db` / `knowledge_graph.db` 大小
  - `--mcp-port N` 覆蓋 `BRAIN_MCP_PORT` 環境變數（預設 3000）
- **`cli_utils.py`** 新增 `brain health [--mcp-port N]` 子指令
- **`cli.py`** 匯入 `cmd_health` 並加入 dispatch 表

### PERF-07 — `session_store.py` list() 指定欄位

- `list()` 查詢由 `SELECT *` 改為 `SELECT key, value, category, session_id, created_at, expires_at, meta`，明確排除自動遞增 `id`（`_row_to_entry()` 不使用），減少不必要的欄位傳輸

---

## v0.20.0（2026-04-05）— 並發安全與資料一致性修復

### SEC-05 — `_brain_cache` 並發競態修復（mcp_server.py）

- 新增 `_cache_lock = threading.Lock()` 保護模組級 `_brain_cache` dict
- `_resolve_brain()` 與 `multi_brain_query()` 兩處 read-check-write 均改為 `with _cache_lock:` 原子操作
- 防止並發 workdir 切換造成 `ProjectBrain` 重複初始化（雙重 SQLite WAL 連線 / 快取覆蓋）
- 對比：`_session_nodes` 已有 `_snodes_lock`，`_brain_cache` 補齊同樣保護

### REL-01 — `update_node()` FTS 失敗後未 rollback 修復（brain_db.py）

- 原實作：`UPDATE nodes` 成功後，FTS sync 若失敗只 log，`conn.commit()` 仍執行 → 節點資料與 FTS 索引不一致，更新後搜尋無法命中
- 修復：將 `UPDATE nodes` + `DELETE/INSERT nodes_fts` 包進單一 `try` 區塊；任一步驟失敗即 `conn.rollback()` + `raise`，保持原子性
- `node_history` snapshot 保持獨立 try-except（審計記錄失敗不應阻止主要更新）

---

## v0.19.0（2026-04-05）— WebUI 信心分布與篩選功能

### WebUI — 信心分布面板

- **`web_ui/server.py`** `_route_stats()`：新增 `conf_dist: {hi, med, low, vlow}` 至統計 API 回傳值
  - `hi`：`confidence >= 0.80`（✓✓ 權威）
  - `med`：`0.60 ≤ confidence < 0.80`（✓ 已驗證）
  - `low`：`0.30 ≤ confidence < 0.60`（~ 推斷）
  - `vlow`：`confidence < 0.30`（⚠ 推測）
- 側邊欄新增「信心分布」區塊（`id="conf-dist-list"`），各列可點擊篩選
- CSS：`.conf-row`、`.conf-row:hover`、`.conf-row.filter-active`、`.stat-card.filter-active`

### WebUI — 已釘選 / 低信心統計修正

- **`_route_stats()`**：`low_conf`、`pinned`、`conf_dist` 三個查詢各自獨立 try-except；消除 `type` 欄位 OperationalError 連帶歸零的問題
- **`_route_graph()` / `_route_node()`** fallback schema：所有 `cols2` 查詢補齊 `confidence, is_pinned, scope` 欄位，修正釘選後刷新頁面 `is_pinned` 仍顯示 False 的問題

### WebUI — 信心 / 釘選篩選（客戶端）

- **JS** 新增 `confFilter`（`'hi'|'med'|'low'|'vlow'|null`）與 `pinnedFilter`（`boolean`）狀態變數
- **`filterConf(key)`**：點選信心分布列 → 切換篩選（再點取消）；同步高亮 `filter-active` 樣式
- **`filterPinned()`**：點選「已釘選」stat card → 切換釘選篩選
- **`applyOpacity()`**：套用三層篩選（搜尋命中 → 信心範圍 → 釘選狀態），連線也同步暗淡

### fix(backfill-git) — AI 審核 0 個節點的根本問題修正

- **根因 A**：`add_node()` 使用 UPSERT，既有節點永不新增，before/after 差集恆為空 → 改為直接查詢 `confidence = 0.5` 節點清單
- **根因 B**：Ollama（llama3.2）對單筆提示回傳單一 JSON object `{...}` 而非陣列 `[...]`；`for item in data` 遍歷 dict keys（字串）→ 加 `if isinstance(data, dict): data = [data]`
- **根因 C**：BATCH > 1 時 Ollama ID 對應錯誤（只回傳一個物件）→ `BATCH = 1`
- 修正後：47 個 `confidence = 0.5` 節點全數通過 AI 審核並更新信心分數

---

## v0.18.0（2026-04-05）— backfill-git AI 審核整合

### FEAT-07（修訂 2）— `brain backfill-git --ai-review` Ollama 信心審核

- **`cli_admin.py`** 新增 `_ai_review_nodes()` 輔助函式：
  - 接收新增節點 ID 列表，批次呼叫 `OllamaClient`（複用 `_build_prompt` / `_clean`）
  - 每批 10 個節點，解析 JSON 回傳後直接 `UPDATE nodes SET confidence=?`
  - Ollama 連線失敗時靜默跳過，不中斷回填流程
- **`_cmd_backfill_git()`** Phase 1 前快照現有節點 ID，Phase 1 結束後計算差集得出新增節點
- **`cli_utils.py`** `backfill-git` 新增三個參數：
  - `--ai-review`：啟用 Ollama AI 審核（預設關閉）
  - `--ollama-url`：覆蓋 `BRAIN_OLLAMA_URL`（預設 `http://localhost:11434`）
  - `--ollama-model`：覆蓋 `BRAIN_OLLAMA_MODEL`（預設 `llama3.2`）

**使用方式：**
```bash
brain backfill-git --ai-review                          # 用預設 Ollama 審核
brain backfill-git --ai-review --ollama-model mistral  # 指定模型
```

---

## v0.17.0（2026-04-05）— backfill-git 完整重寫

### FEAT-07（修訂）— `brain backfill-git` 全歷史回填

舊版只能更新已存在節點的時間戳，無法從未學習的舊 commit 建立知識節點。本次重寫解決根本問題。

- **`cli_admin.py`** `_cmd_backfill_git()` 全面重寫，兩階段處理：
  - **Phase 1（建立）**：呼叫 `git log --max-count=N --pretty=%H|%s|%aI` 取得全部 commit；查詢 `nodes.source_url` 與 `episodes.source` 確認已處理清單；對每個未處理 commit 呼叫 `engine.learn_from_commit(commit_hash)`，自動以正確的 commit 日期作為 `created_at`
  - **Phase 2（補正）**：對 DB 中已存在但時間戳有誤的節點批次修正 `created_at`
- **`cli_utils.py`** `backfill-git` 新增 `--limit N`（預設 200）控制掃描深度
- 測試：執行 `brain backfill-git`，117 筆 git 歷史中回填 102 筆 commit，新增 93 個知識節點（時間戳均為各 commit 實際日期）

---

## v0.16.0（2026-04-05）— P3 長期改善版

### FEAT-05 — Analytics 時序圖表 + HTML 報告

- **`analytics_engine.py`** 新增 `generate_timeseries(period_days, bucket)` 方法：
  - 回傳 `growth`（每週/每日新增節點數）與 `confidence_dist`（信心值十段分布直方圖）
- **`cli_admin.py`** `cmd_report()` 新增 `--format html`：呼叫 `generate_timeseries()` 生成內嵌 Chart.js 的自含式 HTML 報告（成長曲線折線圖 + 信心分布柱狀圖）

### FEAT-06 — `brain doctor` 矛盾 / deprecated 比例警告

- **`cli_admin.py`** `cmd_doctor()` 在資料庫健康檢查區塊新增：
  - **deprecated 比例**：`confidence < 0.2` 節點比例 > 20% 時觸發 ⚠
  - **矛盾節點數**：查詢 `edges WHERE relation='CONFLICTS_WITH'`，> 0 時觸發 ⚠ 並提示啟用 `BRAIN_CONFLICT_RESOLVE=1`

### ARCH-08 — `ConflictResolver` 快取 TTL 驅逐

- **`conflict_resolver.py`** 新增 `_evict_stale_cache()` 方法：移除 `time.monotonic()` 差值 ≥ `CACHE_SECONDS`（86400s）的所有快取項目
- 每次呼叫 `arbitrate()` 前自動驅逐，防止長執行進程記憶體持續增長

### TEST-02 — Decay Engine 100K 節點負載測試

- **新增 `tests/chaos/test_decay_load.py`**：
  - `@pytest.mark.chaos` 標記，預設 CI 不執行
  - 建立 100K Decision 節點（1000 批次插入），執行 `engine.run(batch_size=500)`
  - 斷言完成時間 < 300 秒

### TEST-03 — 移除 Chaos / Unit 測試中的硬編碼路徑

- **`tests/chaos/test_chaos_and_load.py`** 移除 `sys.path.insert(0, '/home/claude/synthex_v10')`
- **`tests/unit/test_core.py`** 移除 `sys.path.insert(0, '/home/claude/project-brain')`

---

## v0.15.0（2026-04-05）— 審計與 PII 安全版

### OBS-03 — rollback_node() 審計記錄

- **`brain_db.py`** `update_node()` 新增 `change_type: str = "update"` 參數，並傳入 `node_history` INSERT，取代原本硬編碼的 `"update"`
- **`brain_db.py`** `rollback_node()` 新增 `actor: str = "system"` 參數；改為傳入 `changed_by=actor, change_type="rollback"`，使 rollback 記錄與普通 update 可明確區分
- 查詢方式：`get_node_history(node_id)` 回傳的記錄中，還原操作 `change_type='rollback'`，`changed_by` 為呼叫方傳入的操作者

### SEC-04 — Federation PII 過濾擴充

- **`federation.py`** 新增 3 條 regex：
  - `_PII_PRIVATE_IP`：覆蓋 RFC-1918 私有 IP（10.x.x.x、172.16–31.x.x、192.168.x.x）→ `[redacted-ip]`
  - `_PII_SLACK`：Slack workspace URL（`*.slack.com`）→ `[redacted-slack-url]`
  - `_PII_CLOUD_URL`：AWS / GCP / Azure 服務 URL（`.amazonaws.com`、`.googleapis.com`、`.azure.com`、`.azurewebsites.net`、`.blob.core.windows.net`）→ `[redacted-cloud-url]`
- `_strip_pii()` 串接所有新規則，匯出 Bundle 前自動清除

---

## v0.14.0（2026-04-05）— 可觀測性強化版

### OBS-02 — Decay Engine F1–F7 因子量測輸出

- **`decay_engine.py`** `DecayEngine.__init__()` 新增 `db` 參數（`BrainDB` 引用）
- **`decay_engine.py`** `_apply_decay()` 新增 `factors` 參數；寫入 DB 後呼叫 `db.emit("decay_factors", {...})`，payload 包含 `node_id`、各因子值（`F1_time`、`F2_version`、`F3_activity`、`F4_contradiction`、`F5_code_ref`、`F6_adoption`、`F7_access_count`，依節點情況出現）、`final`（最終信心值）、`delta`（變化量）
- **`engine.py`** `decay_engine` 屬性初始化時傳入 `db=self._db`，使 emit 路徑生效
- 可透過 `brain_db.recent_events("decay_factors")` 查詢所有衰減因子記錄，支援調參分析

---

## v0.13.0（2026-04-05）— P2 改善版

本版本完成所有 P2 改善項目。

### FEAT-07 — Git 歷史時間回填

- **`graph.py`** `add_node()` 新增 `created_at` 參數；`INSERT OR REPLACE` → `UPSERT`，`ON CONFLICT DO UPDATE` 不覆蓋 `created_at`，永久保留初始建立時間
- **`brain_db.py`** 同步修改 `add_node()`：UPSERT 保留 `created_at`；`SCHEMA_VERSION` 20 → 21
- **`archaeologist.py`** `_scan_git_history()` 在 `add_node()` 呼叫中加入 `created_at=commit_date`，歷史節點日期正確回填
- **`cli_admin.py`** 新增 `brain backfill-git [--dry-run]`：對 `source_url` 為 commit hash 或檔案路徑的節點批次更新 `created_at`，修正已建立 DB 的時間錯誤
- **`cli_utils.py` / `cli.py`** 註冊 `backfill-git` 子指令

### PERF-06 — type+confidence 複合索引

- **`brain_db.py`** migration v21：`CREATE INDEX idx_nodes_type_conf ON nodes(type, confidence DESC)`；`search_nodes(node_type=...)` type 過濾從全表掃描提升為索引掃描，10k 節點下效能顯著改善

### BUG-D03 — KRB AI Cache 永不 VACUUM

- **`krb_ai_assist.py`** `_setup_cache()`：新增 `ai_screen_meta` 表追蹤最後 VACUUM 時間；每 7 天執行一次 `VACUUM` 回收 `ai_screen_cache.db` 空間

### BUG-D04 — SessionStore FD 洩漏

- **`session_store.py`**：移除 `threading.local()` per-thread 連線；改為單一共享連線 `check_same_thread=False` + WAL 模式，與 `brain_db.py` 模式一致；長執行伺服器不再洩漏 FD

### ARCH-07 — scope 推斷邏輯去重

- **`brain_db.py`** `BrainDB.infer_scope()` 擴充為 4 步驟完整實作（git-remote → 子目錄 → workdir 名稱 → global）
- **`cli_utils.py`** `_infer_scope()` 改為委派呼叫 `BrainDB.infer_scope()`，消除兩套同步維護的推斷邏輯

---

## v0.12.0（2026-04-05）— 品質鞏固版

本版本完成所有 P1 改善項目，測試套件從 15 個失敗降至 0（868 passed / 5 skipped）。

### SEC-03 — API Key Timing Attack 修復

- **`api_server.py`**：`auth[7:].strip() != key` → `not hmac.compare_digest(auth[7:].strip(), key)`
- 防止透過計時差異推算 API key 前綴（OWASP A07）

### BUG-D01 — 靜默例外消除（29 處）

- 全專案清除 `except Exception: pass`，替換為適當的 `logger.error` / `logger.warning`
- 涵蓋 18 個檔案，包括：`brain_db.py`（6 處）、`cli_knowledge.py`（7 處）、`graph.py`（5 處）、`federation.py`（4 處）、`engine.py`（3 處）等

### BUG-D02 — Embedder Cache 競態修復

- **`embedder.py`**：新增 `_embedder_lock = threading.Lock()`，保護 `_embedder_cache` 的所有讀寫路徑（5 處 cache write + 1 處 cache read）

### BUG-E01 — `_search_batch` 截斷修復（False Negative）

- **`context.py`**：`_search_batch(terms[:8])` → `_search_batch(terms)`（全詞傳遞，不截斷）
- **`context.py`**：Rule 類節點配額 `limit=2` → `limit=3`
- **`synonyms.py`**：新增 5 條 API 版本化同義詞（「版本」「版本號」「路徑」「header」「versioning」），條目總數 46 → 51
- 修復 benchmark 召回測試案例 `api-01`（如何設計 API 版本號）的 False Negative

### PERF-05 — Decay N+1 查詢批次化

- **`decay_engine.py`**：`_detect_contradictions()` 由每對矛盾各一次 `SELECT confidence` 改為單次批次預取 `WHERE id IN (?)` dict；消除 N+1 查詢模式

### TEST-01 — 修復全部失敗測試（15 → 0）

- **`web_ui/server.py`**：`create_app()` 改為回傳真實 Flask WSGI app，修復 16 個 `AttributeError`
- **`graph.py`**：`search_nodes()` FTS5 查詢加 `threading.Lock()`，修復並行讀取測試的 `bad parameter or other API misuse`
- **`tests/unit/test_core.py`**：修復 4 個路徑（`/home/claude` → `Path(__file__).parent`）、lora 回傳值解包、embedding cache key 公式
- **`tests/test_core.py`**：同步修復路徑與 lora 測試
- **`tests/unit/test_arch_decisions_v06.py`**：同義詞數量 46 → 51
- **`tests/unit/test_arch_decisions_v03.py`**：embedder cache 污染隔離
- **`tests/chaos/test_chaos_and_load.py`**：修復硬編碼 `/home/claude/synthex_v10/brain.py` 路徑
- **`tests/test_chaos_and_load.py`**：修復硬編碼 `/home/claude/synthex_v10` sys.path

---

## v0.11.0（2026-04-04）— AI 全自主版

### KRB-01 — 自主審核（Autonomous KRB）

- **`review_board.py`** `RB_SCHEMA_VERSION=3`：`confidence` 欄位 migration；`INITIAL_CONF_BY_SOURCE`（git-*=0.85, mcp=0.80, manual=0.75, scan=0.60）；`submit()` 從 source 推斷初始信心；`approve()` 傳遞 confidence 至 L3；`auto_approve_by_confidence()`（≥0.75 auto-approve / 0.50–0.74 approve@0.55 / <0.50 reject）；`list_audit_log()`
- **`engine.py`** `StagingGraph`：掃描後自動對每個 `staged_id` 呼叫 `auto_approve_by_confidence()`；`learn_from_commit()` 使用 `git log -1 --pretty=%aI` 取實際 commit 日期
- **`cli_knowledge.py`**：`brain review list` 預設顯示 audit log；`--pending` 顯示人工審查佇列（KRB-01 模式下永遠空）
- **環境變數**：`BRAIN_KRB_AUTO_APPROVE`（預設 0.75）/ `BRAIN_KRB_AUTO_REJECT`（預設 0.50）

### FEAT-03 — 時間感知查詢（Temporal Query）

- **`brain_db.py`** SCHEMA_VERSION=19：`ALTER TABLE nodes ADD COLUMN valid_from TEXT DEFAULT NULL`；`add_node()` INSERT OR REPLACE 前先讀取現有 `valid_from` 確保不遺失；新增 `nodes_at_time(at_time, limit, node_type)` 查詢方法
- **`engine.py`** `_store_chunk()`：同步寫入 `brain.db` 帶 `valid_from=commit_date`
- **`mcp_server.py`** `temporal_query`：回傳 `edges` + `nodes`（節點時間快照）
- **`cli_knowledge.py`** `brain history --at <date|ref>`：顯示指定時間點知識快照；支援 git branch/tag 名稱解析

### Bug 修復

- **BUG-C01**：`mcp_server.py` `report_knowledge_outcome()` 更新 confidence 但未呼叫 `db.emit("knowledge_outcome", {...})`，導致 `analytics_engine.useful_knowledge_rate()`（brain report ROI 指標）永遠回傳 `null`。修復：`record_feedback()` 之後立即 `db.emit()`
- **BUG-C02**：`traces` 表缺少 `result_count` 欄位且 `search_nodes()` 從未寫入 traces，`query_hit_rate()` 因 `total=0` 永遠回傳 `None`。修復：SCHEMA_VERSION=20 加 `result_count INTEGER NOT NULL DEFAULT 0`；`search_nodes()` 尾端加 `INSERT INTO traces(query, result_count, latency_ms)`
- **BUG-C03**：`CLAUDE.md` 只有 8 行通用指令，缺少 Task Start Protocol 和 Knowledge Summary Protocol，知識摘要閉環從未被 Agent 觸發。修復：新增 `## Task Start Protocol`（任務開始呼叫 `get_context`）與 `## Knowledge Summary Protocol`（任務結束呼叫 `complete_task` + `report_knowledge_outcome`）

---

## v0.10.0（2026-04-04）— 長期穩定版

### REF-01 — BrainDB 拆分

- 從 ~1800 行的 God Object `BrainDB` 抽離 `vector_store.py`（`VectorStore`）和 `feedback_tracker.py`（`FeedbackTracker`）
- `BrainDB` 以 delegation 模式保持 backward compatibility，所有呼叫點零改動

### CLI-01 — cli.py 拆分

- `cli.py`（原 2864 行）拆分為 `cli_utils.py`、`cli_knowledge.py`、`cli_admin.py`、`cli_serve.py`、`cli_fed.py`
- 抽取 `@require_brain_dir` 裝飾器；`cli.py` 精簡至 240 行（目標 ≤500）
- `_build_parser()` / `_apply_aliases()` 抽至 `cli_utils`

### ARCH-04 — scope UX 統一

- `--global` flag 保留但輸出棄用警告（stderr），導引改用 `--scope global`
- 消除 scope 三路控制流（`--global` / `--scope` / 自動推斷）造成的使用者困惑

---

## v0.9.0（2026-04-04）— 深化功能版

### DEEP-04 — AI 自動裁決

- `nudge_engine.py` `auto_resolve_batch()`：rule-based 自動裁決低信心節點；`get_context()` 背景靜默觸發
- `mcp_server.py` `auto_resolve_knowledge()` MCP 工具

### FED-01 — Federation 審計日誌

- `brain_db.py` `federation_imports` 表（`source / node_id / node_title / imported_at / status`）
- 每次 federation 匯入自動記錄；`brain_db.get_federation_imports()` 查詢
- `cli_fed.py` `brain fed imports` → `cmd_fed_import_list()`

### FED-02 — 語義去重

- `federation.py` `_is_duplicate()`：Jaccard（title tokens）OR TF-IDF cosine similarity（sklearn，threshold=0.82）
- chromadb 可用時自動升級為向量比對；批量匯入語義近似知識不再膨脹

### CLI-02 — Federation CLI 完整實裝

- `cli_fed.py`：`brain fed sync / export / import / subscribe / unsubscribe / imports` 全部實裝
- `cmd_fed_sync()`：`brain fed sync [--dry-run] [--confidence 0.5]`
- `cmd_session()`：`brain session archive / list`（FEAT-04 入口）

### FEAT-04 — Session Archive

- `session_store.py` `SessionStore.archive()`：導出當前 session 為 `.brain/sessions/<id>.md`
- 90 天後自動清理舊歸檔（`_cleanup_archives()`）
- `brain session archive [--session <id>]` / `brain session list`

### OBS-01 — 可觀測性

- structlog 結構化日誌：`{event, node_id, reason, old_val, new_val}` 覆蓋 Decay / Nudge / Context 所有核心流程
- `api_server.py` `GET /v1/metrics`（Prometheus 格式）：`brain_nodes_total`、`brain_decay_count`、`brain_nudge_trigger_rate`、`brain_context_tokens_avg`

---

## v0.8.0（2026-04-04）— 知識自適應版

### DEEP-05 — Decay F6 採用率反饋

- `brain_db.py` SCHEMA_VERSION=17：`adoption_count INTEGER NOT NULL DEFAULT 0`
- `feedback_tracker.py` `record_outcome()`：採用率累計 + 信心調整
- `decay_engine.py` `_factor_adoption(n)` → `F6 = min(1.2, 1 + n × 0.02)`（最多 +20%）
- `graph.py` `increment_adoption(node_id)`：knowledge_graph.db 同步
- `mcp_server.py` `report_knowledge_outcome`：呼叫 `record_feedback()` + `graph.increment_adoption()`
- `api_server.py` `POST /v1/knowledge/<id>/outcome`：REST 入口，回傳 `{confidence, delta}`

### ARCH-05 — 弃用流程

- `brain_db.py` SCHEMA_VERSION=16：`deprecated_at TEXT DEFAULT NULL`；`_apply_decay()` 同步設置；`list_deprecated()` / `purge_deprecated(older_than_days)`
- `context.py`：推薦 deprecated 節點時加 `[已棄用]` 標記
- `cli_knowledge.py`：`brain deprecated list` / `brain deprecated purge --older-than <days>`
- `api_server.py` `GET /v1/knowledge/deprecated`

### ARCH-06 — ConflictResolver 實裝

- 新增 `conflict_resolver.py`：`ConflictResolver(db, graph, llm_client=None)`；無 LLM 時數值保守仲裁；有 `BRAIN_LLM_KEY` 時語義仲裁
- `decay_engine.py` F4 升級：`_detect_contradictions()` 偵測矛盾後寫入 `CONFLICTS_WITH` edges；仲裁後非對稱調整（winner 不懲罰，loser × 0.5）
- `BRAIN_CONFLICT_RESOLVE=1` 不再導致 ImportError

### FEAT-01 — 知識版本控制

- `brain_db.py` SCHEMA_VERSION=14：`nodes.version INTEGER DEFAULT 1`；SCHEMA_VERSION=15：`node_history.change_type TEXT`（`update / decay / feedback`）
- `update_node()`：先插入 `node_history` 完整快照，再 UPDATE nodes，`version +1`
- `cli_knowledge.py`：`brain history <node_title_or_id>` 顯示版本清單；`brain restore <node_id> --version <N>` 還原指定版本

---

## v0.7.0（2026-04-04）— 正確性優先版

### P0 快速修復

- **PERF-03**：`brain_db.py` `_count_tokens()` 加 `@lru_cache(maxsize=1024)`，消除 800+ 次/請求的高頻 CPU 浪費
- **BUG-A03**：`engine.py` 6 個懶加載屬性從共用 `_lock` 改為各自獨立的 `threading.Lock()`，消除競態死鎖隱患
- **REF-04**：新增 `project_brain/constants.py`，集中定義 4 個魔法數字（`DECAY_RATE`、`MAX_TOKENS`、`EXPAND_LIMIT`、`SIMILARITY_THRESHOLD`）
- **PERF-04**：`brain_db.py` `_expand_query()`：詞數 < 3 → 上限 10；3–5 → 15；> 5 → 20（動態調整，取代固定 15）
- **BUG-B02**：`_effective_confidence()` 和 `decay_engine._factor_time()` 改用 `MAX(created_at, updated_at)` 作為衰減時間基準（見 v0.6.0 P1 修復）
- **BUG-B01**：移除 `BrainDB.session_set/get/list/clear` 死碼，`SessionStore` 成為 L1a 唯一入口（見 v0.6.0 P2 修復）

---

## v0.6.0（2026-04-04）— 飛輪啟動版（已完成）

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

### 架構決策驗收測試（v0.3.0 decisions）

- **`tests/unit/test_arch_decisions_v03.py`**：新增 16 個測試確保 v0.3.0 四項核心決策在所有版本永久成立：
  - **OllamaClient duck-typed 決策**（4 個測試）：`OllamaClient` 無需 `anthropic` 套件；具備 `.messages.create` 介面；`KRBAIAssistant` 接受任意 duck-type client
  - **MultilingualEmbedder 優先級決策**（3 個測試）：原始碼結構確認 Multilingual 在 Ollama 之前；兩者皆可用時選 Multilingual；Multilingual 不可用時回落 Ollama
  - **Federation PII export-time 決策**（5 個測試）：`_strip_pii` 移除 email / internal hostname / .local；`_sanitise_node` 套用清理；`import_bundle` 不呼叫 `_strip_pii`
  - **ANN LinearScan fallback 決策**（4 個測試）：`LinearScanIndex` 無外部依賴；`get_ann_index()` 在 sqlite-vec 不可用時回傳 `LinearScanIndex`；兩者共享相同介面；add/search 功能正確
  - 16/16 通過（0.53s）

### P0 修復

- **BUG-A01**：`engine.py` `add_knowledge` 以 `WHERE title=?` 更新 scope 造成同名節點全部被改寫（靜默資料損毀）。改用 `WHERE id=?`；直接使用 `b.db`，移除多餘的 `new BrainDB()`；`except` 改 `logger.warning`

### P1 修復（BUG-A02 / ARCH-01）

- **BUG-A02**：移除 FTS5 觸發器 `nodes_fts_au` / `nodes_fts_ad`（與手動同步並存造成重複索引風險）；`delete_node()` 補手動 FTS5 清理；v12 migration 執行 `DROP TRIGGER IF EXISTS`；補全測試 `TestDef02FTS5Triggers`（驗證觸發器已消失，API 仍維護 FTS5 同步）
- **ARCH-01**：`mcp_server.py` 的 `temporal_query`、`mark_helpful`、`report_knowledge_outcome` 原直接 `BrainDB(_bdir)` 繞過 singleton，改用 `_resolve_brain().db`，消除多 WAL writer 鎖爭用

### P2 修復（資安）

- **SEC-01**：`brain_db.py` `search_nodes()` scope filter 原以 f-string 拼接 SQL（潛在注入路徑）。改在入口加 `re.match(r'^[a-z0-9_-]+$', scope)` 白名單驗證；非法值回退 `scope=None`
- **SEC-02**：`mcp_server.py` `_validate_workdir()` 原在 `.resolve()` 後才驗 `..`，symlink 可繞過。改為在 `.resolve()` 前先驗 `".." in Path(raw).parts`
- **BUG-A05**：`temporal_query` 的 `git_branch` 參數未驗證格式，使用者輸入直接傳入 subprocess（命令注入）。加入 `re.match(r'^[a-zA-Z0-9._\-/]+$', git_branch)` 驗證

### P2 修復（資料一致性）

- **DATA-01**：`brain_db.py` `delete_node()` 刪除前先 INSERT 到 `node_history`（記錄 title、content、confidence、`change_note='deleted'`），cascade 刪除的 edge 現在可回溯
- **DATA-02**：`_run_migrations()` 失敗後 `schema_version` 仍 +1，導致失敗的 migration 下次啟動被跳過。引入 `_genuine_failure` flag；只有成功或 benign 錯誤（`already exists`）才遞增版本
- **BUG-A04**：federation 匯出 scope fallback 忽略 scope 過濾，本地私有節點意外洩漏給接收方。fallback query 補上 `AND (scope IS NULL OR scope = 'global' OR scope = ?)`

### P2 修復（架構）

- **ARCH-02**：`BrainDB` / `KnowledgeGraph` 原使用 `threading.local()` 儲存 SQLite 連線，API server 每請求一執行緒造成 fd 洩漏。改用單一 `_conn_obj`（`check_same_thread=False`）；新增 `_make_connection()` 虛方法供 `ReadBrainDB` 覆寫（唯讀 URI）；新增 `close()` 方法明確釋放連線
- **ARCH-03**：`search_nodes` / `search_nodes_multi` 簽名不一致、回傳結構不同。`search_nodes` 加入 `terms: list | None` 參數，內建 FTS5 fast-path；`search_nodes_multi` 改為 1 行 thin wrapper；`context.py` 改呼叫 `search_nodes(terms=terms)`

### P2 修復（效能）

- **PERF-01**：`context.py` 主迴圈內逐筆 `UPDATE access_count`（N+1 寫入）。移除迴圈內 UPDATE；Spaced Repetition `executemany` 區塊成為唯一的 access_count 更新路徑
- **PERF-02**：FTS5 排序含 `CASE expression`，大資料集全掃後排序（> 5000 節點時明顯）。v13 migration 新增 `idx_nodes_pinned_conf ON nodes(is_pinned DESC, confidence DESC)`；SCHEMA_VERSION → 13

### P2 修復（重構）

- **REF-02**：`_SYNONYM_MAP` 複製於 `brain_db.py` 和 `context.py` 兩處，每次修改需同步兩處。新增 `project_brain/synonyms.py`；兩處改為 `from .synonyms import SYNONYM_MAP as _SYNONYM_MAP`
- **REF-03**：`_write_guard()` 使用 `fcntl.flock()`（Windows 完全失效，每次寫入多 1–2ms syscall）。改用 `threading.RLock`（`self._write_lock`），移除所有 fcntl 相關程式碼

### 功能 / 量測 / 文件

- **FLY-03**：`status_renderer.py` 新增「🌀 飛輪健康度」面板：近 7 天新增節點數（🟢 ≥ 5 / 🟡 ≥ 1 / 🔴 < 1）＋ Top 3 高頻 Pitfall（依 access_count 排序）
- **FLY-04**：`nudge_engine.py` `check()` 有結果時 emit `nudge_triggered` 事件到 brain.db；量測 SQL 收錄於 `CONTRIBUTING.md`，目標命中率 ≥ 30%
- **FLY-05**：知識庫自然成長率量測 SQL 收錄於 `CONTRIBUTING.md`；`brain status` 飛輪面板顯示 7 天新增數；目標 ≥ 5 節點/7 天
- **DIR-01**：`CONTRIBUTING.md` 加入「品質門檻與驗收標準」表：召回率 ≥ 60%、Chaos test 100%、靜默失效 0、Migration 可觀察率 100%
- **DIR-02**：`COMMANDS.md` 每個命令加 🟢 / 🟡 / 🔴 狀態標記（22 個命令全覆蓋），🟡 = 架構就緒需手動步驟
- **DIR-03**：`CONTRIBUTING.md` 加入「發布前隨機審計清單」：抽查 3 項 CHANGELOG 完成條目 + 四維指標 SQL + 發布 Gate checklist
- **TECH-01**：`COMMANDS.md` 命令總覽加狀態欄（🟢 端對端可用 / 🟡 架構就緒 / 🔴 實驗性）
- **TECH-02**：`COMMANDS.md` `brain distill` 已移除說明補充：輸出 JSONL 訓練設定檔，需自行搭配 Axolotl / Unsloth 執行微調
- **TECH-03**：`COMMANDS.md` 新增「向量索引說明」：< 2000 節點用 sqlite-vec；≥ 2000 建議切換 HNSW（需 `pip install hnswlib`）
- **STAB-08**：`pytest.ini` 加入 `chaos` marker 定義；`tests/chaos/test_chaos_and_load.py` 6 個 Chaos/Load 測試類加 `@pytest.mark.chaos`；CI 可執行 `pytest -m chaos` 作為 Gate

### AI 輔助 KRB 審核（PH3-03）

- **`krb_ai_assist.py` 完整實作**：三速道分流（auto-approve / manual / auto-reject）、24 小時快取、Prompt Injection 防護（拒絕含 `system:` / `ignore` / `<|` 等注入模式的 content）
- **`brain review pre-screen`**：CLI 子命令，支援 `--limit N` / `--max-api-calls N` / `--dry-run`
- **`krb_pre_screen` MCP 工具**：可在 Agent workflow 中呼叫，回傳分流結果與理由

### 測試計劃（待實作項目）

- **`tests/unit/test_ref04_constants.py`**：REF-04 魔法數字提取驗收測試（4 群組 / 11 個測試），等待 `project_brain/constants.py` 實作後執行
- **`tests/unit/test_perf03_token_cache.py`**：PERF-03 lru_cache 驗收測試（4 群組 / 18 個測試），等待 `_count_tokens` 加 `@lru_cache` 後執行
- **`tests/unit/test_bug_a03_locking.py`**：BUG-A03 雙重加鎖驗收測試（5 群組 / 15 個測試），等待 `engine.py` 拆分 `_init_lock` 後執行
- **`tests/TEST_PLAN.md`**：完整測試計劃文件（9 章節）— 涵蓋測試套件全覽、待實作計劃、真實數據量測方案（FLY-04/05、REV-02）、品質門檻總表

### 文件更新（HON-01）

- **HON-01 標記為 N/A**：`brain distill` 指令已於 v10.x 移除（COMMANDS.md 有記錄），README LoRA 說明已無對象。計劃中該項目標記為不適用並關閉

### UNQ-03 基準測試資料集與召回率量測（2026-04-04）

- **`tests/benchmarks/benchmark_recall.py`**：建立 50 節點測試知識庫（10 個 SE 領域 × 5 節點）+ 20 個有已知正確答案的查詢，量測 `get_context` 召回率：
  - **v1（FTS5 模式）**：45%（9/20）。節點只加入 `KnowledgeGraph`，`BrainDB` 空，向量路徑無法啟用
  - **v2（hybrid search 模式）**：**95%（19/20）**，embedder=`MultilingualEmbedder`，82 ms/query
    - 修復 1：`setup_test_brain()` 同時加入 `BrainDB` + 建立向量索引（`brain_db.add_vector()`）
    - 修復 2：`embedder.py` 加入 `_embedder_cache` module-level singleton，消除每次 `build()` 重複載入模型的效能問題
  - 目標 ≥ 60%（sentence-transformers）：✅ 達標；目標 ≥ 40%（LocalTFIDF）：✅ 達標
  - **結論：主要 context 來源**。hybrid search 模式下召回率 95%，可信賴作為 Agent 的主要知識注入
  - 唯一 miss：`api-01`（API 版本號），查詢語意與節點標題向量距離差距較遠，屬邊界案例

### P1 修復（BUG-B02）

- **BUG-B02 Decay 時間基準**：`_effective_confidence()`（`brain_db.py`）和 `decay_engine._factor_time()`（`decay_engine.py`）從使用 `created_at` 改為 `MAX(created_at, updated_at)` 作為衰減計算基準。820 天前建立但 3 天前更新的節點，effective_confidence 從 0.077 恢復至 0.892，解除對長期維護節點的不當懲罰

### P2 修復（BUG-B01）

- **BUG-B01 移除 BrainDB.session_\* 死碼**：移除 `BrainDB.session_set/get/list/clear` 四個方法（~50 行）及 `ReadBrainDB` 中的 2 個 PermissionError override；同步移除 `MAX_SESSION_ENTRIES` 常數及 `TestDef06SessionLRU` 測試；`import_json` 的遺留 `session_store.db` 遷移路徑改用直接 SQL INSERT（不含 LRU，遷移場景不需要）。`SessionStore`（`session_store.py`）是 L1a 的唯一業務入口；`brain.db` 的 `sessions` 表格保留供舊資料統計（`stats()` / `health_report()`）

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

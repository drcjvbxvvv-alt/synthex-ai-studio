# SYNTHEX AI STUDIO — Changelog

## v0.10.0（第十輪，2026-03-27）

### P0 修復（5項）

**P0-1：base_agent.py 完全整合 config.py**
- 移除重複的 `PRICING` dict 和 `MODEL_STRATEGY` dict
- 所有模型選擇委託給 `cfg.model_for_agent()`
- `TokenBudget` 改用 `cfg.calc_cost()`，支援 cache_read/write 精確計算
- `_budget.record()` 新增 `cache_read`、`cache_write` 參數
- `_model_display_tag()` 支援 Opus 4.6 / Sonnet 4.6 顯示名稱

**P0-2：321 個 print() 系統性整合**
- `base_agent.py` 所有 debug/info/error 日誌改用 `get_logger()`
- 保留 CLI UI 彩色輸出（這是終端機產品的 UX，不是日誌）
- `advanced_tool_use.py` logger 呼叫相容 structlog 和 stdlib logging

**P0-3：advanced_tool_use.py 遷移到 Structured Output GA 格式**
- 新增 `StructuredOutputParser.build_ga_output_config()`
  - 使用 `output_config.format`（GA，無需 beta header）
  - 不包含 `betas`、`tools`、`tool_choice`
- `build_api_params_for_schema()` 保留但內部走 GA 路徑（向後相容）
- 移除廢棄的 `STRUCTURED_OUTPUT_BETA` 常數（改為私有 `_STRUCTURED_OUTPUT_BETA_DEPRECATED`）
- 新增 `build_web_search_tool()`：支援 `web_search_20260209`（dynamic filtering，GA）

**P0-4：computer_use.py 修正 async/sync 邊界**
- 移除誤導的 `async with` 文件（實作是同步的）
- `__enter__`/`__exit__` 文件與實作一致
- 新增 `_session_id`（UUID）和結構化審計日誌
- URL 安全檢查強化：加入 `::1` localhost、有白名單時才驗證
- `_do_wait()` 限制最大等待 5 秒（防止 DoS）
- `verify_frontend_with_browser()` 使用 `cfg.model_sonnet`（非硬編碼）

**P0-5：requirements.txt 補上缺失依賴**
- 新增 `pydantic-settings>=2.3.0`（`config.py` 必要）
- 新增 `pydantic>=2.7.0`（pydantic-settings 依賴）
- 新增 `structlog>=24.1.0`（`logging_setup.py` 必要）
- 新增 opentelemetry 選填安裝說明

---

### P1 修復（4項）

**P1-1：config.py 更新 1M context window（GA）**
- `CONTEXT_WINDOWS[ModelID.SONNET_46]` 更新為 `1_000_000`
- 依據 Anthropic 2026-03-13 公告：Opus 4.6 + Sonnet 4.6 的 1M context GA
- 無溢價、無需 beta header、所有平台適用

**P1-2：brain/* 和 orchestrator.py 完全整合 config.py**
- `brain/engine.py`：新增 `cfg` import，model 改用 `cfg.model_sonnet`
- `brain/extractor.py`：新增 `cfg`/`ModelID` import，`self.model` 改用 `_DEFAULT_MODEL`
- `brain/counterfactual.py`：新增 `cfg` import，`__init__` model 參數預設值改為 `_DEFAULT_BRAIN_MODEL`
- `core/orchestrator.py`：新增 `cfg`/`ModelID` import，`route()` 中 model 改用 `cfg.model_opus`
- 全部支援 `ImportError` fallback（Brain 模組可獨立使用）
- `config.py`：`AGENT_TIER_MAP` 補上遺漏的 `PULSE`（Haiku tier）

**P1-3：AgentSwarm 部分失敗恢復（Partial Failure Recovery）**
- 新增 `FailurePolicy` enum（ABORT / CONTINUE / FALLBACK）
- `ABORT`：任何失敗立即中止（原始行為）
- `CONTINUE`：失敗 → 跳過直接和遞迴下游任務，其他繼續
- `FALLBACK`：失敗 → 使用 `fallback_result`，下游視為已解決繼續執行
- `SwarmTask` 新增 `max_retries`、`fallback_result`、`attempt` 欄位
- `SwarmTask.reset_for_retry()` 重設狀態準備重試
- `SwarmResult` 新增 `tasks_skipped`、`partial_success`、`success`、`summary()` 
- `SwarmScheduler.get_tasks_to_skip()` 遞迴計算需跳過的下游任務
- `SwarmScheduler._transitive_depends_on()` 避免循環依賴（visited set）
- `ship_with_swarm()` 預設策略改為 `CONTINUE`，各任務加入 `fallback_result`

**P1-4：PROBE Agent 整合最新版 Web Search（隱式）**
- `build_web_search_tool()` 預設使用 `web_search_20260209`（含 dynamic filtering）
- PROBE 可直接呼叫此函數取得工具定義

---

### P2 更新（測試覆蓋率）

**測試數：29 → 62（+33 個新測試）**

新增 5 個測試群組：
- `TestConfig`（7）：ModelID 常數、1M context GA、成本計算、AGENT_TIER_MAP
- `TestStructuredOutputGA`（6）：GA 格式驗證、無 beta header、web search 工具
- `TestComputerUseSecurity`（7）：URL 驗證、私有 IP 阻擋、動作限制、audit log 輪轉
- `TestSwarmFailureRecovery`（8）：三種策略、遞迴依賴跳過、retry 邏輯、SwarmResult 語義
- `TestTokenBudgetV4`（4）：cache token 追蹤、budget 超支、成本層級比較

**全部 62 tests 通過（2.73s）**

---

## v0.9.0（第九輪）
- `core/config.py` 建立集中設定（ModelID, Tier, SynthexConfig）
- Haiku 3 → Haiku 4.5 遷移（退役日 2026-04-19）
- `core/logging_setup.py` + `TokenGuard` context window 保護
- `core/rate_limiter.py` Token Bucket 速率限制
- `core/observability.py` OpenTelemetry 整合
- `core/computer_use.py` Computer Use 基礎整合

## v0.8.0（第八輪）
- P0：shell=True × 5 → argv 陣列（OS 安全）
- P0：`DocContext.write()` 和 `Checkpoint._save()` 原子寫入
- P0：`future.result()` 加 timeout（防死鎖）
- P0：`conversation_history` 記憶體洩漏修復
- P0：`run_command` 輸出大小限制
- P1：`ToolRegistry` 動態工具發現
- P1：`StructuredOutputParser` 三層 fallback
- P2：27 個 unit tests

## v0.1.0（初始版本）
- 28 個 AI Agent，8 個部門
- `synthex.py` CLI 入口（discover / ship / chat / do / brain）
- `core/web_orchestrator.py` 12-Phase 流水線
- `Project Brain` 長期記憶模組
- VS Code 擴充套件

## v0.11.0（第十一輪，2026-03-27）

### P0 修復（4項）

**P0-1：PhaseCheckpoint 雙重缺陷根除**
- `close()` 的 `NameError`：引用了 out-of-scope 的 `requirement` 變數 → 改為 `self.requirement`
- 職責分離：將「新需求重置」邏輯獨立為 `reset_for_new_requirement()`
- `_save()` 改為原子寫入：`tempfile.mkstemp()` + `os.replace()`（POSIX 原子操作）
- `_load()` 加入完整性驗證：JSON 損毀時靜默重置（不崩潰），並記錄 warning

**P0-2：run() agentic loop 加入 Context Compaction**
- 新增 `CompactionManager` 類別（兩層策略）
- 第一層（輕量）：`context_management` API 自動清除舊工具結果（server-side，`context-management-2025-06-27`）
- 第二層（重量）：手動 Compaction，token 超過閾值時呼叫 Claude 生成摘要，重置 messages（基於 Anthropic 58.6% token 節省最佳實踐）
- `run()` 新增 `enable_compaction: bool = True` 參數
- Compaction 失敗安全降級：API 錯誤時截斷舊訊息，不崩潰

**P0-3：建立 evals/ Golden Dataset**
- 新增 `evals/` 目錄（原先不存在，`evals.py` 是 453 行死程式碼）
- 4 個測試套件：`prd_quality`（3 cases）、`architecture_quality`（2 cases）、`security_quality`（2 cases）、`code_quality`（2 cases）
- `evals.db` SQLite 初始化完成
- 9 個 Golden Dataset 測試案例，覆蓋 ECHO、NEXUS、SHIELD、BYTE、STACK

**P0-4：AgentSwarm 加入 asyncio 支援**
- `_run_task()` 改用 `asyncio.to_thread()` 包裝 Agent.chat()（I/O-bound → 不阻塞）
- 新增 `run_async()` coroutine：完整 async 版本，適合 FastAPI/aiohttp 環境
- 同步版 `run()` 保留（向後相容），自動使用 `asyncio.get_event_loop()`
- 一個 Worker hang 不再阻塞其他 Worker

---

### P1 修復（2項）

**P1-1：web_orchestrator.py 整合 structlog**
- 新增 `from core.logging_setup import get_logger`
- `_phase()`、`_step()`、`_ok()`、`_warn()` 同時輸出到 structlog
- Phase 9+10 並行段加入 `_log.info("phase_parallel_start")` 和 `done`
- `_log.error()` 記錄 timeout 事件（可被監控系統捕獲）
- 保留所有 UI 彩色 print（這是 CLI 產品 UX，不是日誌）

**P1-2：CompactionManager 整合 context-management-2025-06-27**
- `build_context_management_params()` 回傳官方 `clear_tool_uses_20250919`
- 保留最近 3 個工具調用（確保模型有足夠上下文）
- 最少清除 10K tokens（避免觸發但清除太少）

---

### P2（測試覆蓋率）

**測試數：62 → 85（+23 個新測試）**

新增 4 個測試群組：
- `TestCompactionManager`（6）：token 閾值、context_management 參數結構、fallback
- `TestPhaseCheckpointFixed`（7）：NameError 修復、原子寫入、損毀處理、reset
- `TestEvalsGoldenDataset`（7）：目錄存在、JSON 有效、必要欄位、scorer 邏輯、DB 初始化
- `TestSwarmAsyncSafety`（3）：run_async 存在、coroutine function、docstring

**全部 85 tests 通過（3.01s）**

## v0.12.0（第十二輪 — Project Brain v3.0，2026-03-27）

### 核心架構升級：三層認知記憶系統

**設計理念：人類認知科學的三層記憶模型**
- L1 工作記憶 → 官方 Memory Tool（即時任務資訊，session 生命週期）
- L2 情節記憶 → Graphiti 時序知識圖譜（決策演化，因果鏈）
- L3 語義記憶 → Project Brain v2.0（深度語義，永久保留）

---

**L1 — `core/brain/memory_tool.py`（424 行）**
- 繼承 Anthropic 官方 `BetaAbstractMemoryTool`（memory_20250818）
- 實作 6 個抽象方法：`view / create / str_replace / insert / delete / rename`
- SQLite 後端（比純檔案更安全：WAL 並發、FTS5 搜尋、審計日誌、ACID）
- 安全設計：路徑驗證（阻擋穿越攻擊）、內容長度限制（防 OOM）
- `make_memory_params()` 回傳正確的 API 參數（tools + betas）
- 官方數據：84% token 節省，39% agentic 任務準確率提升

**L2 — `core/brain/graphiti_adapter.py`（370 行）**
- 整合 Graphiti 時序知識圖譜（開源，Zep 出品）
- 雙時態模型（t_valid / t_invalid）：追蹤「什麼時候是真的」
- 混合搜尋：語義 + BM25 + 圖遍歷，<100ms 查詢延遲
- 知識衝突自動 invalidate（不刪除歷史）
- 完整降級策略：Graphiti 不可用 → TemporalGraph（現有 v1.1）
- 便利函數：`episode_from_phase / episode_from_commit / episode_from_adr`
- `TemporalSearchResult.is_current` 屬性 + `to_context_line()` 格式化

**路由層 — `core/brain/router.py`（311 行）**
- `BrainRouter`：三層並行查詢 + 聚合 + Token Budget 管理
- 智能寫入路由：即時工作資訊 → L1，決策/ADR → L2+L3
- `BrainQueryResult.to_context_string()`：優先順序聚合（L1 > L2 > L3，<4K tokens）
- `learn_from_phase()` / `learn_from_commit()` 自動學習入口
- 任一層失敗不影響其他層（獨立 try/except）
- 每次查詢記錄延遲（目標：L1<10ms，L2<100ms，L3<200ms）

**整合 — `core/brain/engine.py` + `__init__.py`**
- `ProjectBrain` 新增 `router` 屬性（懶初始化 `BrainRouter`）
- `get_context()` 升級：router 已初始化時走三層聚合，否則降級到 v2.0
- `__version__` 升級至 `3.0.0`
- `__init__.py` 完整 export 新增的 v3.0 類別和函數

**降級矩陣：**
```
Graphiti ✓ + Memory Tool ✓ → 完整三層（最佳性能）
Graphiti ✗ + Memory Tool ✓ → L1 + TemporalGraph + L3
Graphiti ✗ + Memory Tool ✗ → 純 L3（Project Brain v2.0，向後相容）
```

---

**測試：85 → 110（+25 個新測試）**
- `TestBrainMemoryBackend`（8）：CRUD、路徑安全、長度限制、FTS5、session 統計、API params
- `TestGraphitiAdapter`（8）：降級行為、Episode helpers、TemporalSearchResult 語義
- `TestBrainRouter`（9）：三層查詢、工作記憶寫入、context 格式、status 完整性、版本號

**全部 110 tests 通過（3.52s）**

## v0.12.0（Project Brain v3.0，2026-03-27）

### 架構革命：三層認知記憶系統

人類認知科學的三層記憶模型正式引入 SYNTHEX：

**L1 工作記憶（Working Memory）— `core/brain/memory_tool.py`**
- 繼承 Anthropic 官方 `BetaAbstractMemoryTool`（SDK `anthropic>=0.74.0`）
- 實作 6 個官方抽象方法：`view`/`create`/`str_replace`/`insert`/`delete`/`rename`
- 底層儲存：SQLite（WAL 模式），比純檔案更安全、可查詢、可審計
- FTS5 全文搜尋，自動處理中英混合 tokenization
- 路徑安全驗證（防路徑穿越）、內容長度限制（防 OOM）、操作審計日誌
- API 參數：`make_memory_params()` → `betas: ["context-management-2025-06-27"]`
- Memory Tool 官方數據：84% token 節省（100 輪 web search 評估）

**L2 情節記憶（Episodic Memory）— `core/brain/graphiti_adapter.py`**
- 整合 Graphiti 開源時序知識圖譜（getzep/graphiti）
- 雙時態模型：`t_valid`/`t_invalid`——追蹤「什麼時候是真的」
- 知識衝突自動 `invalidate`（不刪除，保留歷史供推理）
- 混合檢索：語義 + BM25 + 圖遍歷，<100ms 查詢延遲
- 後端：FalkorDB（輕量）/ Neo4j / Kuzu（可選）
- 完整降級到現有 `TemporalGraph`（Graphiti 不可用時無縫切換）
- 便利工廠函數：`episode_from_phase()`/`episode_from_commit()`/`episode_from_adr()`

**L3 語義記憶（Semantic Memory）— Project Brain v2.0**
- 完全保留（向後相容）
- SQLite 知識圖譜 + Chroma 向量記憶
- 反事實推理、知識衰減模型、跨 Repo 聯邦
- `get_context()` 升級：L3 作為三層聚合的最後一層

**BrainRouter v3.0 — `core/brain/router.py`**
- 三層並行查詢（各層獨立 try/except，失敗不影響其他層）
- 智能寫入路由（根據知識類型決定目標層）
- `BrainQueryResult.to_context_string()`：按優先順序（L1>L2>L3）聚合，Token Budget 管理
- `learn_from_phase()` / `learn_from_commit()`：ship() 流水線自動學習鉤子
- `clear_working_memory()`：任務完成後清空 L1

**ProjectBrain 整合**
- `engine.py` 新增 `router` property（懶初始化）
- `get_context()` 升級：`_router` 已初始化時走三層聚合，否則降級到 v2.0
- 建構子新增 `graphiti_url` 參數（`bolt://localhost:7687`）

**brain/__init__.py 升級至 v3.0.0**

---

### 降級策略（Graceful Degradation）

| L1 Memory Tool | L2 Graphiti | 結果 |
|----------------|-------------|------|
| ✓ SDK 支援 | ✓ DB 可用 | 完整三層 |
| ✓ SDK 支援 | ✗ DB 不可用 | L1 + TemporalGraph + L3 |
| ✗ SDK 舊版 | ✗ DB 不可用 | L3 only（v2.0 模式） |

任一層失敗都不影響其他層，SYNTHEX 始終可用。

---

### 測試數：110（+25 個新測試）

新增 3 個測試群組：
- `TestBrainMemoryBackend`（8）：CRUD、FTS5 中英搜尋、路徑安全、長度限制
- `TestGraphitiAdapter`（7）：降級、Episode 工廠、TemporalSearchResult 語義
- `TestBrainRouter`（8）：三層查詢、寫入、狀態、版本確認

**全部 110 tests 通過（3.47s，無 warnings）**

## v0.13.0（第十三輪 — Project Brain v4.0，2026-03-27）

### Project Brain v4.0 — 六大功能

**1. Agent 自主知識驗證（`knowledge_validator.py`，648 行）**
- 三階段驗證：規則驗證（本地）→ 程式碼比對（本地）→ Claude 語義驗證（API）
- Prompt Injection 防護：知識內容清理後才送入 Claude
- 驗證快取（7 天 SQLite）：同一知識不重複 API 呼叫
- 成本控制：只對 confidence≥0.5 且 age≥30 天的 Decision/Rule/ADR 觸發 AI
- 結果只更新 confidence（不刪除，保留歷史可審計）
- `ValidationResult.conf_delta`、`to_summary_line()` 語義豐富的輸出

**2. 跨組織匿名知識共享（`federation.py`，455 行）**
- 三重差分隱私：語意泛化 + Laplace 機制（ε=1.0）+ K-匿名（K=3）
- PII 自動過濾：email、IP、API Key、URL 在上傳前清除
- 只分享 Pitfall/Rule（Decision 可能含公司策略）
- 本地佇列管理（SQLite）+ flush_queue() 同步
- 聯邦 Hub 以 mock 模擬（架構已就緒，等 v5.0 接入真實 Hub）
- `org_id` 由機器特徵 SHA-256 hash 生成（不可逆）

**3. 多層知識蒸餾（`knowledge_distiller.py`，489 行）**
- Layer 1 Context Distillation：壓縮為 SYNTHEX_KNOWLEDGE.md（任何 LLM 可讀）
- Layer 2 Role Prompts：為 7 個 SYNTHEX Agent 角色生成針對性 system prompt
  - `distill_for_agent("SHIELD")` 即時回傳安全知識 prompt 片段
- Layer 3 LoRA Dataset：生成 Alpaca instruction-following 格式 JSONL
  - 含訓練配置模板（Axolotl / Unsloth 兼容）
- PII 過濾確保訓練數據安全

**4. Graphiti 專屬 MCP Server（`graphiti_mcp_server.py`，458 行）**
- 4 個 MCP Tools：`graphiti_search` / `graphiti_add_episode` / `graphiti_adr` / `graphiti_status`
- `current_only=True` 自動過濾已過期知識（`valid_until != None`）
- Rate Limiting（60 RPM）、輸入嚴格驗證、錯誤訊息不洩漏路徑
- 支援 stdio 模式（Claude Code 直接呼叫）

**5. 知識圖譜視覺化 Web UI（`web_ui/server.py`，554 行）**
- Flask + D3.js 力導向圖（Force-directed Graph）
- 節點信心分數顏色渲染（綠→黃→橙→紅）
- 即時搜尋高亮（FTS5 + fallback LIKE）
- 按類型過濾、拖拽節點、縮放平移
- RESTful API：`/api/graph` / `/api/stats` / `/api/search` / `/api/decay`
- 只綁定 127.0.0.1（本地安全）

**6. L1 工作記憶跨 Session 持久化（`memory_tool.py` 擴充）**
- `persist_session_memories()`：pitfalls/decisions/context 跨 session 保留
- `restore_session_memories()`：下次 session 恢復上次的工作記憶
- `list_available_sessions()`：列出可恢復的歷史 session
- progress/notes 為 ephemeral（session 結束自動清空）
- 快照儲存在 `.brain/memory_sessions/{session_id}/snapshot.json`

**整合：`engine.py` 三個新屬性（懶初始化）**
- `brain.validator` → KnowledgeValidator
- `brain.federation` → KnowledgeFederation
- `brain.distiller` → KnowledgeDistiller

**`brain/__init__.py` 版本升級至 4.0.0**

**測試：110 → 139（+29 個新測試）**
- `TestKnowledgeValidator`（7）
- `TestKnowledgeFederation`（8）
- `TestKnowledgeDistiller`（6）
- `TestSessionPersistence`（4）
- `TestBrainV4Integration`（4）

**全部 139 tests 通過（4.58s）**

## v0.13.0（第十三輪 — Project Brain v4.0，2026-03-27）

### 六個 v4.0 功能全部實作完成

**1. KnowledgeValidator — Agent 自主知識驗證（648 行）**
- 三階段驗證：規則驗證（<1ms）→ 程式碼比對（<100ms）→ Claude 語義驗證（~2s）
- Prompt Injection 防護：過濾 ignore/forget/override 等指令
- 驗證快取（7 天 SQLite）：避免重複 API 呼叫，成本控制
- max_api_calls 強制上限（預設 20 次）
- dry_run 模式：只報告不更新
- `validation_log.db` 審計追蹤（run 歷史 + 詳細記錄）
- 整合：`ProjectBrain.validator` 懶初始化屬性

**2. KnowledgeFederation — 跨組織匿名知識共享（455 行）**
- 差分隱私（Differential Privacy）三重保護：
  - 語意泛化：CamelCase 組件名 → 通用描述
  - Laplace 雜訊（ε=1.0）：信心分數加 DP 雜訊
  - K-匿名：≥3 個組織提供才發布
- PII 自動過濾：email、IP、API Key、URL 拒絕上傳
- 匿名組織 ID（SHA-256 不可逆 hash）
- `federation.db` 本地審計（發布佇列 + 接收快取）
- `flush_queue()` 同步佇列；`receive_industry_knowledge()` 接收業界知識
- `apply_to_brain()` 將聯邦知識寫入 L3

**3. KnowledgeDistiller — 多模型知識蒸餾（489 行）**
- Layer 1 Context Distillation：壓縮為 `SYNTHEX_KNOWLEDGE.md`（任何 LLM 可讀）
- Layer 2 Role Prompts：為 7 個 Agent 角色生成針對性 system prompt 片段
- Layer 3 LoRA Dataset：生成 Alpaca 格式的 JSONL 訓練數據 + Axolotl 配置模板
- `distill_for_agent("SHIELD")` 即時版本（不需要事先執行 distill_all）
- PII 過濾確保訓練數據安全

**4. Graphiti MCP Server — L2 時序圖直接查詢（458 行）**
- 4 個 MCP Tools：graphiti_search / add_episode / adr / status
- `current_only=True` 過濾：只回傳 valid_until=None 的有效知識
- 支援 JSON-RPC stdio 協議（Claude Code 標準）
- Rate limiting 60 RPM，輸入嚴格驗證
- 整合到 Claude Code 的 `.claude/settings.json` MCP 設定

**5. Web UI — 知識圖譜視覺化（554 行）**
- Flask + D3.js 力導向圖（Force-directed Graph）
- 節點衰減熱力圖：信心分數 → 顏色（綠/黃/橙/紅）
- 節點類型形狀映射（Pitfall=triangle, Decision=diamond, ...）
- 即時搜尋（FTS5，300ms debounce）+ 圖上高亮
- 類型過濾按鈕（踩坑/規則/決策/ADR/組件）
- 節點詳情側邊欄（點擊顯示完整內容）
- 統計儀表板（健康分數、低信心計數）
- 只綁定 localhost（127.0.0.1），不對外暴露

**6. L1 跨 Session 持久化（新增到 memory_tool.py）**
- `persist_session_memories()` — 將重要記憶快照到 `.brain/memory_sessions/`
  - pitfalls / decisions / context → 跨 session 保留（30 天）
  - progress / notes → session 結束後清空（ephemeral）
- `restore_session_memories()` — 從快照恢復上次 session 的工作記憶
- `list_available_sessions()` — 列出所有可恢復的 session
- JSON 快照格式，帶過期時間戳

---

**測試：110 → 139（+29 個新測試）**

| 群組 | 數量 | 覆蓋範圍 |
|------|------|---------|
| TestKnowledgeValidator | 7 | 三階段驗證、Injection 偵測、dry_run |
| TestKnowledgeFederation | 8 | 匿名化、DP 雜訊、PII 過濾、分享/拒絕 |
| TestKnowledgeDistiller | 6 | 三層蒸餾、LoRA JSONL、角色 prompt |
| TestSessionPersistence | 4 | 持久化、恢復、列表、不存在 session |
| TestBrainV4Integration | 4 | 三個屬性懶初始化、版本號 v4.0.0 |

**全部 139 tests 通過（4.70s）**

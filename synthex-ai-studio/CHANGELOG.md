# SYNTHEX AI STUDIO — Changelog

## v0.11.0（2026-03-27）

## [System Audit]

### 🔍 系統崩潰風險與 API 規格落差盤點

聚焦於近期架構迭代後潛藏的確認性 Bug（不修就崩）、與 2026 官方 API 規格的競爭力差距，以及未來的技術佈局。此清單將作為下一階段緊急修補與底層重構的指導原則。

#### 優先排序矩陣

| 優先   | 類型       | 問題                                                          | 影響                                                                     |
| :----- | :--------- | :------------------------------------------------------------ | :----------------------------------------------------------------------- |
| **P0** | 確認性 Bug | `PhaseCheckpoint._save()` 非原子寫入 + `close()` 有 scope bug | 每次 `ship()` 中斷都可能損毀 `.ship_state.json`                          |
| **P0** | 確認性 Bug | `base_agent.run()` agentic loop 無 Context Compaction         | 長任務必 OOM（如 14.5h 任務時 messages 列表無限增長）                    |
| **P0** | 確認性 Bug | `evals/` 目錄不存在                                           | `evals.py` 淪為死程式碼，Golden Dataset 為零                             |
| **P0** | 確認性 Bug | 0 個 `async` 函數 — 全同步阻塞                                | Swarm 4 Worker 相互死等，單一 API hang 導致整個 Swarm 停頓               |
| **P1** | 規格缺口   | Tool Runner + 自動 Compaction 官方整合                        | 解決手工 agentic loop 在 `run()` 和 `swarm.py` 中邏輯重複且脆弱的問題    |
| **P1** | 規格缺口   | Memory Tool (官方) vs Project Brain (自製) 評估               | 官方方案支援任意後端，需與 900+ 行自製 SQLite 方案抉擇                   |
| **P1** | 規格缺口   | Context Management — 工具結果清除                             | 長流水線 `tool_result` 無限累積，需導入官方 token 觸發點自動清除機制     |
| **P1** | 規格缺口   | `web_orchestrator.py` 殘留 `print()` + 缺乏 E2E 測試          | `structlog` 整合不全；62 個單元測試皆孤立，無端對端覆蓋 12-Phase 流水線  |
| **P2** | 技術佈局   | Agent SDK 執行層遷移                                          | `claude_agent_sdk.query()` 取代手工 loop，內建 subagents 與 context 管理 |
| **P2** | 技術佈局   | MCP Elicitation (2026-03 最新)                                | MCP Server 可在任務中途請求結構化輸入（表單/瀏覽器 URL）                 |
| **P2** | 技術佈局   | Files API 整合                                                | 實現可重用文件上傳                                                       |
| **P2** | 技術佈局   | Batch API 評估                                                | 獲取 50% 折扣，適用於 evals 系統                                         |
| **P2** | 技術佈局   | Agent Skills (beta)                                           | 官方 SKILL.md 整合                                                       |

---

#### 📝 缺陷細節與重構方向

- **P0 — 確認性 bug（不修就崩）**
  - **檔案損毀風險：** `web_orchestrator.py` 中的 `PhaseCheckpoint._save()` 直接調用非原子的 `.write_text()`，且 `close()` 引用了 out-of-scope 的 requirement 變數引發 `NameError`。
  - **記憶體溢出 (OOM)：** 手工編寫的 `base_agent.run()` 缺乏 Context Compaction 機制。相較於官方 Tool Runner 能自動節省 58.6% token，SYNTHEX 在長任務下會因 messages 列表無上限增長而崩潰。
  - **評估系統失效：** `evals.py` 假設 `EVALS_DIR / suites/` 存在，但系統從未建立該目錄，導致 453 行程式碼無法執行。
  - **Swarm 執行緒死鎖：** 系統內 0 個 `async` 函數，導致 4 個 Worker thread 全同步阻塞在 API 呼叫上。一旦單一任務 hang 住，`ThreadPoolExecutor` 無法釋放 slot，將拖垮整個 Swarm。

- **P1 — 2026 API 規格缺口（競爭力直接差距）**
  - **手工 Agentic Loop 汰換：** 官方 SDK 的 `tool_runner` 已具備自動處理工具循環、錯誤傳回與 100K token 觸發的 Compaction，應考慮取代系統中脆弱的手工 while loop。
  - **架構選擇時刻：** 需評估是否將 900+ 行自製的 Project Brain (SQLite) 遷移至 Anthropic 官方的 client-side Memory Tool (`BetaAbstractMemoryTool`)。
  - **工具結果無限累積：** `web_orchestrator.py` 缺乏清除機制，需導入官方 `clear_tool_uses_20250919` 來自動清除舊工具結果，避免 Token 浪費。
  - **觀測性與測試缺口：** `web_orchestrator.py` 仍有 52 個 `print()` 待替換為 `structlog`，且現有 62 個 unit tests 皆為孤立測試，12-Phase 流水線零整合測試覆蓋。

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

## v0.10.0（2026-03-27）

### 🔍 系統升級遺留缺陷與前沿技術盤點

主要針對近期系統架構升級後，發現的整合不完整、舊程式碼殘留與 API 規格更新落差進行盤點。這份清單將作為接下來緊急修補 (Hotfix) 與次要版本更新的優先執行指標。

#### 優先排序矩陣

| 優先   | 問題                                              | 影響                                                 |
| :----- | :------------------------------------------------ | :--------------------------------------------------- |
| **P0** | `base_agent.py` 未整合 `config.py` — 兩套模型並存 | `config.py` 未完全發揮作用，定價與策略仍被寫死       |
| **P0** | 321 個 `print()` 未替換 `structlog`               | 日誌未結構化，開發與生產環境觀測性破損               |
| **P0** | `advanced_tool_use.py` beta headers 仍未移除      | GA 格式已改變，可能導致 API 呼叫格式錯誤             |
| **P0** | `computer_use.py` async/sync 邊界破損             | 文件標示與實作錯亂，引發併發執行風險                 |
| **P0** | `requirements.txt` 缺少三個核心依賴               | 安裝後靜默降級且無報錯，環境一致性失效               |
| **P1** | 1M context window GA — `config.py` 數值過時       | 上下文限制卡在舊版，無法發揮最新模型百萬 Tokens 潛力 |
| **P1** | Web Search GA + Dynamic Filtering 尚未整合        | `PROBE`/`TRACE` 錯失動態過濾功能，耗費不必要的 Token |
| **P1** | `brain/*` + `orchestrator.py` 仍硬編碼舊模型      | 核心引擎面臨舊版模型退役或定價失效風險               |
| **P1** | AgentSwarm 無部分失敗恢復機制                     | 單點失敗直接擊潰下游任務，Swarm 輸出殘缺             |
| **P2** | Claude Agent SDK 官方 loop 整合評估               | 系統底層架構前沿演進規劃                             |
| **P2** | Agent Skills (`skills-2025-10-02`)                | 提升 Agent 基礎能力的技術探索                        |
| **P2** | Test coverage 擴大 (`swarm`/`orch`)               | 測試涵蓋率提升，確保調度核心穩定                     |

---

#### 📝 缺陷細節與修補方向

- **P0 — 緊急修復（系統性缺陷）**
  - **兩套模型版本並存：** `base_agent.py` 未完全整合 `config.py`。目前僅使用了 `cfg.cache_control_block()`，但 `PRICING dict` 與 `MODEL_STRATEGY` 依然是硬編碼。
  - **日誌替換不完全：** `logging_setup.py` 已建立但未被廣泛引用，系統內仍殘留 321 個 `print()`（包含 `synthex.py` 113 個、`web_orchestrator.py` 52 個、`deploy_pipeline.py` 42 個、`base_agent.py` 27 個）。
  - **工具標頭未更新：** `advanced_tool_use.py` 中的 beta headers 尚未移除。Structured Outputs 已經 GA，格式應從原有的 beta 寫法更新為正式的 `output_config.format`。
  - **非同步邊界破損：** `computer_use.py` 出現 docstring 標示為非同步 (`async with ComputerUseSession()`)，但底層實作 `__enter__`/`__exit__` 卻是同步邏輯的嚴重錯亂。
  - **核心依賴遺漏：** `requirements.txt` 缺少了 `structlog`、`pydantic-settings` 與 `opentelemetry-sdk` 三個核心套件，導致新環境安裝後發生靜默降級。

- **P1 — 重要更新（2026 API 新規格 + 架構缺口）**
  - **上下文視窗數值過時：** 1M context window 已於 2026-03-13 針對 Opus 4.6 與 Sonnet 4.6 GA，不再需要 beta header 且無溢價。需將 `config.py` 中的 `CONTEXT_WINDOWS[SONNET_46]` 更新至 1,000,000。
  - **網頁搜尋新功能整合：** Web Search 已 GA 並支援 Dynamic Filtering（最新版 `web_search_20260209`）。`PROBE` 與 `TRACE` Agent 應盡速整合以透過 code execution 過濾結果，節省 Token。
  - **模組硬編碼殘留：** `config.py` 整合不徹底。`brain/engine.py:147`、`brain/extractor.py:60` 仍硬編碼 `claude-sonnet-4-5`；`orchestrator.py:92` 仍為 `claude-opus-4-5`。
  - **Swarm 容錯機制缺失：** `AgentSwarm` 缺乏部分失敗恢復能力。當 4 個 Worker 中有 2 個失敗時，依賴這些任務的下游節點無 fallback 或 retry 機制，會導致整個進程直接被 kill 掉。

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

**P1-2：brain/\* 和 orchestrator.py 完全整合 config.py**

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

## v0.9.0

- `core/config.py` 建立集中設定（ModelID, Tier, SynthexConfig）
- Haiku 3 → Haiku 4.5 遷移（退役日 2026-04-19）
- `core/logging_setup.py` + `TokenGuard` context window 保護
- `core/rate_limiter.py` Token Bucket 速率限制
- `core/observability.py` OpenTelemetry 整合
- `core/computer_use.py` Computer Use 基礎整合

## v0.8.0

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

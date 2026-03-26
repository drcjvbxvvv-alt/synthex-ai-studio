# SYNTHEX AI STUDIO — Changelog

## v0.10.0（第十輪，2026-03-27）

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

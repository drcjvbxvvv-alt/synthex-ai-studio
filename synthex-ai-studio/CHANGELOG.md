# SYNTHEX AI STUDIO — Changelog

> 28 個 AI Agent · 12-Phase 自動化開發流水線

## v0.0.0 — 2026-04-01

**初始獨立版本。** SYNTHEX AI STUDIO 從合體專案拆分為獨立專案，完全移除 Project Brain 依賴。

### 本版本確立的基礎

**核心架構**
- 28 個 AI Agent（7 個部門），基於 `BaseAgent v5`
- `CompactionManager`：長任務 context 壓縮（58.6% token 節省）
- `CircuitBreaker`：防止 Agent 級聯失敗（3 次連續失敗熔斷 60s）
- `TokenBudget`：精確成本追蹤（含 cache read/write）
- `AgentSwarm`：DAG 並行調度（Kahn 算法 + `asyncio.to_thread`）
  - 新增 `agentic_mode` 旗標：`chat()`（預設）或 `run()`（帶工具循環）

**模型管理**
- `ModelID` 常數集中在 `core/config.py`，無散落硬編碼字串
- `BETA_INTERLEAVED_THINKING` / `BETA_CONTEXT_MANAGEMENT` 常數化，GA 後一處改完
- 模型分層：Opus 4.6（複雜推理）/ Sonnet 4.6（開發工作）/ Haiku 4.5（高頻任務）
- Haiku 3 已退役（2026-04-19），全面遷移到 Haiku 4.5

**智慧路由**
- `Orchestrator` 複雜度感知路由（low/medium/high → Haiku/Sonnet/Opus）
- 路由決策本身改用 Sonnet 4.6（取代 Opus，效率更高）

**MCP Server**（`core/mcp_server.py`）
- 標準 JSON-RPC 2.0 over stdio
- 工具：`synthex_ask` / `synthex_agent` / `synthex_list_agents` / `synthex_ship`
- Claude Code、Cursor 等 MCP client 直接可接

**安全**
- `_safe_run()` argv 陣列執行（無 shell injection）
- 路徑遍歷防護、SSRF 過濾、原子寫入、PII 過濾
- SQL 參數化、Rate Limiting、Secret Scanning

**Evals 框架**
- Golden Dataset：4 套件，9 個測試案例
- `EvalRunner` + `EvalScorer` + SQLite 結果持久化

**測試：102/102 通過**

### 版本說明

v0.0.0 是獨立分拆後的起點版本。後續版本號（v0.1.0、v0.2.0...）按以下規則遞增：
- **patch**（v0.0.x）：Bug 修復、文件更新
- **minor**（v0.x.0）：新 Agent、新命令、功能擴充
- **major**（vX.0.0）：架構重構、重大 API 變更


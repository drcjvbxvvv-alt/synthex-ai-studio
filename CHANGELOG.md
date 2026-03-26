## [v2.3.0] - 2026-03-26

### ⚙️ 生產級基礎設施升級、可觀測性與 Computer Use 整合

本次更新專注於提升系統的生產環境穩定性與可維護性。全面汰除硬編碼模型版本、導入結構化日誌、強化 Token 與 Rate Limit 控制，並正式引入前沿的 Computer Use 能力以進行真實瀏覽器驗證。

#### 優先排序矩陣

| 優先   | 問題                                 | 影響                |
| :----- | :----------------------------------- | :------------------ |
| **P0** | 集中模型版本管理（`core/config.py`） | Haiku 3 退役        |
| **P0** | 全面替換 `print()` → `structlog`     | 可調試性            |
| **P0** | Config 驗證（`pydantic-settings`）   | 啟動 fail-fast      |
| **P0** | Context Window 溢出保護              | API 500 錯誤        |
| **P0** | Structured Output beta header → GA   | Vertex/Bedrock 相容 |
| **P1** | 1 小時 Prompt Cache TTL              | 成本 -40%           |
| **P1** | Client-side Rate Limiting            | 429 風暴防護        |
| **P1** | OpenTelemetry 觀測性整合             | 維運可見性          |
| **P2** | Computer Use 整合（BYTE/PROBE）      | 革命性能力          |
| **P2** | Opus 4.6 Agent Team 遷移評估         | 架構升級            |

#### 📝 修復與架構演進摘要

- **P0：生產環境緊急修復與防禦**
  - **集中模型版本管理：** 重構 19 處硬編碼模型字串，統一由 `core/config.py` (`ModelID.OPUS_46` 等) 管理，徹底移除即將退役的 Haiku 3。同時導入 `pydantic-settings` 進行環境變數的 fail-fast 驗證（如缺 API Key 立即退出）。
  - **結構化日誌導入：** 全面汰除 209 個 `print()`，改用 `structlog`。開發模式維持彩色輸出，生產模式則輸出帶有 timestamp/agent/phase/cost 標籤的 JSON 日誌，完美銜接 ELK/Datadog。
  - **Context Window 溢出保護 (`TokenGuard`)：** 針對超過安全輸入限制（Context Window 的 80%）的超長文件，在呼叫 API 前會自動進行「前 45% + 後 35%」的智慧截斷並加上標記，防止引發靜默的 API 500 錯誤。
  - **Prompt Cache TTL 延長：** 針對長達 30-60 分鐘的流水線，將快取存活時間升級為 1 小時，預估可進一步節省約 40% 的 Token 成本。
  - **GA Header 相容性修正：** 移除已 GA 的 Structured Output beta header，解決在 Vertex AI / Bedrock 環境下造成的 400 錯誤。

- **P1：系統強健性與可觀測性升級**
  - **客戶端速率限制 (`core/rate_limiter.py`)：** 實作 Thread-safe 的全域雙令牌桶（Request 與 Token 雙維度），依據官方限制的 70% 設定安全閥（Opus: 40 req/min, Sonnet: 200 req/min, Haiku: 350 req/min），防範 429 錯誤風暴。
  - **輕量級觀測性整合 (`core/observability.py`)：** 新增 `PhaseSpan` 與 `AgentSpan` context manager，自動記錄各階段的延遲、成本與成功率。零外部依賴設計，並能透過 `telemetry.format_report()` 產出易讀的效能報告。

- **P2：革命性前沿技術探索**
  - **Computer Use 真實瀏覽器驗證 (`core/computer_use.py`)：** 整合 `computer-use-2025-01-24` beta，實作 `ComputerUseSession`。具備 URL 白名單、操作上限（100次/session）與完整稽核日誌。PROBE Agent 現在可以直接在真實瀏覽器中點擊與驗證前端渲染結果，而不僅限於生成測試程式碼。

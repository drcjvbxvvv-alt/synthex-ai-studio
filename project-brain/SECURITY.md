# Project Brain — 安全設計與最佳實踐

> 本地優先的 AI 記憶系統。預設情況下，所有知識存在本地 SQLite，不強制上傳任何雲端服務。

---

## 設計原則

**最小權限**：`brain` 只操作 `--workdir` 內的 `.brain/` 目錄，不存取系統其他位置。

**輸入驗證**：所有 CLI 參數通過 argparse 驗證；KnowledgeValidator 對知識內容進行三階段驗證（規則 → 程式碼引用 → LLM 語意），並過濾 Prompt Injection 嘗試。

**API 認證**：`brain serve` 支援 `BRAIN_API_KEY` 環境變數啟用 Bearer token 認證。

**本地優先**：所有知識存在 `.brain/brain.db`（單一 SQLite 文件），備份 = 複製一個文件。

---

## 資料存儲

v10.0 起所有資料統一在單一文件：

```
.brain/brain.db          主記憶庫（SQLite WAL 模式）
├── nodes                L3 語意記憶
├── edges                因果關係
├── episodes             L2 情節記憶（git commits）
├── sessions             L1a 工作記憶
└── events               事件記錄

.brain/review_board.db   KRB 暫存區（自動提取候選知識）
```

**備份建議**：定期複製整個 `.brain/` 目錄，或僅複製 `brain.db`。

---

## LLM 資料流

`brain scan` 和 `brain sync` 會把程式碼 diff 送到 LLM 分析。

**使用 Anthropic API 時**：Diff 內容傳送到 Anthropic 伺服器，遵循 Anthropic 資料使用政策。

**需要完全本地（零資料外傳）**：

```bash
export BRAIN_LLM_PROVIDER=openai
export BRAIN_LLM_BASE_URL=http://localhost:11434/v1
export BRAIN_LLM_MODEL=llama3.2:3b
# 所有 LLM 呼叫走本地 Ollama，資料不離開本機
```

---

## API 安全（brain serve）

### 啟用認證

```bash
export BRAIN_API_KEY=your-secret-key
brain serve --port 7891
```

啟用後所有 API 請求需要：

```
Authorization: Bearer your-secret-key
```

`/health` 端點不需要認證。

### 生產部署建議

```bash
# 綁定本地迴環（內部工具，不暴露到網路）
brain serve --host 127.0.0.1 --port 7891

# 或透過 nginx 反向代理加 TLS
```

---

## MCP Server 安全（brain serve --mcp）

MCP Server 暴露給 Claude Code / Cursor 等工具時：

- `--workdir` 限制操作範圍，工具只能讀寫指定目錄的 `.brain/`
- 不允許路徑遍歷（`../` 攻擊）
- KnowledgeValidator 的 Prompt Injection 過濾對 `add_knowledge` MCP 工具同樣生效

```bash
# 限制在特定專案目錄
brain serve --mcp --workdir /your/specific/project
```

---

## 錯誤訊息安全（v0.2.0）

API 錯誤回應不洩漏內部實作細節：

- 所有 `str(e)` 原始 SQL 異常已改為中文友善訊息（U-1）
- 後端完整錯誤仍記錄至 `logger.error()`，便於除錯
- MCP Rate limit 觸發時回傳 `[rate_limited] ... — 請稍後再試` 而非空字串（U-2）
- `BRAIN_RATE_LIMIT_RPM` 環境變數控制每分鐘呼叫上限（預設 60）

---

## 已知限制（v0.2.0）

企業安全功能目前不在優先範圍，個人開發者與小型團隊場景不需要：

| 功能 | 狀態 | 替代方案 |
|------|------|---------|
| 靜態加密（SQLCipher）| 未實作 | 使用作業系統磁碟加密 |
| 稽核日誌 | 未實作 | `events` 表有部分記錄 |
| RBAC 角色存取控制 | 未實作 | 透過 `BRAIN_API_KEY` 單一 token 認證 |
| TLS 自動配置 | 未實作 | 使用 nginx / Caddy 反向代理 |

---

## 回報安全問題

發現安全漏洞請透過 GitHub Issue 私訊回報，勿直接公開。

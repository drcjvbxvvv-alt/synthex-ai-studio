# Project Brain — 命令參考

> 已安裝全局指令：`brain <command>`
> `brain` 自動從當前目錄往上找 `.brain/`，無需 `--workdir`

## 命令總覽

| 命令 | 說明 | 例子 |
|------|------|------|
| `brain setup` | 一鍵初始化（建 db + git hook + MCP）| `brain setup` |
| `brain add` | 加入知識 | `brain add "JWT 必須用 RS256"` |
| `brain ask` | 查詢知識 | `brain ask "JWT 設定"` |
| `brain status` | 記憶庫狀態 | `brain status` |
| `brain sync` | 從最新 commit 自動學習 | `brain sync --quiet` |
| `brain scan` | 掃描 git 歷史提取知識 | `brain scan --all` |
| `brain review` | 審查 KRB 暫存區知識 | `brain review list` |
| `brain serve` | REST API / MCP Server | `brain serve --mcp` |
| `brain webui` | D3.js 瀏覽器視覺化 | `brain webui --port 7890` |
| `brain context` | 查詢（技術名，同 ask）| `brain context "JWT"` |
| `brain index` | 重建 FTS5 / 向量索引 | `brain index` |
| `brain init` | 低階初始化 | （一般用 setup 即可）|
| `brain meta` | 後設知識管理 | `brain meta --list` |

---

## brain add 詳細說明

```bash
# 快速模式（位置參數）
brain add "JWT 必須使用 RS256"

# 完整模式
brain add "JWT 規則" \
  --kind Rule \
  --scope auth \
  --confidence 0.9 \
  --content "RS256 是非對稱加密，可跨服務安全共享公鑰"
```

**kind 類型**：`Note`（預設）/ `Rule` / `Pitfall` / `Decision` / `ADR` / `Component`

**scope 範例**：`auth` / `payment_service` / `user_profile` / `global`（預設）

---

## brain review 詳細說明

`brain scan` 提取的知識先進 KRB Staging 暫存區，需人工審核才進入 L3：

```bash
# 列出待審清單
brain review list

# 核准（進入 L3）
brain review approve <node_id>

# 駁回（附上原因）
brain review reject <node_id> --reason "資訊不正確"
```

---

## brain scan 詳細說明

```bash
# 掃描最近 100 筆 commit（預設）
brain scan

# 掃描全部歷史
brain scan --all

# 指定數量
brain scan --limit 50
```

提取的知識進入 KRB 暫存區，用 `brain review list` 審查。

---

## brain ask 輸出說明

```
🧠 相關知識注入
─────────────────
⛓ 因果關係（Brain 預先推導）
  🛡 [JWT RS256] PREVENTS [Token 過期漏洞]

### ⚠ 已知踩坑：Token 過期未驗證
JWT exp 欄位必須驗證...

### 📌 業務規則：JWT RS256
必須使用 RS256 非對稱加密...
```

---

## 環境變數

| 變數 | 預設 | 說明 |
|------|------|------|
| `BRAIN_WORKDIR` | 當前目錄 | 省略 --workdir |
| `ANTHROPIC_API_KEY` | — | AI 功能（scan / 知識提取）|
| `BRAIN_SYNTHESIZE` | `0` | `1` = 記憶融合模式（opt-in）|
| `BRAIN_LLM_PROVIDER` | `anthropic` | `openai` = Ollama 本地 LLM |
| `BRAIN_LLM_BASE_URL` | `http://localhost:11434/v1` | 本地 LLM 端點 |
| `BRAIN_LLM_MODEL` | `claude-haiku-4-5-20251001` | 模型名稱 |
| `BRAIN_API_KEY` | — | `brain serve` API 認證 |

---

## 已移除命令

`learn`, `distill`, `validate`, `export-rules`, `daemon` 等已在 v10.x 清理。

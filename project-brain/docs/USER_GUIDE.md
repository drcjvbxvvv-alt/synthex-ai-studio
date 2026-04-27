# Project Brain — 使用者指南

> **版本**：v0.46.0
> **適用對象**：所有團隊成員（工程師、PM、設計師、管理者）
> **最後更新**：2026-04-27

---

## 目錄

1. [Project Brain 是什麼？](#1-project-brain-是什麼)
2. [核心概念](#2-核心概念)
3. [安裝與初始化](#3-安裝與初始化)
4. [加入知識](#4-加入知識)
5. [查詢知識](#5-查詢知識)
6. [知識審查（KRB）](#6-知識審查krb)
7. [自動學習](#7-自動學習)
8. [與 AI 助手整合](#8-與-ai-助手整合)
9. [團隊共用模式](#9-團隊共用模式)（含 AI Agent 自主託管、餵入文件）
10. [知識庫管理](#10-知識庫管理)
11. [視覺化界面（WebUI）](#11-視覺化界面webui)
12. [匯出與匯入](#12-匯出與匯入)
13. [常用命令速查表](#13-常用命令速查表)
14. [設定參考](#14-設定參考)
15. [常見問題（FAQ）](#15-常見問題faq)

---

## 1. Project Brain 是什麼？

Project Brain 是一個**團隊知識庫**，專門記住你們專案中重要的事：

- 架構決策（為什麼選 PostgreSQL？）
- 踩過的坑（mock 測試通過但 production 爆了）
- 必須遵守的規則（JWT 必須用 RS256）
- 重要筆記（部署流程、API 規格）

它跟一般 Wiki 的差別是：

| | Wiki / Notion | Project Brain |
|--|--|--|
| 誰維護 | 人手動寫 | AI 自動提取 + 人審查 |
| 會過時嗎 | 容易過時 | 自動衰減，舊知識降低可信度 |
| 怎麼找 | 手動搜尋 | AI 主動注入相關知識 |
| 誰能用 | 看文件的人 | AI 助手自動使用 |

**簡單說**：讓 AI 助手記住你們團隊的經驗，下次誰遇到相同問題，AI 會主動提醒。

---

## 2. 核心概念

### 2.1 知識類型

每條知識都有一個「類型」，幫助分類和搜尋：

| 類型 | 什麼時候用 | 範例 |
|------|-----------|------|
| **Rule** | 必須遵守的規則 | 「JWT 必須使用 RS256 簽名」 |
| **Decision** | 做了什麼選擇，為什麼 | 「選用 PostgreSQL，因為需要 ACID 保證」 |
| **Pitfall** | 踩過的坑、要避免的錯誤 | 「mock 測試通過但 production migration 失敗」 |
| **ADR** | 正式的架構決策記錄 | 「ADR-001: 採用 Clean Architecture」 |
| **Note** | 一般筆記 | 「部署到 staging 需要 VPN」 |

**怎麼選？**
- 如果是「一定要這樣做」→ **Rule**
- 如果是「我們選了 A 而不是 B」→ **Decision**
- 如果是「以前出過錯」→ **Pitfall**
- 不確定？用 **Note**，之後再改

### 2.2 信心度

每條知識都有一個 0~100% 的信心度：

| 信心度 | 意義 | 來源 |
|--------|------|------|
| 90%+ | 已驗證的事實 | 人工確認 |
| 70-90% | 合理推斷 | AI 提取 + 人審查 |
| 50-70% | 可能正確 | AI 自動提取 |
| <50% | 需要確認 | 過時或有爭議 |

信心度會隨時間**自動衰減**——如果一條知識長時間沒人引用或確認，它的信心度會慢慢降低，避免 AI 給出過時建議。

### 2.3 三層記憶

```
┌─────────────────────────────────────────┐
│  L1 — 工作記憶                           │
│  目前正在做的任務上下文                     │
│  任務結束後自動清除                        │
├─────────────────────────────────────────┤
│  L2 — 情節記憶                           │
│  git commit 歷史、任務完成記錄             │
│  隨時間自動老化                           │
├─────────────────────────────────────────┤
│  L3 — 長期記憶（知識庫）                   │
│  Rule / Decision / Pitfall / ADR / Note  │
│  可搜尋、可衰減、可審查                    │
└─────────────────────────────────────────┘
```

你加入的知識存在 **L3 長期記憶**，是最重要的一層。

---

## 3. 安裝與初始化

### 3.1 安裝

```bash
# 基本安裝
pip install project-brain

# 推薦安裝（含 AI 助手整合）
pip install "project-brain[mcp]"
```

### 3.2 初始化專案

```bash
# 進入你的專案目錄
cd /path/to/your/project

# 一鍵初始化
brain setup
```

這會自動完成：
1. 建立 `.brain/brain.db`（知識庫檔案）
2. 安裝 git post-commit hook（每次 commit 自動學習）
3. 偵測 AI 助手並設定連接

### 3.3 確認安裝成功

```bash
brain health
```

如果看到全部 `[OK]`，就可以開始使用了。

---

## 4. 加入知識

### 4.1 快速加入

```bash
# 最簡單的方式——一行搞定
brain add "JWT 必須使用 RS256 簽名"
```

預設類型是 Note，信心度 80%。

### 4.2 指定類型和詳細內容

```bash
# 加入一條規則
brain add "JWT 必須使用 RS256" \
  --kind Rule \
  --confidence 0.9 \
  --content "多服務環境需使用非對稱加密，HS256 只適合單一服務"

# 記錄一個架構決策
brain add "選用 PostgreSQL 而非 MySQL" \
  --kind Decision \
  --content "需要 ACID 保證，且團隊已有 PostgreSQL 經驗"

# 記錄一個踩過的坑
brain add "mock 測試通過但 production migration 失敗" \
  --kind Pitfall \
  --content "本地 mock 的 schema 與真實 DB 不一致，應該用 integration test"
```

### 4.3 指定作用域

如果知識只跟某個模組有關：

```bash
brain add "付款 API 必須驗證 HMAC 簽名" \
  --kind Rule \
  --scope payment_service
```

常用 scope：`auth` / `payment` / `user` / `deploy` / `global`（預設）

### 4.4 什麼值得加入？

**值得記錄的**：
- 團隊會議決定的事（選什麼技術、為什麼）
- 出過的事故和解決方法
- 必須遵守的規範（安全、程式碼風格）
- 踩過的坑（尤其是花了很多時間才解決的）

**不需要記錄的**：
- 程式碼裡已經寫清楚的事（看程式碼就知道）
- 暫時性的事（這個 bug 明天就修）
- 個人備忘（用自己的筆記工具）

---

## 5. 查詢知識

### 5.1 自然語言查詢

```bash
# 用自然語言問問題
brain ask "我們的 JWT 設定是什麼？"
brain ask "付款模組要注意什麼？"
brain ask "上次 Redis 出了什麼問題？"
```

Brain 會搜尋知識庫，回傳最相關的知識。

### 5.2 關鍵字搜尋

```bash
# 純關鍵字搜尋
brain search "PostgreSQL 連線池"
```

### 5.3 任務 Context 查詢

```bash
# 開始一個任務前，先看有什麼該注意的
brain context "我要修改付款流程"
```

這會回傳所有跟「付款流程」相關的 Rule、Pitfall、Decision，幫你避免踩坑。

### 5.4 查看知識庫狀態

```bash
# 知識庫概覽
brain status

# 詳細健康診斷
brain health
```

---

## 6. 知識審查（KRB）

KRB（Knowledge Review Board）是一個**品質控制機制**。AI 自動提取的知識不會直接進入知識庫，而是先進入「暫存區」等待人工審查。

### 6.1 為什麼需要審查？

AI 自動提取的知識可能：
- 不夠準確
- 太瑣碎（不值得長期記住）
- 需要修改措辭

審查確保知識庫的品質。

### 6.2 查看待審知識

```bash
brain review list
```

這會列出所有等待審查的知識，包含：
- 標題和內容
- 來源（哪次 commit 提取的）
- AI 給的信心度

### 6.3 核准或駁回

```bash
# 核准（進入長期記憶）
brain review approve <id>

# 駁回（不進入知識庫）
brain review reject <id> --reason "資訊不正確"
```

### 6.4 審查建議

- **信心度 > 80%**：通常可以直接核准
- **信心度 50-80%**：看一下內容，確認正確再核准
- **信心度 < 50%**：仔細評估，可能需要修改或駁回

---

## 7. 自動學習

### 7.1 Git Commit 自動學習

每次 `git commit` 後，Brain 會自動：

```
git commit
    ↓
post-commit hook 觸發
    ↓
分析 commit diff
    ↓
AI 判斷是否值得記住
    ↓
值得 → 進入 KRB 暫存區等待審查
不值得 → 跳過
```

你不需要做任何事——commit 就好，Brain 會自動學習。

### 7.2 手動觸發學習

```bash
# 從最新 commit 學習
brain sync

# 掃描所有 git 歷史（首次設定時有用）
brain scan --all

# 只掃描最近 10 筆 commit
brain scan --limit 10
```

### 7.3 Pipeline 統計

```bash
# 查看自動學習的統計
brain pipeline-stats

# JSON 格式
brain pipeline-stats --json
```

---

## 8. 與 AI 助手整合

### 8.1 Claude Code（自動整合）

如果你用 Claude Code，`brain setup` 會自動設定。之後：

- **開始任務時**：Claude Code 自動呼叫 `get_context`，把相關知識注入對話
- **完成任務時**：Claude Code 自動呼叫 `complete_task`，記錄學到的東西
- **你不需要做任何事**——整合是透明的

### 8.2 其他 AI Agent（透過 MCP）

任何支援 MCP 協定的 AI Agent 都可以連接 Brain：

```json
{
  "mcpServers": {
    "project-brain": {
      "command": "python",
      "args": ["-m", "project_brain.mcp_server", "--workdir", "/path/to/project"]
    }
  }
}
```

### 8.3 AI Agent 可用的 MCP Tools

AI Agent 連接後可使用以下工具：

| 工具 | 用途 | 使用頻率 |
|------|------|---------|
| `get_context` | 取得任務相關知識 | 每次開始任務 |
| `search_knowledge` | 搜尋知識庫 | 需要查資料時 |
| `add_knowledge` | 加入新知識 | 發現值得記住的事 |
| `batch_add_knowledge` | 批次加入（最多 50 條） | 上傳文件後提取 |
| `complete_task` | 記錄任務完成 + 學到的東西 | 每次完成任務 |
| `brain_status` | 知識庫統計 | 查看狀態 |
| `report_knowledge_outcome` | 回饋知識是否有用 | 知識幫到你時 |
| `krb_pre_screen` | 列出待審知識 | 審查時 |
| `impact_analysis` | 分析元件影響範圍 | 改動前評估 |
| `mark_helpful` | 標記知識有用/無用 | 隨時 |

---

## 9. 團隊共用模式

### 9.1 透過 Telegram + AI Agent

最快讓全團隊共享知識庫的方式：

```
公司機器上：
  1. brain setup              ← 初始化知識庫
  2. AI Agent 連接 Brain MCP  ← 設定 MCP Server
  3. AI Agent 綁定 Telegram   ← 所有人都能用
```

之後，同事可以在 Telegram 上：
- 上傳文件 → AI Agent 提取知識 → 自動寫入 Brain
- 問問題 → AI Agent 查詢 Brain → 回覆知識
- 審查知識 → AI Agent 呼叫 Brain → 核准/駁回

### 9.2 透過 HTTP MCP Server（直連）

如果網路環境允許，可以啟動 HTTP MCP Server 讓其他 AI Agent 直連：

```bash
# 啟動 HTTP MCP Server
brain serve --mcp --auth-key $BRAIN_API_KEY --port 3000

# 綁定所有網路介面（讓其他機器連入）
brain serve --mcp --auth-key $BRAIN_API_KEY --bind 0.0.0.0 --port 3000
```

其他機器的 AI Agent 設定：
```json
{
  "mcpServers": {
    "company-brain": {
      "url": "http://brain-server:3000/mcp",
      "headers": {
        "Authorization": "Bearer your-api-key"
      }
    }
  }
}
```

### 9.3 知識來源追蹤

多人共用時，每條知識會記錄「誰加的」：

```bash
# 加入知識時標記來源
brain add "JWT 規則" --kind Rule
# → source: "cli:your-username"

# AI Agent 加入時
add_knowledge(title="JWT 規則", source="telegram:@alice")
# → source: "telegram:@alice"

# 按來源搜尋
# AI Agent 可用 search_knowledge(query="JWT", author="telegram:@alice")
```

### 9.4 讓 AI Agent 自主安裝與託管

如果你的 AI Agent（例如小龍蝦 / OpenClaw）有 Shell 存取權限，可以讓它自己安裝 Brain 並全權託管知識庫，你完全不需要手動操作。

**只需告訴你的 AI Agent：**

> 「安裝 Project Brain 並託管知識庫」

AI Agent 會自主執行：

```
1. pip install "project-brain[mcp]"       ← 安裝
2. cd /path/to/project && brain setup     ← 初始化
3. 設定 MCP 連接                           ← 接上知識庫
4. brain health                           ← 確認正常
5. 回報：「Brain 已安裝，準備就緒」         ← 通知你
```

之後 AI Agent 可以自主處理所有日常運營：

| 操作 | AI Agent 怎麼做 | 頻率 |
|------|-----------------|------|
| 同事上傳文件 | 讀文件 → 提取知識 → `add_knowledge` | 有人上傳時 |
| 同事問問題 | `get_context` / `search_knowledge` → 回覆 | 隨時 |
| 知識品質審查 | `krb_pre_screen` → approve / reject | 定期 |
| 健康監控 | `brain health` → 異常時通知群組 | 每天 |
| 資料庫維護 | Shell 執行 `brain optimize` | 每週 |
| 統計報告 | `brain_status` → 回報群組 | 每天/每週 |

### 9.5 AI Agent 託管的建議 System Prompt

在你的 AI Agent 的 System Prompt 中加入以下指引，讓它知道怎麼管理 Brain：

```markdown
## Brain 知識庫託管

你負責管理 Project Brain 知識庫。

### 安裝（首次）
如果 Brain 未安裝，執行：
  pip install "project-brain[mcp]"
  cd /company/project && brain setup

### 日常運營
- 同事上傳文件 → 讀取內容 → 提取知識點 → 呼叫 add_knowledge
- 同事問問題 → 呼叫 get_context → 根據知識庫回答
- 每天執行一次 brain health，異常時通知群組
- 每週執行一次 brain optimize

### 知識品質控制
- add_knowledge 時設定 confidence=0.85（來自文件的知識）
- source 欄位填入 "telegram:@用戶名"（追蹤來源）
- 知識類型分類：
  - Rule：必須遵守的規則
  - Decision：架構或技術決策
  - Pitfall：踩過的坑、要避免的錯誤
  - Note：一般筆記

### 知識提取原則
- 從文件中只提取值得長期記住的知識，不要什麼都加
- 每條知識一個重點，不要把整段文件塞進一條
- 如果文件沒有值得記錄的知識，直接告訴用戶
```

### 9.6 餵入文件的三種方式

#### 方式 1：透過 AI Agent（最推薦）

直接在 Telegram 或對話中告訴 AI Agent：

> 「請讀取這份文件，提取重要的知識加入 Brain」

AI Agent 會自動讀取文件、提取 Rule / Decision / Pitfall，然後呼叫 `add_knowledge` 寫入。

#### 方式 2：CLI 手動加入

```bash
brain add "JWT 必須使用 RS256 簽名" --kind Rule --confidence 0.9
brain add "選用 PostgreSQL 因為需要 ACID" --kind Decision
```

精確但需要逐條操作。

#### 方式 3：Git Commit 自動學習

```bash
git add docs/new-spec.md
git commit -m "docs: add API specification"
# → Brain 的 post-commit hook 自動分析 diff
# → 值得記住的部分進入 KRB 暫存區等待審查
```

適合程式碼和文件的變更，但只分析 diff（不是整份文件）。

---

## 10. 知識庫管理

### 10.1 資料庫維護

```bash
# 資料庫最佳化（清理碎片、重建索引）
brain optimize

# 清除 session 工作記憶（不影響長期記憶）
brain clear
```

### 10.2 知識驗證

```bash
# 三階段驗證：檢查知識庫品質
brain validate

# CI 模式（跳過需要 AI 的檢查）
brain validate --ci
```

驗證會檢查：
- 結構規則（信心度範圍、必要欄位）
- 內容品質（Pitfall 必須有詳細內容）
- 語意一致性（AI 檢查矛盾知識）

### 10.3 環境診斷

```bash
# 完整環境診斷 + 自動修復
brain doctor --fix

# 查看所有設定來源
brain config
```

---

## 11. 視覺化界面（WebUI）

```bash
# 啟動瀏覽器視覺化界面
brain webui --port 7890
# 開啟 http://localhost:7890
```

WebUI 提供：
- **知識圖譜視覺化**：D3.js 力導向圖，看到知識之間的關係
- **行內編輯**：直接在瀏覽器修改知識的標題、內容、類型、信心度
- **KRB 管理面板**：在瀏覽器審查和核准知識
- **全文搜尋**：即時搜尋 + 類型過濾

---

## 12. 匯出與匯入

### 12.1 匯出知識庫

```bash
# 匯出為 JSON
brain export --format json > knowledge.json

# 匯出為 Markdown
brain export --format markdown > knowledge.md
```

### 12.2 匯入知識庫

```bash
# 從 JSON 匯入
brain import knowledge.json
```

### 12.3 跨專案同步（Federation）

```bash
# 從 A 專案匯出
cd /project-a
brain fed export --output /tmp/bundle.json

# 匯入到 B 專案（進入 KRB 等待審查）
cd /project-b
brain fed import /tmp/bundle.json
```

匯出會自動清理 PII（email、IP、token）。

---

## 13. 常用命令速查表

### 日常使用

| 做什麼 | 命令 |
|--------|------|
| 加入知識 | `brain add "標題" --kind Rule` |
| 查詢知識 | `brain ask "問題"` |
| 搜尋知識 | `brain search "關鍵字"` |
| 查看狀態 | `brain status` |
| 審查知識 | `brain review list` |
| 核准知識 | `brain review approve <id>` |
| 駁回知識 | `brain review reject <id>` |

### 管理維護

| 做什麼 | 命令 |
|--------|------|
| 健康診斷 | `brain health` |
| 環境診斷 | `brain doctor --fix` |
| 資料庫最佳化 | `brain optimize` |
| 知識驗證 | `brain validate` |
| 查看設定 | `brain config` |
| Pipeline 統計 | `brain pipeline-stats` |

### 進階操作

| 做什麼 | 命令 |
|--------|------|
| 掃描 git 歷史 | `brain scan --all` |
| 手動同步最新 commit | `brain sync` |
| 啟動 WebUI | `brain webui --port 7890` |
| 啟動 MCP Server | `brain serve --mcp` |
| 啟動 HTTP MCP | `brain serve --mcp --auth-key $KEY` |
| 匯出知識庫 | `brain export --format json` |
| 匯入知識庫 | `brain import data.json` |
| 清除工作記憶 | `brain clear` |

---

## 14. 設定參考

### 14.1 環境變數

| 變數 | 預設 | 說明 |
|------|------|------|
| `BRAIN_WORKDIR` | 當前目錄 | 專案目錄（省略 --workdir） |
| `ANTHROPIC_API_KEY` | — | Claude API key（AI 功能需要） |
| `BRAIN_API_KEY` | — | HTTP MCP Server 認證 key |
| `BRAIN_LLM_PROVIDER` | `anthropic` | LLM 提供者（`openai` = 本地 Ollama） |
| `BRAIN_LLM_MODEL` | `claude-haiku-4-5` | 使用的 AI 模型 |
| `BRAIN_RATE_LIMIT_RPM` | `60` | MCP 每分鐘最大呼叫次數 |
| `BRAIN_EMBED_PROVIDER` | 自動偵測 | 向量搜尋（`none` = 只用全文搜尋） |

### 14.2 brain.toml 設定檔

Brain 的進階設定在 `.brain/brain.toml`（可選，不建立也能正常運作）：

```toml
[brain]
max_context_tokens = 6000     # Context 注入的最大 token 數
freshness_warn_days = 30      # 知識超過幾天開始警告
dedup_threshold = 0.85        # 語意去重閾值

[pipeline]
enabled = true                # 自動知識提取開關
worker_interval_seconds = 60  # Pipeline 執行間隔

[decay]
enabled = true                # 知識衰減開關
run_interval_hours = 24       # 衰減計算間隔

[review]
auto_approve_threshold = 0.80 # 高信心知識自動核准閾值
staging_ttl_days = 30         # 待審知識過期天數
```

---

## 15. 常見問題（FAQ）

### Q: Brain 會影響我的程式碼嗎？

不會。Brain 的資料全部存在 `.brain/` 目錄下，不會修改你的程式碼。你可以把 `.brain/` 加入 `.gitignore`（個人使用）或提交到 git（團隊共享設定）。

### Q: 知識庫會越來越大嗎？

會成長，但有自動管理機制：
- **知識衰減**：不再引用的知識信心度自動降低
- **KRB 清理**：過期未審的知識自動歸檔
- **資料庫最佳化**：`brain optimize` 清理碎片

一般專案（幾千條知識）的 brain.db 不超過 100MB。

### Q: 沒有 AI API key 能用嗎？

可以。沒有 API key 時：
- ✅ 手動加入/搜尋/查詢知識（完全可用）
- ✅ 全文搜尋（FTS5，不需要 AI）
- ❌ 自動知識提取（需要 LLM）
- ❌ 語意搜尋向量模式（需要 embedding model）
- ❌ 知識驗證的 LLM 階段

### Q: 支援什麼語言？

繁體中文、簡體中文、英文都支援。全文搜尋使用 Unicode 分詞，可以正確搜尋中文。

### Q: 怎麼備份知識庫？

```bash
# 方法 1：直接複製 DB 檔案
cp .brain/brain.db .brain/brain.db.bak

# 方法 2：匯出為 JSON
brain export --format json > backup.json
```

### Q: 知識加錯了怎麼辦？

在 WebUI 中可以直接編輯或刪除：
```bash
brain webui
# 在瀏覽器中找到該知識，點編輯或刪除
```

### Q: 多人同時使用會衝突嗎？

不會。Brain 使用 SQLite WAL 模式，支援多人同時讀取和寫入。寫入操作會自動序列化，不會丟失資料。

### Q: 怎麼知道 AI 有沒有用到我的知識？

```bash
# 查看知識庫統計，包含被引用次數
brain status

# 在 AI 回覆中通常會看到「根據知識庫...」的提示
```

---

## 附錄：完整知識生命週期

```
            ┌─── 人工加入 ───┐
            │  brain add     │
            │  Telegram 上傳  │
            │  WebUI 編輯     │
            └───────┬────────┘
                    │
                    ▼
  ┌──── AI 自動提取 ────┐
  │  git commit hook    │
  │  brain scan         │
  │  Agent complete_task│
  └─────────┬───────────┘
            │
            ▼
     ┌──────────────┐         ┌──────────────┐
     │ KRB 暫存區    │────────▶│ 人工審查      │
     │（等待審查）    │         │ approve/reject│
     └──────────────┘         └──────┬───────┘
                                     │
                              核准 ──┘
                                     │
                                     ▼
                              ┌──────────────┐
                              │ L3 長期記憶    │
                              │ 知識庫正式收錄  │
                              └──────┬───────┘
                                     │
                          ┌──────────┼──────────┐
                          │          │          │
                     被 AI 引用   信心衰減     被搜尋
                     ↑ 信心提升   ↓ 信心降低   ↑ 信心維持
                          │          │          │
                          └──────────┴──────────┘
                                     │
                              信心 < 閾值
                                     │
                                     ▼
                              ┌──────────────┐
                              │  自動歸檔      │
                              │  不再主動推薦   │
                              └──────────────┘
```

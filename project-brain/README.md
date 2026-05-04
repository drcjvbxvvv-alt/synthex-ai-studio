# Project Brain — AI 記憶系統

> 為 AI Agent 設計的工程記憶基礎設施。
> 讓你的 AI 助手記住團隊的架構決策、踩過的坑、和專案規則。

---

## 什麼是 Project Brain？

Project Brain 是一個**持久化知識庫**，可以與任何 AI Agent 整合：

- **自動學習**：每次 `git commit` 後自動提取值得記住的知識
- **智慧注入**：開始任務前自動把相關知識注入 AI Context
- **知識衰減**：舊的、不再引用的知識自動降低信心，不讓 AI 說出過時建議
- **審查機制**：AI 提取的知識進入暫存區（KRB），人工確認後才進入長期記憶
- **團隊共享**：多位同事透過同一個知識庫，所有人的經驗即時共享

### 誰適合使用？

| 角色 | 怎麼用 |
|------|--------|
| 工程師 | CLI + Claude Code 自動整合，commit 後自動學習 |
| PM / 管理者 | 透過 Telegram 或 WebUI 查詢和加入知識 |
| 新進同事 | 查詢知識庫，快速了解專案慣例和踩過的坑 |
| AI Agent | 透過 MCP 協定連接，18 個工具可用 |

---

## 架構總覽

### 三層記憶

```
┌──────────────────────────────────────────────────────────┐
│  L1 — 工作記憶                                            │
│  當前任務上下文，任務結束後清除                              │
├──────────────────────────────────────────────────────────┤
│  L2 — 情節記憶                                            │
│  git commit 歷史、任務完成記錄，自動老化                     │
├──────────────────────────────────────────────────────────┤
│  L3 — 長期記憶（知識庫）                                    │
│  Rule / Decision / Pitfall / ADR / Note                  │
│  FTS5 全文搜尋 + 向量搜尋（可選）                           │
└──────────────────────────────────────────────────────────┘
          ↑
   brain.db（SQLite）— 單一檔案，零維運負擔
```

### 多種接入方式

```
brain.db（單一真相源）
     │
     ├── CLI               brain add / brain ask / brain review
     ├── MCP Server        Claude Code / 小龍蝦 / 任何 MCP Agent
     ├── HTTP MCP Server   遠端 Agent 透過網路連接
     ├── Telegram          透過 AI Agent 轉接（解決網路問題）
     ├── WebUI             瀏覽器視覺化 + 行內編輯
     └── REST API          CI / 腳本 / 自動化
```

所有接入方式讀寫同一個 `brain.db`，知識即時共享。

### 知識節點類型

| 類型 | 什麼時候用 | 例子 |
|------|-----------|------|
| `Rule` | 必須遵守的規則 | JWT 必須使用 RS256 |
| `Decision` | 架構決策與理由 | 選用 PostgreSQL 而非 MySQL |
| `Pitfall` | 踩過的坑 | mock 測試通過但生產 migration 失敗 |
| `ADR` | 正式架構決策記錄 | ADR-001: 採用 Clean Architecture |
| `Note` | 一般筆記 | 部署流程備忘 |

---

## 快速開始

### 安裝

```bash
pip install "project-brain[mcp]"
```

### 初始化

```bash
cd /your/project
brain setup
```

這會：
1. 建立 `.brain/brain.db`（知識庫）
2. 安裝 `git post-commit hook`（自動學習）
3. 偵測 AI 助手並寫入 MCP 設定

### 基本操作

```bash
# 加入知識
brain add "JWT 必須驗證 exp 欄位" --kind Rule
brain add "選用 PostgreSQL" --kind Decision --content "需要 ACID 保證"

# 查詢知識
brain ask "JWT 設定"
brain context "我要修改付款流程"

# 查看狀態
brain status
brain health
```

### AI 助手自動整合

安裝後 Brain 透過 MCP 自動與 Claude Code 整合。開始任務時 AI 自動取得相關知識，完成任務時自動記錄學到的東西。無需手動操作。

---

## 核心功能

### 自動知識提取

```
git commit → post-commit hook → AI 分析 diff → 提取知識 → KRB 暫存區 → 人工審查 → L3 長期記憶
```

每次 commit 後，AI 自動判斷是否有值得記住的東西，提取後等待人工審查才正式入庫。

### 知識審查（KRB）

```bash
brain review list              # 列出待審知識
brain review approve <id>      # 核准 → 進入長期記憶
brain review reject <id>       # 駁回
```

### 知識衰減

6 個因子讓知識信心隨時間自動演變：

| 因子 | 效果 |
|------|------|
| 時間衰減 | 舊知識信心自然降低 |
| 版本差距 | 關聯 commit 距今越遠懲罰越大 |
| git 活動 | 相關程式碼持續活躍 → 信心回升 |
| 矛盾懲罰 | 有衝突知識存在 → 信心降低 |
| 程式碼引用 | 被程式碼引用確認 → 信心提升 |
| 查詢頻率 | 常被查詢的知識 → 信心維持 |

### MCP Server（AI Agent 整合）

Brain 提供 18 個 MCP 工具，任何支援 MCP 協定的 AI Agent 都可以使用：

| 工具 | 用途 |
|------|------|
| `get_context` | 取得任務相關知識 |
| `search_knowledge` | 搜尋知識庫（支援 author 過濾） |
| `add_knowledge` | 加入知識（支援 source 追蹤） |
| `batch_add_knowledge` | 批次加入（最多 50 條） |
| `complete_task` | 記錄任務完成 + 學到的東西 |
| `brain_status` | 知識庫統計 |
| `report_knowledge_outcome` | 回饋知識是否有用 |
| `krb_pre_screen` | AI 預審待審知識 |
| `impact_analysis` | 分析元件影響範圍 |

完整清單：18 個工具，詳見 [COMMANDS.md](COMMANDS.md)。

### HTTP MCP Server（遠端連接）

```bash
# 啟動 HTTP MCP Server（供遠端 AI Agent 連接）
brain serve --mcp --auth-key $BRAIN_API_KEY --port 3000

# 健康檢查
curl http://localhost:3000/health
# → {"status": "ok", "version": "0.46.0", "transport": "streamable-http"}
```

安全機制：Bearer token 認證 + 每 IP 限流 + CORS 白名單。

### CI 整合

```yaml
# .github/workflows/ci.yml
- name: Health check
  run: |
    brain health --json | python -c "
    import json,sys; d=json.load(sys.stdin)
    sys.exit(0 if d['summary']['overall'] in ('ok','warn') else 1)"

- name: Validate
  run: brain validate --ci --output report.json
```

### WebUI 視覺化

```bash
brain webui --port 7890
```

- D3.js 知識圖譜（節點 + 邊關係）
- 行內編輯節點（title / kind / confidence / content）
- KRB Staging 管理面板（approve / reject）

### Federation 跨知識庫同步

```bash
cd /project-a && brain fed export --output /tmp/bundle.json
cd /project-b && brain fed import /tmp/bundle.json
```

自動 PII 清理（email / private IP / internal hostname）與去重。

---

## 團隊共享

### 方式 1：AI Agent + Telegram（推薦，零基礎設施）

```
公司機器上運行：
  Brain MCP Server ←→ AI Agent（如小龍蝦 / OpenClaw）←→ Telegram
  
同事透過 Telegram：
  - 上傳文件 → AI 提取知識 → 自動寫入 Brain
  - 問問題 → AI 查詢 Brain → 回覆知識
  - 審查知識 → AI 呼叫 Brain → 核准/駁回
```

不需要公網 IP、不需要 VPN。AI Agent 負責 Telegram 介面，Brain 負責知識儲存。

### 方式 2：HTTP MCP 直連（需網路直通）

```bash
brain serve --mcp --auth-key $KEY --bind 0.0.0.0 --port 3000
```

其他機器的 AI Agent 直接連接：
```json
{
  "mcpServers": {
    "company-brain": {
      "url": "http://brain-server:3000/mcp",
      "headers": {"Authorization": "Bearer $KEY"}
    }
  }
}
```

### 多用戶安全

- **知識來源追蹤**：每條知識記錄 `source`（如 `telegram:@alice`）
- **並發安全**：SQLite WAL 模式 + process-local 寫入序列化（單機 best-effort，非強一致）
- **按 author 搜尋**：`search_knowledge(query, author="telegram:@alice")`

---

## 安裝選項

| 配置 | 命令 | 說明 |
|------|------|------|
| 最小安裝 | `pip install project-brain` | 純 FTS5 全文搜尋（recall 55%） |
| 推薦安裝 | `pip install "project-brain[mcp]"` | + MCP Server 支援 |
| Hybrid 語意搜尋 | `pip install "project-brain[semantic]"` | + sentence-transformers（recall **90%**） |
| 完整安裝 | `pip install "project-brain[all]"` | 含全部功能 |

詳見 [INSTALL.md](INSTALL.md)。

---

## 全部命令

```bash
# 日常使用
brain setup              # 一鍵初始化
brain add "知識"          # 手動加入
brain ask "問題"          # 查詢
brain search "關鍵字"     # 全文搜尋
brain status             # 狀態概覽
brain review list        # 審查 KRB 暫存

# AI 與團隊
brain serve --mcp        # 啟動 MCP Server（本地 AI）
brain serve --mcp --auth-key $KEY  # HTTP MCP Server（遠端/團隊）
brain webui              # 瀏覽器視覺化

# 管理維護
brain health --json      # 健康診斷（CI 友好）
brain validate --ci      # 知識驗證（CI 友好）
brain eval run           # 檢索品質評估（recall/MRR/nDCG）
brain pipeline-stats     # Pipeline 統計
brain doctor --fix       # 環境診斷 + 自動修復
brain optimize           # 資料庫最佳化
brain export / import    # 匯出匯入
```

詳見 [COMMANDS.md](COMMANDS.md)。

---

## 效能指標（v0.60.0）

| 指標 | 數值 |
|------|------|
| Hybrid recall@3（sentence-transformers e5-small）| **90%** |
| FTS5-only recall@3 | 55% |
| FastAPI Discovery Rate（Hybrid）| **75%** |
| FastAPI Discovery Rate（FTS5-only）| 35% |
| FTS5 搜尋延遲（5K nodes p99）| ≤ 300ms |
| 批次寫入吞吐量 | ≥ 200 nodes/s |
| 測試數量 | **1532 passed**（0 failed） |
| 覆蓋率 | ~51% |
| 並發安全 | 100 threads × 10 writes（0 丟失） |

---

## 文件

| 文件 | 說明 |
|------|------|
| [docs/USER_GUIDE.md](docs/USER_GUIDE.md) | **使用者指南**（入門必讀，1214 行） |
| [COMMANDS.md](COMMANDS.md) | 所有命令詳細說明 |
| [INSTALL.md](INSTALL.md) | 安裝指南 |
| [docs/SYSTEM_DEEP_REVIEW_2026-05-04.md](docs/SYSTEM_DEEP_REVIEW_2026-05-04.md) | 深度系統審查 v0.60.0：架構+性能雙突破 |
| [docs/COMPETITIVE_ANALYSIS.md](docs/COMPETITIVE_ANALYSIS.md) | 競品分析：Brain vs Zep/Mem0/Cognee |
| [docs/EXPERIMENT_REPORT.md](docs/EXPERIMENT_REPORT.md) | 實驗驗證：零依賴系統完整性 |
| [docs/ROADMAP.md](docs/ROADMAP.md) | 開發路線圖 |
| [CHANGELOG.md](CHANGELOG.md) | 版本歷史 |

---

## 授權

MIT License — 詳見 [LICENSE](LICENSE)（如有）。

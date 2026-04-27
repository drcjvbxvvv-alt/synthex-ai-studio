# Project Brain — AI 記憶系統

> 為 AI Agent 設計的工程記憶基礎設施。
> 讓 Claude Code 記住你的架構決策、踩過的坑、和專案規則。

---

## 什麼是 Project Brain？

Project Brain 是一個**持久化知識庫**，與 Claude Code 深度整合：

- **自動學習**：每次 `git commit` 後自動提取值得記住的知識
- **智慧注入**：開始任務前自動把相關知識注入 AI Context
- **知識衰減**：舊的、不再引用的知識自動降低信心，不讓 AI 說出過時建議
- **審查機制**：AI 提取的知識進入暫存區（KRB），人工確認後才進入長期記憶

---

## 三層記憶架構

```
┌──────────────────────────────────────────────────────────┐
│  L1a — Session Memory（工作記憶）                          │
│  當前任務上下文，任務結束後清除                              │
├──────────────────────────────────────────────────────────┤
│  L2 — Episodic Memory（情節記憶）                          │
│  git commit 歷史、任務完成記錄，自動老化                     │
├──────────────────────────────────────────────────────────┤
│  L3 — Semantic Memory（語意記憶）                          │
│  知識節點（Rule / Decision / Pitfall / ADR）               │
│  FTS5 全文搜尋 + 向量搜尋（可選）                           │
└──────────────────────────────────────────────────────────┘
          ↑
   brain.db（SQLite）— 單一檔案，零維運負擔
```

### 知識節點類型

| 類型 | 說明 | 例子 |
|------|------|------|
| `Rule` | 必須遵守的規則 | JWT 必須使用 RS256 |
| `Decision` | 架構決策與理由 | 選用 PostgreSQL 而非 MySQL |
| `Pitfall` | 踩過的坑 | mock 資料庫測試通過但生產 migration 失敗 |
| `ADR` | 架構決策記錄（較正式）| ADR-001: 採用 Clean Architecture |
| `Note` | 一般筆記 | 部署流程備忘 |

---

## 快速開始

### 安裝

```bash
pip install "project-brain[mcp]"
```

### 初始化新專案

```bash
cd /your/project
brain setup
```

這會：
1. 建立 `.brain/brain.db`（知識庫）
2. 安裝 `git post-commit hook`（自動學習）
3. 偵測 Claude Code 並寫入 MCP 設定

### 手動加入知識

```bash
brain add "JWT 必須驗證 exp 欄位" --kind Rule --scope auth
brain add "選用 PostgreSQL" --kind Decision --content "需要 ACID 保證，且團隊熟悉"
```

### 查詢知識

```bash
brain ask "JWT 設定"
brain context "我要修改付款流程"
```

### 查看狀態

```bash
brain status       # 三層記憶概覽
brain health       # DB / schema / signal queue 健康診斷
brain health --json  # CI 友好的 JSON 輸出
```

### 在 Claude Code 中使用

安裝後 Brain 透過 MCP 自動整合：

```
# .claude/settings.json 由 brain setup 自動寫入
```

開始任務時 Claude Code 會自動呼叫 `get_context`，
把相關知識注入對話 context，無需手動操作。

---

## 核心功能

### 自動知識提取 Pipeline

```
git commit → post-commit hook
    → signal emit (SignalQueue)
    → PipelineWorker (background daemon)
    → LLMJudgmentEngine (add / skip 決策)
    → KnowledgeExecutor → brain.db (L3)
```

每次 commit 後，AI 分析 diff，決定是否提取知識節點。
分析結果先進 KRB Staging 等待審核。

### KRB 知識審查機制

```bash
# 列出待審知識
brain review list

# 核准（進入 L3 長期記憶）
brain review approve <id>

# 駁回
brain review reject <id> --reason "資訊不正確"
```

### 知識衰減系統

6 個衰減因子讓知識信心隨時間演變：

| 因子 | 效果 |
|------|------|
| F1 時間衰減 | 舊知識信心自然降低 |
| F2 版本差距 | 關聯 commit 距今越遠懲罰越大 |
| F3 git 活動 | 相關程式碼持續活躍 → 信心回升 |
| F4 矛盾懲罰 | 有衝突知識存在 → 信心降低 |
| F5 程式碼引用 | 被程式碼引用確認 → 信心提升 |
| F6 查詢頻率 | 常被查詢的知識 → 信心維持 |

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
# 開啟 http://localhost:7890
```

- D3.js 知識圖譜（節點 + 邊關係）
- 行內編輯節點（title / kind / confidence / content）
- KRB Staging 管理面板（approve / reject）

### Federation 跨知識庫同步

```bash
# 從 A 專案匯出
cd /project-a && brain fed export --output /tmp/bundle.json

# 匯入到 B 專案（進入 KRB 等待審核）
cd /project-b && brain fed import /tmp/bundle.json
```

自動 PII 清理（email / private IP / internal hostname）與去重。

---

## 安裝選項

| 配置 | 命令 | 說明 |
|------|------|------|
| 最小安裝 | `pip install project-brain` | LocalTFIDF，純 FTS5 |
| 推薦安裝 | `pip install "project-brain[mcp]"` | + MCP Server 支援 |
| 完整功能 | + Ollama nomic-embed-text | 88% 語意召回率 |

詳見 [INSTALL.md](INSTALL.md)。

---

## 全部命令

```bash
brain setup              # 一鍵初始化
brain add "知識"          # 手動加入
brain ask "問題"          # 查詢
brain status             # 狀態概覽
brain health --json      # 健康診斷（CI 友好）
brain validate --ci      # 知識驗證（CI 友好）
brain pipeline-stats     # Pipeline 統計
brain review list        # 審查 KRB 暫存
brain webui              # 視覺化界面
brain doctor             # 環境診斷
```

詳見 [COMMANDS.md](COMMANDS.md)。

---

## 效能指標（v0.46.0）

| 指標 | 數值 |
|------|------|
| FTS5 搜尋延遲（5K nodes p99）| ≤ 300ms |
| FTS5 搜尋延遲（5K nodes avg）| ≤ 100ms |
| 批次寫入吞吐量 | ≥ 200 nodes/s |
| 語意召回率（LocalTFIDF）| ~65% |
| 語意召回率（Ollama nomic-embed-text）| ~88% |
| 測試數量 | 1029 passed |
| 覆蓋率 | ~47% |

---

## 文件

| 文件 | 說明 |
|------|------|
| [COMMANDS.md](COMMANDS.md) | 所有命令詳細說明 |
| [INSTALL.md](INSTALL.md) | 安裝指南（含 GPU/LoRA）|
| [tests/TEST_PLAN.md](tests/TEST_PLAN.md) | 完整測試計劃 |
| [docs/ROADMAP.md](docs/ROADMAP.md) | 開發路線圖 |
| [docs/EXPERIMENT_REPORT.md](docs/EXPERIMENT_REPORT.md) | 實驗驗證報告 |
| [CHANGELOG.md](CHANGELOG.md) | 版本歷史 |

---

## 授權

MIT License — 詳見 [LICENSE](LICENSE)（如有）。

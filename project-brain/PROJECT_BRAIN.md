# Project Brain — 技術文件

> 詳細技術文件請見：[docs/BRAIN_MASTER.md](docs/BRAIN_MASTER.md)

本文件是 `BRAIN_MASTER.md` 的對外摘要版本。

---

## 什麼是 Project Brain

Project Brain 讓 AI Agent 擁有長期記憶，能夠記住你的專案踩坑、架構決策、工程規則，並在每次對話中自動提供給 Agent。

**核心能力（v0.2.0）：**
- 📝 **知識加入**：`brain add "JWT 必須用 RS256"` — 即時加入，即時可查
- 🔍 **語意搜尋**：FTS5 關鍵字 + 向量語意混合搜尋
- 🗂 **空間隔離**：scope 自動從目錄推導，payment_service 的規則不污染 auth
- ⏳ **時光機**：`temporal_query(git_branch="v1-legacy")` 查詢任意時間點的知識
- 🔗 **因果鏈**：`brain ask "JWT"` 輸出 `🛡 [JWT RS256] PREVENTS [Token 過期漏洞]`
- 🤖 **MCP 整合**：Claude Code / Cursor 直接讀寫知識庫
- 📡 **CLAUDE.md**：`brain setup` 自動生成，讓 Claude Code 每次對話帶上 Brain context
- 🔒 **信心語意標注**：`⚠ 推測` / `~ 推斷` / `✓ 已驗證` / `✓✓ 權威` 四層標注
- 🛠 **資料庫維護**：`brain optimize` 執行 VACUUM + ANALYZE + FTS5 rebuild
- 📤 **知識匯出入**：`brain export/import` 支援 JSON / Neo4j Cypher 格式
- 📊 **使用率分析**：`brain analytics` 顯示節點存取統計，可匯出 CSV

## 三層記憶架構

```
L3 語意記憶  →  brain add / MCP add_knowledge
L2 情節記憶  →  git commit → brain sync（自動）
L1 工作記憶  →  當前 session
```

全部儲存在單一 `brain.db`（SQLite），備份 = 複製一個文件。

## 快速開始

```bash
pip install project-brain
cd /your/project
brain setup
brain add "你的第一條規則"
brain ask "你的查詢"
```

詳細安裝說明：[INSTALL.md](INSTALL.md)  
命令參考：[COMMANDS.md](COMMANDS.md)  
設計文件：[docs/BRAIN_MASTER.md](docs/BRAIN_MASTER.md)

# SYNTHEX AI STUDIO — 安裝與環境設定

> 完整安裝指南，從零到第一次執行 `/ship`，大約 10 分鐘。

---

## 目錄

- [系統需求](#系統需求)
- [取得 SYNTHEX](#一取得-synthex)
- [安裝 Python 依賴](#二安裝-python-依賴)
- [設定 API Key](#三設定-api-key)
- [設定工作目錄](#四設定工作目錄)
- [初始化 Project Brain](#五初始化-project-brain)
- [選填：Graphiti L2 記憶](#六選填啟用-graphiti-l2-記憶)
- [選填：Web UI](#七選填啟用知識圖譜-web-ui)
- [Claude Code 整合](#八claude-code-整合)
- [驗證安裝](#九驗證安裝)
- [常見問題](#常見問題)

---

## 系統需求

| 項目 | 最低需求 | 建議 |
|------|---------|------|
| Python | 3.11+ | 3.12 |
| 記憶體 | 4GB | 8GB+ |
| 磁碟空間 | 500MB | 2GB+（知識庫會成長）|
| 作業系統 | macOS / Linux / WSL2 | macOS / Ubuntu 22.04 |
| Anthropic API | 必要（計費） | claude-opus-4-6 存取 |

---

## 一、取得 SYNTHEX

```bash
# 解壓縮發行版
unzip synthex-release-v13.zip -d ~/tools/
cd ~/tools/synthex-ai-studio
```

---

## 二、安裝 Python 依賴

```bash
# 建立虛擬環境（強烈建議，避免版本衝突）
python3 -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows PowerShell

# 安裝核心依賴
pip install -r requirements.txt
```

**核心依賴說明：**

| 套件 | 版本 | 用途 |
|------|------|------|
| `anthropic` | ≥0.74.0 | Claude API SDK（Memory Tool 需要此版本）|
| `pydantic` | ≥2.7.0 | 資料驗證 |
| `pydantic-settings` | ≥2.3.0 | 集中設定管理 |
| `structlog` | ≥24.1.0 | 結構化日誌 |
| `chromadb` | ≥0.4.0 | 向量記憶（語義搜尋）|

**選填依賴：**

```bash
# Web UI（知識圖譜視覺化）
pip install flask flask-cors

# Graphiti 時序知識圖譜
pip install graphiti-core falkordb

# OpenTelemetry 可觀測性
pip install opentelemetry-sdk opentelemetry-api
```

---

## 三、設定 API Key

### 永久設定（推薦）

```bash
# macOS / zsh（加到 ~/.zshrc）
echo 'export ANTHROPIC_API_KEY="sk-ant-xxxxxxxx"' >> ~/.zshrc
source ~/.zshrc

# Linux / bash（加到 ~/.bashrc）
echo 'export ANTHROPIC_API_KEY="sk-ant-xxxxxxxx"' >> ~/.bashrc
source ~/.bashrc
```

### 臨時設定

```bash
export ANTHROPIC_API_KEY="sk-ant-xxxxxxxx"
```

### 驗證

```bash
python synthex.py list
# 若顯示 28 個 Agent 列表，Key 設定正確
```

Key 格式無效時會看到：`ANTHROPIC_API_KEY 格式無效（應以 sk-ant- 或 sk- 開頭）`

---

## 四、設定工作目錄

SYNTHEX 需要一個「工作目錄」作為 Agent 的操作根目錄：

```bash
# 永久設定（記住在 ~/.synthex/config.json）
python synthex.py workdir ~/projects/my-app

# 或每次指定
python synthex.py ship "需求" --workdir ~/projects/my-app
```

工作目錄應是你的 git 倉庫根目錄。Agent 會在這裡：
- 讀寫程式碼檔案
- 建立 `docs/` 目錄（PRD、架構文件、測試報告）
- 建立 `.brain/` 目錄（Project Brain 三層記憶庫）

---

## 五、初始化 Project Brain

Project Brain 是 SYNTHEX 的長期記憶系統，建議所有新專案都初始化。

```bash
cd ~/projects/my-app
python ~/tools/synthex-ai-studio/synthex.py brain init

# 輸出：
# ✅ Project Brain v4.0 初始化完成
# • Git Hook 已設定（每次 commit 自動學習 → L2 + L3）
# • L1 SQLite 工作記憶已建立（.brain/working_memory.db）
# • L3 SQLite 知識圖譜已建立（.brain/knowledge_graph.db）
```

**舊專案：考古掃描**（分析 Git 歷史重建知識庫）

```bash
python ~/tools/synthex-ai-studio/synthex.py brain scan
# 約 3-10 分鐘，分析最近 200 個 commit
```

---

## 六、選填：啟用 Graphiti L2 記憶

Graphiti 提供時序知識圖譜，可以查詢「這個決策現在還有效嗎？」

```bash
pip install graphiti-core falkordb

# 啟動 FalkorDB（需要 Docker）
docker run -d -p 6379:6379 --name falkordb falkordb/falkordb

# 驗證連線
python synthex.py brain status
# **L2 Graphiti（時序圖）**
#   ✓ 已連接 bolt://localhost:7687
```

不安裝 Graphiti 時，系統自動降級到 SQLite 時序圖（v1.1），功能完整。

---

## 七、選填：啟用知識圖譜 Web UI

```bash
pip install flask flask-cors

# 啟動視覺化界面
python -m core.brain.web_ui.server --workdir ~/projects/my-app --port 7890
# 瀏覽器開啟 http://localhost:7890
```

功能：D3.js 力導向圖、節點衰減熱力圖、即時搜尋、知識健康儀表板。

---

## 八、Claude Code 整合

**方式 A：CLAUDE.md 自動載入**

```bash
# 複製到你的專案根目錄
cp ~/tools/synthex-ai-studio/CLAUDE.md ~/projects/my-app/

# Claude Code 啟動時自動讀取，化身 SYNTHEX 公司
```

**方式 B：MCP Server（讓 Claude Code 直接查詢 Brain）**

在 `~/.claude/settings.json` 加入：

```json
{
  "mcpServers": {
    "project-brain": {
      "command": "python",
      "args": ["-m", "core.brain.mcp_server"],
      "cwd": "/path/to/synthex-ai-studio",
      "env": { "BRAIN_WORKDIR": "/your/project" }
    },
    "graphiti-brain": {
      "command": "python",
      "args": ["-m", "core.brain.graphiti_mcp_server"],
      "cwd": "/path/to/synthex-ai-studio",
      "env": {
        "BRAIN_WORKDIR": "/your/project",
        "GRAPHITI_URL": "bolt://localhost:7687"
      }
    }
  }
}
```

---

## 九、驗證安裝

```bash
# 1. 確認 28 個 Agent 都存在
python synthex.py list

# 2. 快速 Agent 測試
python synthex.py ask ARIA "你好，介紹一下自己"

# 3. 執行完整測試套件
python -m pytest tests/ -v
# → 應顯示 139 passed

# 4. 查看 Brain 三層狀態
python synthex.py brain status

# 5. 執行品質評估（可選）
python -m core.evals run --suite prd_quality --dry-run
```

---

## 常見問題

**Q：`ModuleNotFoundError: No module named 'anthropic'`**
```bash
source .venv/bin/activate   # 確認虛擬環境已啟動
pip install -r requirements.txt
```

**Q：`ANTHROPIC_API_KEY 格式無效`**
前往 [platform.claude.com](https://platform.claude.com) → API Keys 取得有效 Key。

**Q：`Brain 記憶不存在` 錯誤**
```bash
cd /your/project
python /path/to/synthex.py brain init
```

**Q：Windows 支援**
建議使用 **WSL2**（Windows Subsystem for Linux）。原生 Windows 可能遇到 `fcntl` 模組缺失（進程鎖降級），其餘功能正常。

**Q：API 費用估算**

| 場景 | 估計費用 |
|------|---------|
| 簡單功能（1-3 Phase）| ~$0.20-0.80 USD |
| 完整 `/ship`（12 Phase）| ~$1.00-5.00 USD |
| `/discover` 深挖需求 | ~$0.50-2.00 USD |

設定預算上限：
```bash
python synthex.py ship "需求" --budget 2.0   # 最高 $2 USD
```

---

## 目錄結構

```
synthex-ai-studio/
├── synthex.py              主入口（所有命令從這裡開始）
├── requirements.txt        Python 依賴
├── CLAUDE.md               Claude Code 角色定義（複製到你的專案）
├── README.md               快速入門
├── INSTALL.md              本文件
├── COMMANDS.md             命令完整參考
├── AGENTS.md               28 位 Agent 詳細說明
├── ARCHITECTURE.md         技術架構深度說明
├── PROJECT_BRAIN.md        Project Brain v4.0 完整文件
├── SECURITY.md             安全設計說明
├── EVALS.md                品質評估指南
├── CONTRIBUTING.md         開發者貢獻指南
├── CHANGELOG.md            版本更新記錄
├── core/                   核心框架
│   ├── config.py           集中設定（ModelID、Tier、成本）
│   ├── base_agent.py       BaseAgent v4 + CompactionManager
│   ├── web_orchestrator.py 12-Phase 流水線
│   ├── swarm.py            AgentSwarm 並行協作
│   ├── evals.py            品質評估框架
│   ├── rate_limiter.py     Token Bucket 速率限制
│   ├── observability.py    OpenTelemetry 整合
│   └── brain/              Project Brain v4.0（三層認知記憶）
├── agents/
│   └── all_agents.py       28 個 Agent 定義
├── tests/
│   └── test_core.py        139 個自動化測試
├── evals/
│   └── suites/             Golden Dataset（prd / arch / security / code）
└── project-template/       新專案模板
```

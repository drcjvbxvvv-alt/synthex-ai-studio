# SYNTHEX AI STUDIO

> 28 個 AI Agent，8 個部門，一行命令讓整個虛擬軟體公司為你工作。

---

## 目錄

- [這是什麼](#這是什麼)
- [快速安裝](#快速安裝)
- [核心架構](#核心架構)
- [兩種使用方式](#兩種使用方式)
- [核心命令](#核心命令)
- [Project Brain 長期記憶](#project-brain-長期記憶)
- [28 位 Agent](#28-位-agent)
- [常見場景](#常見場景)
- [品質與安全](#品質與安全)
- [延伸閱讀](#延伸閱讀)

---

## 這是什麼

SYNTHEX AI STUDIO 是一個自主式 AI 軟體開發框架。你描述想做什麼，它負責把想法變成可以跑起來的程式碼。

**不是 AI 助手，是 AI 公司。** 差別在於：

| 傳統 AI 助手 | SYNTHEX AI STUDIO |
|------------|------------------|
| 你問一個問題，它回答一個問題 | 你給一個需求，它從分析到交付全部完成 |
| 你要把 AI 回答的程式碼複製貼上 | Agent 直接讀寫你的專案檔案 |
| 每次對話從零開始 | Project Brain 記錄每個決策，永久積累 |
| 一個 AI 做所有事 | 28 個 Agent 各司其職，並行工作 |

**核心設計數字：**

- **28 個 Agent**，8 個部門（高層管理、工程、設計、AI、基礎架構、品質、商務、硬體）
- **12 Phase 流水線**（需求確認 → PRD → 架構 → 實作 → 測試 → 安全 → 交付）
- **Project Brain v4.0** — 三層認知記憶系統（L1 工作記憶 + L2 時序圖譜 + L3 語義知識）
- **AgentSwarm** — 並行多 Agent 協作，Phase 9+10 並行省 30-50% 時間
- **139 個自動化測試**，全數通過

---

## 快速安裝

```bash
# 1. 下載並放到合適位置
mv synthex-ai-studio ~/tools/
cd ~/tools/synthex-ai-studio

# 2. 安裝 Python 依賴
pip install -r requirements.txt

# 3. 設定 API Key（加到 ~/.zshrc 或 ~/.bashrc 永久生效）
export ANTHROPIC_API_KEY="sk-ant-..."

# 4. 設定你的預設工作目錄
python synthex.py workdir ~/projects/my-app

# 5. 驗證安裝
python synthex.py list
```

詳細安裝說明見 [INSTALL.md](INSTALL.md)。

---

## 核心架構

```
你的需求
    ↓
synthex.py（CLI 入口）
    ↓
WebOrchestrator（12 Phase 流水線）
    ├── Phase 1：ARIA — 任務確認
    ├── Phase 2：ECHO — 需求分析 PRD
    ├── Phase 3：LUMI — 產品驗證
    ├── Phase 4：NEXUS — 技術架構
    ├── Phase 5：SIGMA — 可行性評估
    ├── Phase 6：FORGE — 環境準備
    ├── Phase 7：SPARK — UX 設計
    ├── Phase 8：PRISM — UI 設計系統
    ├── Phase 9+10：BYTE + STACK（並行）— 實作
    ├── Phase 11：PROBE + TRACE — 測試
    └── Phase 12：SHIELD + ARIA — 安全審查 + 交付
            ↓
    AgentSwarm（並行協作）
            ↓
    BaseAgent（單一 Agent 執行單元）
    ├── CompactionManager — Context 長任務管理
    ├── TokenBudget — 成本控制
    ├── CircuitBreaker — 故障隔離
    └── Project Brain v4.0 — 知識注入
```

**模型分配策略（config.py）：**

| 層級 | 模型 | 適用 Agent |
|------|------|-----------|
| Opus 4.6 | 最高品質，1M context | NEXUS、ARIA、SIGMA |
| Sonnet 4.6 | 均衡，1M context | BYTE、STACK、ECHO 等主力 |
| Haiku 4.5 | 快速廉價 | RELAY、BRIDGE、WIRE 等輔助 |

---

## 兩種使用方式

### 方式 A：Synthex CLI（適合自動化流水線）

```bash
# 需求模糊時，先挖掘需求
python synthex.py discover "我想做一個台灣股票 AI 分析平台"

# 需求確認後，一氣呵成交付
python synthex.py ship "電商平台：商品瀏覽、購物車、Stripe 結帳..."

# 在現有專案開發
python synthex.py feature "新增 Google OAuth 登入"

# 修復問題
python synthex.py fix "用戶登出後資料仍顯示上一個用戶的"
```

### 方式 B：Claude Code + CLAUDE.md（適合高品質互動開發）

```bash
# 把 CLAUDE.md 複製到你的專案
cp ~/tools/synthex-ai-studio/CLAUDE.md ~/projects/my-app/

# 開啟 Claude Code
cd ~/projects/my-app && claude

# 在 Claude Code 裡直接用角色
# @NEXUS 設計技術架構
# @BYTE 實作登入頁面
# @SHIELD 做安全審查
```

**選擇哪種方式？**

- 需要**快速產出骨架**，或希望**完全自動** → 選 CLI
- 需要**高品質交付**，或想要**全程介入** → 選 Claude Code
- 最佳組合：**CLI 做規劃（discover + agent）→ Claude Code 做實作**

---

## 核心命令

### 開發流程

```bash
# 需求挖掘（模糊想法 → 完整需求書）
python synthex.py discover "你的想法"

# 全自動交付（需求書 → 可執行程式碼）
python synthex.py ship "完整需求描述"
python synthex.py ship "需求" --budget 10.0   # 設定最高成本（美元）

# 功能開發（在現有專案加功能）
python synthex.py feature "新功能描述"

# 問題修復
python synthex.py fix "bug 描述"

# 專案調查（找出問題根源）
python synthex.py investigate "問題描述"
```

### Agent 互動

```bash
# 問任何問題（智能路由選最合適的 Agent）
python synthex.py ask "JWT RS256 和 HS256 有什麼差別？"

# 指定 Agent 對話
python synthex.py agent NEXUS "評估用 GraphQL 替換 REST API 的利弊"

# 多角色持續對話（保留記憶）
python synthex.py chat NOVA

# Agentic 模式（Agent 直接操作你的檔案）
python synthex.py do SHIELD "掃描 API 路由，修復缺少授權檢查的端點"

# Agentic Shell（互動式）
python synthex.py shell BYTE
```

### 部門協作

```bash
# 讓整個部門一起分析
python synthex.py dept engineering "評估把 Python 後端改寫為 Go 的工作量"

# 多部門專案規劃
python synthex.py project "建立 AI 客服系統，需要 NLP + 後台 + 數據分析"
```

### 工具

```bash
# 設定預設工作目錄
python synthex.py workdir ~/projects/my-app

# 列出所有 Agent
python synthex.py list

# 清除 Agent 記憶
python synthex.py clear NEXUS

# 程式碼審查
python synthex.py review BYTE   # 貼入程式碼讓 BYTE 審查

# 全專案回顧
python synthex.py retro

# 瀏覽器 QA
python synthex.py qa_browser --url http://localhost:3000
```

完整命令參考見 [COMMANDS.md](COMMANDS.md)。

---

## Project Brain 長期記憶

Project Brain 是 SYNTHEX 最獨特的功能：**讓 AI 永遠記得你的專案**。

### 快速開始

```bash
# 新專案初始化（只需一次）
python synthex.py brain init

# 舊專案考古掃描（只需一次，約 3-10 分鐘）
python synthex.py brain scan

# 之後的 commit 自動學習（Git Hook 自動觸發）
git commit -m "feat: 加入冪等性機制"

# 查看三層記憶狀態
python synthex.py brain status
```

### 三層認知架構（v4.0）

```
L1 工作記憶 — Anthropic Memory Tool
   即時任務資訊（本次踩坑、任務進展）
   生命週期：session，<10ms 查詢
   效果：84% token 節省

L2 情節記憶 — Graphiti 時序知識圖譜
   「三個月前的決策現在還有效嗎？」
   雙時態模型（t_valid/t_invalid），<100ms
   後端：FalkorDB / Neo4j

L3 語義記憶 — Project Brain v2.0
   深度語義知識、反事實推理、知識衰減
   永久保留，SQLite + Chroma
```

### v4.0 新功能

- **知識自動驗證**：AI 定期確認知識是否仍然準確
- **聯邦匿名共享**：差分隱私保護下，與業界共享踩坑知識
- **知識蒸餾**：壓縮為 Markdown 摘要 / 角色 Prompt / LoRA 訓練數據
- **Web UI**：D3.js 互動式知識圖譜（`http://localhost:7890`）
- **跨 Session 持久化**：重要工作記憶跨次保留

詳細說明見 [PROJECT_BRAIN.md](PROJECT_BRAIN.md)。

---

## 28 位 Agent

### 🎯 高層管理

| Agent | 職位 | 核心能力 |
|-------|------|---------|
| **ARIA** | 執行長 CEO | 任務確認、流水線指揮、交付總結 |
| **NEXUS** | 技術長 CTO | 系統架構、技術選型、設計評審 |
| **LUMI** | 產品長 CPO | 產品策略、用戶研究、需求驗證 |
| **SIGMA** | 財務長 CFO | 成本估算、可行性評估、ROI 分析 |

### ⚙️ 工程開發

| Agent | 職位 | 核心能力 |
|-------|------|---------|
| **BYTE** | 前端技術主管 | React/Next.js、TypeScript、效能優化 |
| **STACK** | 後端技術主管 | API 設計、PostgreSQL、微服務 |
| **FLUX** | 全端工程師 | 快速原型、第三方整合、Docker |
| **KERN** | 系統工程師 | Linux 底層、效能調優、並發問題 |
| **RIFT** | 行動端工程師 | React Native、iOS/Android |

### 💡 產品設計

| Agent | 職位 | 核心能力 |
|-------|------|---------|
| **SPARK** | UX 設計主管 | 用戶旅程、資訊架構、線框圖 |
| **PRISM** | UI 設計師 | Design System、色彩、組件規範 |
| **ECHO** | 商業分析師 | PRD 撰寫、AC 定義、需求分析 |
| **VISTA** | 產品經理 | Sprint 規劃、Roadmap、ICE 框架 |

### 🧠 AI 與資料

| Agent | 職位 | 核心能力 |
|-------|------|---------|
| **NOVA** | ML 主管 | LLM 整合、RAG、Prompt 工程 |
| **QUANT** | 資料科學家 | 統計分析、A/B 測試、預測建模 |
| **ATLAS** | 資料工程師 | ETL、dbt、資料管線 |

### 🚀 基礎架構

| Agent | 職位 | 核心能力 |
|-------|------|---------|
| **FORGE** | DevOps 主管 | CI/CD、Kubernetes、IaC |
| **SHIELD** | 資安工程師 | OWASP、滲透測試、合規 |
| **RELAY** | 雲端架構師 | AWS/GCP、FinOps、多雲策略 |

### 🔍 品質保證

| Agent | 職位 | 核心能力 |
|-------|------|---------|
| **PROBE** | QA 主管 | 測試策略、品質指標、UAT |
| **TRACE** | 自動化測試 | Playwright、API 測試、E2E |

### 📣 商務發展

| Agent | 職位 | 核心能力 |
|-------|------|---------|
| **PULSE** | 行銷主管 | SEO、GTM、AARRR 成長框架 |
| **BRIDGE** | 業務主管 | 企業銷售、提案設計 |
| **MEMO** | 法務合規 | GDPR、台灣個資法、合約審查 |

### 🔧 硬體嵌入式

| Agent | 職位 | 核心能力 |
|-------|------|---------|
| **BOLT** | 韌體工程師 | MCU、RTOS、Bootloader |
| **VOLT** | 嵌入式 Linux | BSP、Device Driver、Yocto |
| **WIRE** | 硬體整合 | Board Bring-up、驗證測試 |
| **ATOM** | 系統程式 | eBPF、效能分析、核心驅動 |

完整 Agent 說明見 [AGENTS.md](AGENTS.md)。

---

## 常見場景

### 場景 1：從想法到產品骨架（最快路線）

```bash
python synthex.py discover "我想做一個幫台灣小餐廳管理訂單的 SaaS"
# → 30 分鐘後，產出完整需求書

python synthex.py ship "（從 docs/DISCOVER.md 複製的完整需求）"
# → 1-2 小時後，可以跑起來的 Next.js + PostgreSQL 骨架
```

### 場景 2：在現有專案加功能

```bash
python synthex.py workdir ~/projects/my-ecommerce
python synthex.py feature "新增訂單退款功能，支援全額和部分退款"
```

### 場景 3：安全審查

```bash
python synthex.py do SHIELD "全面審查所有 API 端點的授權邏輯，找出漏洞並修復"
```

### 場景 4：Project Brain 輔助開發

```bash
# 初始化記憶系統
python synthex.py brain init

# 每次 git commit 自動學習（設定 Git Hook 後）
git commit -m "fix: 修復支付 timeout 問題"

# 之後開發時，Brain 自動注入相關知識
python synthex.py feature "新增支付退款功能"
# → Brain 自動提醒：「之前有 timeout 踩坑記錄」
```

### 場景 5：Hardware + Software 整合

```bash
# 嵌入式韌體
python synthex.py agent BOLT "設計 STM32 的 UART 驅動，支援 DMA 傳輸"

# 搭配上位機軟體
python synthex.py agent STACK "設計後端 WebSocket API 接收韌體數據"
```

---

## 品質與安全

### 測試框架

```bash
# 執行所有 139 個自動化測試
python -m pytest tests/ -v

# 執行品質評估
python -m core.evals run --suite prd_quality
python -m core.evals run --suite security_quality
```

### 安全設計

- **命令注入防護**：所有外部命令使用 argv 陣列，禁止 `shell=True`
- **路徑穿越防護**：所有檔案操作驗證路徑在工作目錄內
- **SSRF 防護**：封鎖私有 IP 網段（10.x.x.x、192.168.x.x）
- **Rate Limiting**：API 呼叫有速率限制（Token Bucket 算法）
- **Budget Guard**：可設定最高花費上限，超過自動中止

詳細安全說明見 [SECURITY.md](SECURITY.md)。

---

## 延伸閱讀

| 文件 | 說明 |
|------|------|
| [INSTALL.md](INSTALL.md) | 完整安裝與環境設定指南 |
| [COMMANDS.md](COMMANDS.md) | 所有命令的完整參考 |
| [AGENTS.md](AGENTS.md) | 28 位 Agent 詳細說明 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 系統技術架構深度說明 |
| [PROJECT_BRAIN.md](PROJECT_BRAIN.md) | Project Brain v4.0 完整文件 |
| [SECURITY.md](SECURITY.md) | 安全設計與最佳實踐 |
| [EVALS.md](EVALS.md) | 品質評估框架使用指南 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 開發者貢獻指南 |
| [CHANGELOG.md](CHANGELOG.md) | 版本更新記錄 |

---

*SYNTHEX AI STUDIO v4.0 · 28 Agents · 8 Departments · Built with Claude Opus 4.6 / Sonnet 4.6*

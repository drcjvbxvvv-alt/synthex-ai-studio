# 🚀 SYNTHEX AI STUDIO: Architecting a 28-Agent Autonomous Tech Enterprise

> **A Research-Grade Framework for Multi-Agent Software Engineering and Workflow Orchestration**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

## 📖 專案摘要 (Abstract)

隨著大型語言模型（LLMs）的演進，AI 輔助開發正從「單點程式碼補全（Copilot）」轉向「全生命週期代理（Autonomous Agents）」。**SYNTHEX AI STUDIO** 並非單純的開發工具，而是一個高度結構化的**虛擬科技企業微型宇宙**。

本框架內建 7 大跨職能部門、共 28 位具備深度專業領域知識的 AI Agents。我們旨在驗證：「**LLM 如何在長生命週期中保持工程紀律？**」透過『檔案系統作為共享記憶體』、『冪等性的斷點狀態機』、『關注點分離的多執行緒平行生成』，以及全新的『動態驗證引擎』，本專案從底層架構上解決了 AI 輔助開發中常見的上下文遺忘、流水線脆弱與單一模型幻覺等致命問題。

---

## 🔬 核心底層突破：我們解決了什麼問題？ (Core Architectural Solutions)

要讓 AI 從「寫單一函式」進化到「架構 SaaS 平台與軟硬體系統」，必須克服傳統 AI 開發流程的幾大痛點。以下是 SYNTHEX 的具體解決方案與底層實作：

### 1. 治癒 LLM 的「長脈絡遺忘」 (Context Amnesia)

- **痛點**：中大型專案在經過多次對話輪轉後，早期的需求細節（如 API 規格、架構約定）容易因 Context Window 限制被截斷而遺忘。
- **SYNTHEX 解法：實體文件驅動的上下文管理 (Document-Driven Context)**
  - **源碼實作**：在 `core/web_orchestrator.py` 的 `DocContext` 類別中，強制將每一個 Phase 的產出物寫入實體的 Markdown 檔案（如 `docs/PRD.md`、`docs/ARCHITECTURE.md`）。後續接手的 Agent（如 CTO 或前端主管）是直接讀取完整檔案，而不是被截斷的歷史對話字串。
  - **價值**：為不同 Agent 建立「單一真實來源（SSOT）」，從物理層面消除資訊傳遞衰減。

### 2. 克服自動化流水線的「高脆弱性」 (Pipeline Fragility)

- **痛點**：全自動的長步驟生成極度脆弱，一旦在後段發生 API 斷線或錯誤，往往需要重頭來過，消耗巨大 Token 成本。
- **SYNTHEX 解法：冪等性的狀態機斷點續傳 (Stateful Checkpointing)**
  - **源碼實作**：透過 `core/web_orchestrator.py` 中的 `PhaseCheckpoint` 類別，系統將每個階段的執行狀態即時序列化寫入 `docs/.ship_state.json`。配合 `if resume and ckpt.is_done(X):` 邏輯，發生中斷後可完美跳過已完成階段。
  - **價值**：賦予工作流「冪等性」，同時創造了 **Human-in-the-loop** 的空間——開發者可在 Phase 2 後手動精修 PRD，再無縫接續後續開發流程。

### 3. 突破 LLM 生成速度的「線性瓶頸」 (Sequential Generation Bottleneck)

- **痛點**：嚴格依照「寫完前端 -> 寫後端 -> 寫測試」的線性生成，嚴重拖慢開發節奏。
- **SYNTHEX 解法：基於 API 契約的非同步平行實作 (Asynchronous Parallel Execution)**
  - **源碼實作**：在 API 規格（Phase 2）與系統架構（Phase 4）以文件形式確立後，`/ship` 流程的 Phase 7 與 Phase 8 使用了 Python 的 `concurrent.futures.ThreadPoolExecutor(max_workers=2)`。這讓 `BYTE`（前端工程師）與 `STACK`（後端工程師）基於同一份合約進行平行開發。
  - **價值**：將最耗時的程式碼實作階段時間大幅壓縮 30% 到 50%。

### 4. 消除單一 Prompt 的「決策盲點與幻覺」 (Single-Agent Bias & Hallucination)

- **痛點**：要求單一 LLM 同時兼顧業務、資安、架構與財務考量，會導致模型權重拉扯，給出平庸或危險的決策。
- **SYNTHEX 解法：多代理人交叉審查與路由決策網 (Multi-Agent Routing & Synthesis)**
  - **源碼實作**：在 `core/orchestrator.py` 的專案規劃模組中，系統強制平行呼叫 `NEXUS`（技術風險評估）、`LUMI`（PMF 評估）、`SIGMA`（財務 ROI 評估）與 `FORGE`（DevOps 規劃）。隨後交由 `ARIA`（CEO 角色）進行收斂與 Go/No-Go 的最終裁決。
  - **價值**：落實軟體工程的「關注點分離（Separation of Concerns）」，利用 AI 進行「自我對抗」式審查，大幅提升系統架構的落地可行性與安全性。

### 5. 導入動態驗證與環境感知 (Dynamic Verification & Context Awareness)

- **痛點**：AI 在介入現有專案時容易「瞎子摸象」，且純靜態生成的程式碼缺乏真實環境的反饋，難以確保落地品質。
- **SYNTHEX 解法：主動掃描與瀏覽器自動化測試**
  - **源碼實作**：引入 `core/project_scanner.py` 主動解析專案結構與相依套件，並透過 `core/browser_qa.py` 掛載真實瀏覽器進行 UI/UX 驗證。搭配 `core/deploy_pipeline.py` 實現端到端部署。
  - **價值**：賦予系統「視覺」與「環境感知」能力，補足了從靜態生成到動態驗證的最後一哩路。

---

## 🎯 應用場景：何時該使用 SYNTHEX？ (When to use)

SYNTHEX 的威力展現於專案的**混沌期與奠基期**：

- 🧠 **需求模糊探索 (`/discover`)**：當你只有一個概念，6 個高階主管 Agent 會透過連環叩問，深度挖掘市場定位、技術複雜度，最終輸出一份直接可執行的架構規格與 MVP 藍圖。
- 🏗️ **底層架構生成 (`/ship`)**：自動流水線不僅涵蓋前後端，更能擴展至 IoT 韌體與資料工程，一次性建立具備 CI/CD 與自動化測試的企業級專案骨架。

---

## 📦 完整發布包內容 (What's Included)

專案分為「CLI 工具本體」與「專案設定模板」兩大部分：

```text
synthex-release/
│
├── README.md                        ← 你正在讀的這個
│
├── synthex-ai-studio/               ← CLI 工具（Python）
│   ├── synthex.py                   ← 主入口
│   ├── requirements.txt
│   ├── README.md                    ← 完整使用說明
│   ├── CLAUDE.md                    ← 最新版（同 project-template）
│   ├── core/
│   │   ├── base_agent.py            ← Agent 基底
│   │   ├── browser_qa.py            ← 瀏覽器 QA 測試與互動 (新增)
│   │   ├── deploy_pipeline.py       ← 自動化部署流水線 (新增)
│   │   ├── orchestrator.py          ← 智能路由
│   │   ├── project_scanner.py       ← 專案環境與結構掃描 (新增)
│   │   ├── tools.py                 ← 基礎工具（讀寫檔案、執行命令）
│   │   ├── web_orchestrator.py      ← /discover + /ship 流水線
│   │   └── web_tools.py             ← 網頁開發工具（npm、git）
│   ├── agents/
│   │   ├── __init__.py
│   │   └── all_agents.py            ← 全部 28 位 Agent 定義
│   └── memory/                      ← Agent 記憶（執行後自動產生）
│
└── project-template/                ← 複製到每個專案根目錄
    ├── CLAUDE.md                    ← 給 Claude Code 的公司作業系統
    └── agents/                      ← 28 位角色的完整技能手冊 (SKILL.md)
        ├── ARIA/                    ← CEO / 策略與任務確認
        ├── ATLAS/                   ← 基礎設施 / 跨區域網路與 CDN
        ├── ATOM/                    ← 系統程式工程師 / Linux Kernel、C/Rust、高效能 IPC
        ├── BOLT/                    ← 韌體技術主管 / MCU、RTOS、C/C++ 裸機開發
        ├── BRIDGE/                  ← 後端 / 第三方 API 與微服務串接
        ├── BYTE/                    ← 前端實作標準
        ├── ECHO/                    ← 商業分析師 / PRD 規格
        ├── FLUX/                    ← 資料工程 / ETL 與串流架構
        ├── FORGE/                   ← 設定檔範本、CI/CD
        ├── KERN/                    ← 系統效能與底層調優
        ├── LUMI/                    ← 產品長 / 產品驗證
        ├── MEMO/                    ← 知識管理 / Tech Writer 與 API 文件
        ├── NEXUS/                   ← 技術選型、架構文件格式
        ├── NOVA/                    ← ML 主管 / AI 架構設計
        ├── PRISM/                   ← 設計系統、tokens.css 規範
        ├── PROBE/                   ← 測試策略框架
        ├── PULSE/                   ← SRE / 系統監控與可觀測性
        ├── QUANT/                   ← 資料科學 / 演算法與量化模型
        ├── RELAY/                   ← 雲端架構師
        ├── RIFT/                    ← 行動端工程師
        ├── SHIELD/                  ← 安全審查清單
        ├── SIGMA/                   ← 財務長 / 可行性評估
        ├── SPARK/                   ← UX 方法論、線框格式
        ├── STACK/                   ← 後端實作標準
        ├── TRACE/                   ← 自動化測試執行
        ├── VISTA/                   ← 前端 / XR、3D 與進階視覺特效
        ├── VOLT/                    ← 嵌入式系統工程師 / Linux BSP、Device Driver、Yocto
        └── WIRE/                    ← 軟硬體整合工程師 / 協議分析 (SPI/I2C)、Board Bring-up
```

---

## 系統架構：SYNTHEX 與 PROJECT BRAIN 的關係

> 一句話總結：SYNTHEX 是短期執行，PROJECT BRAIN 是長期記憶。前者讓 AI 今天做好這件事，後者讓 AI 明天還記得昨天發生了什麼。兩者組合，AI 就從單純的「工具」升級成「懂你專案的夥伴」。

### 兩者的核心角色

- **SYNTHEX AI STUDIO — 執行引擎（「做事的人」）**
  - 由 28 個 AI Agent 在 12 Phase 流水線中協作，負責把需求變成可運行的程式碼。
  - 每次執行 `ship`、`agent` 或 `do` 指令就是在工作。
  - **特性**：它是無狀態的——執行完就結束，下次啟動不會記得上次做了什麼。

- **PROJECT BRAIN — 記憶系統（「記事的人」）**
  - 跨 session 持續累積專案知識：記錄這個專案踩過哪些坑、做過哪些架構決策、有哪些不能違反的業務規則。
  - **特性**：它不執行任何開發工作，只負責記憶和提供知識。

### 真實場景對比

| 狀態                      | 運作情況                                                                                                                                                                                                          |
| :------------------------ | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **沒有 Project Brain 時** | • NEXUS 每次都是空白頭腦設計架構<br>• SHIELD 不知道這個專案上次踩過 Stripe Webhook 的坑<br>• BYTE 不記得金額要用 cent 整數                                                                                        |
| **有 Project Brain 時**   | _(每個 Agent 啟動前，Brain 會自動注入相關知識)_<br>• NEXUS 看到：「ADR-001：我們選了 PostgreSQL，原因是...」<br>• SHIELD 看到：「⚠ 踩坑：Webhook 必須冪等保護」<br>• BYTE 看到：「📋 規則：金額以 cent 整數儲存」 |

### 更精確的運作定義

- **可以獨立運作**：不初始化 Brain 也能用 `ship`，Agent 照樣工作，只是沒有記憶。
- **加在一起才完整**：Brain 是 SYNTHEX 的長期記憶層，讓 AI 越用越懂你的專案。
- **Brain 不依賴 SYNTHEX**：你也可以只用 Brain 做知識管理，不跑任何 Agent。

---

## 🚀 快速開始與兩個部分的用途 (Getting Started)

## 兩個部分的用途

### 第一部分：`synthex-ai-studio/` — 放在你的工具目錄

作為全域指令營運你的虛擬開發公司。

```bash
mv synthex-ai-studio ~/tools/
cd ~/tools/synthex-ai-studio

pip install -r requirements.txt
export ANTHROPIC_API_KEY="your-key"

# 設定你的專案目錄
python synthex.py workdir ~/projects/my-app

# 需求模糊時
python synthex.py discover "我想做一個..."

# 需求清楚時，一氣呵成
python synthex.py ship "電商平台：商品瀏覽、購物車、Stripe 結帳..."
```

### 第二部分：`project-template/` — 複製到每個專案

讓 IDE 內的 Claude 繼承 SYNTHEX 的架構記憶與角色規範。

```bash
# 每次開新專案，把這個目錄的內容複製進去
cp -r project-template/CLAUDE.md  ~/projects/my-app/
cp -r project-template/agents     ~/projects/my-app/

# 然後開啟 Claude Code
cd ~/projects/my-app
claude

# 在 Claude Code 裡輸入
/ship 你的需求
```

---

## 🔄 標準工作流程 (Workflow)

```
Step 1  需求模糊？
        python synthex.py discover "模糊想法"
        → 產出 docs/DISCOVER.md + 建議的 /ship 指令

Step 2  確認需求，執行 /ship
        python synthex.py ship "完整需求描述"
        → 產出程式碼骨架 + PRD + 架構文件

Step 3  開啟 Claude Code 精修
        cd ~/projects/my-app && claude
        → 帶著 docs/ 裡的文件，用角色指令繼續開發
        → "@BYTE 根據 docs/PRD.md 完善表單驗證"
```

---

## ⚙️ 需要填寫的地方 (Customization)

當你完成初始化後，請打開 `project-template/CLAUDE.md` 中的「專案資訊」區塊進行客製化填寫：

```
目錄結構  ← 第一次 /ship 後，把產出的目錄結構貼進來
常用指令  ← 補充你的 DB migration 等自訂指令
環境變數  ← 第一次 /ship 後，把 .env.local.example 的 key 列表貼進來
禁止事項  ← 你的專案特有限制
```

品牌和技術由角色決定（已在 CLAUDE.md 設定），這四個由你補充。

---

## Project Brain — 兩種使用場景

Project Brain 是 SYNTHEX AI STUDIO 的長期記憶系統，已內建在 `synthex.py` 裡。

## Project Brain × SYNTHEX — 兩種使用場景

> **核心原則**
>
> - **自動觸發**：Context 注入（每次 `ship`/`feature`/`fix` 都自動）、Git Hook 學習（每次 `git commit` 都自動）
> - **手動觸發**：`brain init` 或 `brain scan`（只需一次）、`brain add`（選填補充）

---

### 場景一：全新專案

從零開始，同時建立開發系統和長期記憶。

**完整流程：**

```
[你] python synthex.py brain init          ← 手動（僅一次）
      │
      │  建立 .brain/、設定 Git Hook、建立知識圖譜
      ▼
[你] python synthex.py discover "模糊想法"  ← 手動
      │
      │  (自動) Brain.get_context() 注入已知背景知識
      │  6 個 Agent 深挖需求，產出 docs/DISCOVER_FINAL.md
      ▼
[你] python synthex.py ship "完整需求" --budget 5.0  ← 手動
      │
      │  Phase 4 NEXUS 架構設計
      │    (自動) Brain 注入相關踩坑 + ADR
      │  Phase 9+10 BYTE+STACK 實作
      │    (自動) Brain 注入業務規則 + 依賴關係
      │  Phase 11 PROBE+TRACE 測試
      │    (自動) Brain 注入已知的邊界條件
      ▼
[你] git commit -m "feat: 完成登入功能"      ← 正常 git 操作
      │
      │  (自動) Git Hook → Brain.learn_from_commit()
      │  Claude 分析 diff，提取決策 / 踩坑 / 規則
      │  存入知識圖譜（背景執行，不阻塞你）
      ▼
 知識圖譜自動成長（每次 commit 都在積累）
      ↻ 下次工作，Brain 知道得更多
```

**時間線：**

| 時間      | commit 數 | 知識節點 | Brain 效果                 |
| --------- | --------- | -------- | -------------------------- |
| 第 1 週   | ~20       | ~5       | 基礎結構知識               |
| 第 1 個月 | ~100      | ~30      | 開始有決策記錄             |
| 第 3 個月 | ~300      | ~100     | 踩坑記錄豐富，不再重蹈覆轍 |
| 第 1 年   | ~1000     | ~300     | 完整機構記憶               |

---

### 場景二：現有專案（接手 / 新功能 / 修復 / 重構）

接手沒有記錄的舊專案，或在現有專案上持續開發。

**接手舊專案（只需一次）：**

```
[你] python synthex.py brain scan           ← 手動（僅一次，約 3-10 分鐘）
      │
      │  Step 1：分析目錄結構，建立組件節點
      │  Step 2：分析 Git 歷史（最近 200 commits）
      │          Claude 提取每個 commit 的決策知識
      │  Step 3：掃描「熱點」程式碼（修改最頻繁的檔案）
      │          提取 TODO/FIXME/HACK 注釋
      │  Step 4：整合現有 README / docs / ADR
      │  Step 5：產出 .brain/SCAN_REPORT.md
      ▼
 知識圖譜重建完成，可以立即使用
```

**日常開發（完全自動）：**

```
[你] python synthex.py feature "新增訂單退款功能"  ← 手動
      │
      │  (自動) Brain.get_context("新增訂單退款功能", "src/order/")
      │          搜尋 → 「支付模組有重複扣款的踩坑記錄」
      │          搜尋 → 「金額必須以分為單位儲存（業務規則）」
      │          搜尋 → 「ADR-042：冪等性設計」
      │          → 全部注入 Agent 的 Prompt 前端
      ▼
 AI Agent 帶著完整記憶工作
 知道之前踩過什麼坑，不會重複犯錯
      │
      ▼
[你] git commit -m "feat: 加入退款 API"      ← 正常 git 操作
      │
      │  (自動) Git Hook 學習新知識
      ▼
 知識圖譜持續成長 ↻
```

**四種操作的觸發方式：**

| 操作     | 命令                            | Brain 介入方式              |
| -------- | ------------------------------- | --------------------------- |
| 新增功能 | `synthex.py feature "描述"`     | 自動注入相關踩坑 + 依賴關係 |
| 修復 Bug | `synthex.py fix "bug 描述"`     | 自動注入歷史相似 bug 的解法 |
| 除錯     | `synthex.py investigate "問題"` | 自動注入可能的根本原因      |
| 重構     | `synthex.py ship "重構需求"`    | 自動注入完整架構脈絡        |

---

### 哪些是自動的，哪些是手動的

```
自動（完全不需要手動觸發）：
  ✓ git commit 後，知識自動積累（Git Hook）
  ✓ 每次 AI 工作前，Context 自動注入（orchestrator 內建）
  ✓ 知識圖譜自動成長

手動（只需一次）：
  ✓ brain init — 新專案初始化
  ✓ brain scan — 舊專案考古掃描

選填（隨時補充）：
  ✓ brain add "知識" — 手動記錄重要決策
  ✓ brain status    — 查看目前記憶狀態
  ✓ brain context   — 測試 Context 注入效果
```

---

_SYNTHEX AI STUDIO · 24 Agents · 18 Tools · Built with Claude_

> "The future of software engineering isn't writing code. It's managing fleets of AI engineers who write code."█

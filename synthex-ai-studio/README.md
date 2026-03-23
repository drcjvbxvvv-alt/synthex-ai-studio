# SYNTHEX AI STUDIO

全 AI 驅動的軟體開發公司。24 位 Agent，7 個部門，透過命令行讓整個公司為你工作。

---

## 目錄結構

```
synthex-ai-studio/          ← 工具本體（建議放在 ~/tools/）
│
├── synthex.py              ← 主入口，所有命令從這裡執行
├── requirements.txt
├── README.md
├── CLAUDE.md               ← 複製到你的專案根目錄，給 Claude Code 使用
│
├── core/
│   ├── base_agent.py       ← Agent 基底（對話 + Agentic 兩種模式）
│   ├── orchestrator.py     ← ARIA 智能路由
│   ├── tools.py            ← 基礎工具（讀寫檔案、執行命令）
│   ├── web_tools.py        ← 網頁開發工具（npm、git、框架偵測）
│   └── web_orchestrator.py ← /discover、/ship 完整流水線
│
├── agents/
│   └── all_agents.py       ← 全部 24 位 Agent 定義
│
└── memory/                 ← 自動產生，Agent 的跨 session 對話記憶
```

**CLAUDE.md 放在每個專案的根目錄，不是工具本體裡：**

```
~/tools/synthex-ai-studio/   ← 工具本體

~/projects/my-app/
├── CLAUDE.md                ← 複製到這裡，Claude Code 自動讀取
├── src/
└── package.json
```

---

## 安裝

```bash
# 1. 放到你喜歡的位置
mv synthex-ai-studio ~/tools/
cd ~/tools/synthex-ai-studio

# 2. 安裝依賴（只有一個）
pip install -r requirements.txt

# 3. 設定 API Key（加到 ~/.zshrc 永久生效）
export ANTHROPIC_API_KEY="your-anthropic-api-key"

# 4. 設定你的專案目錄（一次設定，之後不用每次指定）
python synthex.py workdir ~/projects/my-app

# 5. 確認正常
python synthex.py list
```

---

## 兩種使用方式

### 方式 A：Synthex CLI（本工具）

你在 Terminal 執行命令，Agent 透過 API 操作你的專案檔案。

```bash
python synthex.py <命令> <參數>
```

### 方式 B：Claude Code + CLAUDE.md

把 `CLAUDE.md` 複製到你的專案，在 Claude Code 裡直接用角色名稱工作。

```bash
cp ~/tools/synthex-ai-studio/CLAUDE.md ~/projects/my-app/
cd ~/projects/my-app
claude
# 然後在 Claude Code 裡：@BYTE 建立 DataTable 組件
```

**兩種方式都是同一個 Claude 扮演不同角色，差別在於：**
Synthex CLI 自動串接多個角色，Claude Code 讓你有更完整的 context 和互動控制。

---

## 完整命令列表

### 需求分析（從這裡開始）

| 命令 | 說明 |
|------|------|
| `discover <想法>` | **需求模糊時用這個**。6 個角色深挖需求，產出需求書和 /ship 指令 |
| `agent ECHO <任務>` | 讓 ECHO 分析需求、撰寫 PRD |
| `agent LUMI <任務>` | 讓 LUMI 做產品策略和用戶研究 |

### 開發執行

| 命令 | 說明 |
|------|------|
| `ship <需求>` | **一氣呵成**。11 Phase 自動流水線，從範疇確認到 git commit |
| `feature <描述>` | 在現有專案新增一個功能 |
| `fixbug <描述>` | 診斷並修復錯誤 |
| `codereview` | PROBE + SHIELD 全面代碼審查 |

### 對話與規劃

| 命令 | 說明 |
|------|------|
| `ask <任務>` | 智能路由，自動選最合適的 Agent（對話模式） |
| `agent <名稱> <任務>` | 直接指派特定 Agent（對話模式） |
| `chat <名稱>` | 與 Agent 持續對話，保留記憶 |
| `project <說明>` | 多部門專案規劃，ARIA 主導 |
| `dept <部門> <任務>` | 讓整個部門一起分析 |
| `review <名稱>` | 貼入內容讓 Agent 審查 |

### Agentic 執行（Agent 直接操作你的檔案）

| 命令 | 說明 |
|------|------|
| `do <名稱> <任務>` | Agent 讀寫檔案、執行命令，完成任務 |
| `run <名稱> <任務>` | 同 `do` |
| `build <任務>` | 智能路由 + Agentic 執行 |
| `shell <名稱>` | Agentic 互動 Shell（最接近 Claude Code 體驗） |

### 工具

| 命令 | 說明 |
|------|------|
| `workdir <路徑>` | 設定預設工作目錄（永久儲存到 ~/.synthex_config.json） |
| `list` | 列出所有 24 位 Agent |
| `clear <名稱>` | 清除特定 Agent 的記憶 |

### 全域選項

```
--workdir <路徑>    覆蓋本次工作目錄
--yes              危險操作自動確認
```

---

## 需求模糊？用 /discover

這是你最常用到的起點。當你只有一個模糊的想法，還不知道要做什麼功能，先跑 `/discover`。

```bash
python synthex.py discover "我想做一個幫助自由工作者管理客戶和收款的工具"

python synthex.py discover "我想做一個台灣股票的 AI 分析平台"

python synthex.py discover "類似 Notion 但專門給工程師寫技術文件的工具"
```

**6 個角色依序分析你的想法：**

```
LUMI  — 你的用戶是誰？他們最痛的地方是什麼？現有替代方案的缺陷？
↓
ARIA  — 商業模式怎麼設計？MVP 怎麼定義？Go/No-Go 建議
↓
ECHO  — 具體功能清單（含假設標注）、優先排序（P0/P1/P2）、不做什麼
↓
NEXUS — 每個功能的技術複雜度、推薦技術棧、第三方服務費用
↓
SIGMA — 開發時間估算、月營運成本、關鍵里程碑
↓
ARIA  — 整合輸出完整需求書 + 可直接執行的 /ship 指令
```

**產出物：**
- `docs/DISCOVER.md` — 完整需求分析報告
- 一條具體的 `/ship` 指令，複製後直接執行

**執行流程：**
```bash
# Step 1: 挖掘需求
python synthex.py discover "你的模糊想法"

# Step 2: 讀 docs/DISCOVER.md，確認需求書符合你的意圖

# Step 3: 複製需求書裡建議的 /ship 指令執行
python synthex.py ship "（從 DISCOVER.md 複製的完整需求）"
```

---

## /ship — 從決策到實作一氣呵成

需求確認後（自己想清楚了，或跑過 `/discover`），用 `/ship` 完整執行。

```bash
python synthex.py ship "電商平台：
- 商品瀏覽（分類、搜尋、篩選）
- 購物車（本地儲存，不需登入）
- 結帳（Stripe，支援信用卡）
- 訂單管理（用戶可查看訂單狀態）
- 後台管理（上架商品、查看訂單）
技術：Next.js 14 + TypeScript + Tailwind + PostgreSQL + Prisma"
```

**11 Phase 自動流水線：**

```
Phase 1  — ARIA  — 任務接收與範疇確認
           輸出：任務確認報告（若有模糊之處，在此停下來問你）

Phase 2  — ECHO  — 需求分析與 PRD
           輸出：docs/PRD.md（功能清單、路由、資料模型、API、驗收標準）

Phase 3  — LUMI  — 產品驗證
           輸出：用戶旅程完整性確認（不通過則要求 ECHO 修改 PRD）

Phase 4  — NEXUS — 技術架構設計
           輸出：docs/ARCHITECTURE.md（技術選型、檔案計畫、實作順序）

Phase 5  — SIGMA — 可行性評估
           輸出：成本分析、風險評估（不可行則暫停）

Phase 6  — FORGE — 環境準備
           執行：建立目錄、安裝套件、建立 .env.local.example

Phase 7  — BYTE  — 前端實作
           執行：TypeScript 型別 → API 客戶端 → 組件 → 頁面 → 路由
           驗證：lint + typecheck 通過

Phase 8  — STACK — 後端實作
           執行：資料模型 → Service 層 → API 路由 → 中間件
           驗證：每個端點測試通過

Phase 9  — PROBE + TRACE — 測試
           執行：單元測試 + API 整合測試 + E2E 測試，全部必須通過

Phase 10 — SHIELD — 安全審查
           執行：OWASP 清單逐一確認，發現問題當場修復

Phase 11 — ARIA  — 交付總結
           執行：docs/DELIVERY.md + git commit
```

**重要說明：**

`/ship` 的交付品質是「可以 demo 的起點」，不是「直接上 production」。原因是每個 Phase 是獨立的 API 呼叫，Phase 7 的 BYTE 只看到被截斷的架構摘要，不是完整的 context。你大約需要再花 2-4 小時修復整合問題。

**如果要更高品質，改用 Claude Code + CLAUDE.md：**

```
# 在 Claude Code 裡，你帶著 DISCOVER.md 的需求書，一步步指揮
@ECHO 根據 docs/DISCOVER.md 的需求，產出完整 PRD
→ 確認 PRD 正確後
@NEXUS 設計架構
→ 確認架構後
@BYTE + @STACK 實作
```

這樣你在全程，每個角色都有完整的 context，交付品質明顯更高。

---

## 對話模式 vs Agentic 模式

### 對話模式（ask / agent / chat / project）

Claude 給你分析、建議、規格、代碼片段，**你自己決定要不要執行**。

```bash
# 適合：規劃、諮詢、技術評估、架構設計、PRD 撰寫
python synthex.py agent NEXUS "評估用 GraphQL 替換現有 REST API 的利弊"
python synthex.py agent SHIELD "列出這個 JWT 實作的安全問題"
```

### Agentic 模式（do / run / shell / ship / discover）

Claude **真實操作你的專案**：讀寫檔案、執行命令、安裝套件、提交 Git。

```bash
# 適合：實際開發、重構、建立設定、修 bug
python synthex.py do FORGE "建立 .github/workflows/ci.yml，包含 lint → test → build"
python synthex.py do SHIELD "掃描所有 API 端點，找出缺少授權檢查的路由並修復"
python synthex.py shell BYTE  # 開啟互動 Shell
```

---

## 使用場景範例

### 場景一：我有個模糊想法

```bash
# 1. 先挖掘需求
python synthex.py discover "我想幫台灣的小餐廳做一個點餐系統"

# 2. 讀 docs/DISCOVER.md，調整不符合你意圖的地方
# 3. 執行建議的 /ship 指令
python synthex.py ship "餐廳點餐系統：
QR code 掃碼點餐、購物車、送出訂單、廚房顯示看板、
結帳（現金為主，不需線上付款）、
管理後台（菜單管理、查看訂單）
Next.js + PostgreSQL，mobile first"
```

### 場景二：我知道要做什麼，需求很清楚

```bash
# 直接 /ship
python synthex.py ship "在現有專案新增 Google OAuth 登入，
使用 NextAuth.js，
登入後 redirect 到 /dashboard，
用戶資料（名稱、Email、頭像）存進 users 資料表"
```

### 場景三：現有專案新增功能

```bash
python synthex.py feature "新增用戶通知系統：
- 後端：WebSocket 推播 + 資料庫儲存通知記錄
- 前端：右上角鈴鐺 icon + 下拉列表 + 已讀/未讀狀態"
```

### 場景四：修 bug

```bash
python synthex.py fixbug "用戶登出後再登入，/dashboard 的資料還是顯示上一個用戶的"
```

### 場景五：請某個 Agent 專門做一件事

```bash
# 讓 NOVA 設計 AI 功能
python synthex.py agent NOVA "我想在股票分析平台加入 AI 解讀財報的功能，設計架構"

# 讓 PROBE 設計測試策略
python synthex.py agent PROBE "為用戶認證模組設計完整的測試計畫"

# 讓 MEMO 審查合規問題
python synthex.py agent MEMO "我們要收集用戶的瀏覽行為做廣告投放，有什麼隱私合規問題"

# 讓 SIGMA 做財務分析
python synthex.py agent SIGMA "估算這個 SaaS 平台需要多少用戶才能損益平衡"
```

### 場景六：Agentic Shell 持續工作

```bash
python synthex.py shell FLUX

# [FLUX] > 先幫我看一下現在的專案結構
# [FLUX] > 在 src/lib/ 建立一個統一的 API error handler
# [FLUX] > 把它套用到所有現有的 API 路由
# [FLUX] > 跑一下 lint，有問題就修
# [FLUX] > exit
```

### 場景七：搭配 Claude Code（推薦的高品質做法）

```bash
# 1. 用 Synthex 做規劃（快速產出文件）
python synthex.py discover "我的模糊想法"
python synthex.py agent NEXUS "根據 docs/DISCOVER.md 設計技術架構"

# 2. 把文件複製到專案，開啟 Claude Code
cp ~/tools/synthex-ai-studio/CLAUDE.md ~/projects/my-app/
cd ~/projects/my-app
claude

# 3. 在 Claude Code 裡帶著文件逐步開發（完整 context，高品質交付）
# "根據 docs/DISCOVER.md 和 docs/ARCHITECTURE.md，@BYTE 請實作登入頁面"
```

---

## 全體 24 位 Agent

### 🎯 高層管理

| Agent | 職位 | /ship 職責 | 其他能力 |
|-------|------|-----------|---------|
| **ARIA** | 執行長 CEO | Phase 1（範疇確認）+ Phase 11（交付） | 策略規劃、危機管理、跨部門協調 |
| **NEXUS** | 技術長 CTO | Phase 4（技術架構） | 系統設計、技術選型、架構評審 |
| **LUMI** | 產品長 CPO | Phase 3（產品驗證）+ /discover Step 1 | 產品策略、用戶研究、功能優先排序 |
| **SIGMA** | 財務長 CFO | Phase 5（可行性評估） | 財務建模、ROI 分析、成本優化 |

### ⚙️ 工程開發

| Agent | 職位 | /ship 職責 | 其他能力 |
|-------|------|-----------|---------|
| **BYTE** | 前端技術主管 | Phase 7（前端完整實作） | React/Next.js、效能優化、Design System |
| **STACK** | 後端技術主管 | Phase 8（後端完整實作） | API 設計、PostgreSQL、微服務 |
| **FLUX** | 全端工程師 | 補位（跨層級問題） | 快速原型、Docker、整合工作 |
| **KERN** | 系統工程師 | /perf 效能優化 | Linux 底層、效能調優、並發問題 |
| **RIFT** | 行動端工程師 | Phase 7 行動端 | React Native、iOS/Android |

### 💡 產品設計

| Agent | 職位 | /ship 職責 | 其他能力 |
|-------|------|-----------|---------|
| **SPARK** | UX 設計主管 | 用戶旅程輸入 | 可用性測試、資訊架構 |
| **PRISM** | UI 設計師 | 設計規格輸入 | 視覺設計、Design Token |
| **ECHO** | 商業分析師 | Phase 2（PRD 產出） | 需求分析、流程設計 |
| **VISTA** | 產品經理 | 任務分解、里程碑 | Sprint 規劃、Roadmap |

### 🧠 AI 與資料

| Agent | 職位 | /ship 職責 | 其他能力 |
|-------|------|-----------|---------|
| **NOVA** | ML 主管 | AI 功能架構設計 | LLM 微調、RAG 系統、MLOps |
| **QUANT** | 資料科學家 | 指標設計、A/B 測試方案 | 統計分析、預測建模 |
| **ATLAS** | 資料工程師 | Schema 設計輸入 | ETL Pipeline、Kafka |

### 🚀 基礎架構

| Agent | 職位 | /ship 職責 | 其他能力 |
|-------|------|-----------|---------|
| **FORGE** | DevOps 主管 | Phase 6（環境準備）+ Phase 11（部署設定） | Kubernetes、CI/CD、IaC |
| **SHIELD** | 資安工程師 | Phase 10（安全審查與修復） | OWASP、滲透測試、合規 |
| **RELAY** | 雲端架構師 | 雲端架構建議 | AWS/GCP/Azure、FinOps |

### 🔍 品質安全

| Agent | 職位 | /ship 職責 | 其他能力 |
|-------|------|-----------|---------|
| **PROBE** | QA 主管 | Phase 9a（測試策略） | 品質指標、UAT 管理 |
| **TRACE** | 自動化測試 | Phase 9b（測試執行） | Playwright、API 測試 |

### 📣 商務發展

| Agent | 職位 | /ship 職責 | 其他能力 |
|-------|------|-----------|---------|
| **PULSE** | 行銷主管 | 發布行銷包 | 內容行銷、SEO、成長策略 |
| **BRIDGE** | 業務主管 | 合作提案框架 | 企業銷售、契約談判 |
| **MEMO** | 法務合規 | 隱私合規檢查 | 合約審查、GDPR、個資法 |

---

## 可用工具（Agentic 模式）

工程、DevOps、QA 角色有全套工具；高層、商務角色只有讀取類工具。

### 基礎工具

| 工具 | 說明 |
|------|------|
| `read_file` | 讀取檔案（支援指定行範圍） |
| `write_file` | 寫入或追加（自動建立目錄） |
| `list_dir` | 樹狀列出目錄 |
| `run_command` | 執行 shell 命令（危險指令自動封鎖） |
| `search_files` | 全專案文字搜尋 |
| `move_file` | 移動或重命名 |
| `delete_file` | 刪除（操作前要求確認） |
| `get_project_info` | 偵測技術棧、統計檔案 |

### 網頁開發工具

| 工具 | 說明 |
|------|------|
| `npm_run` | 執行 npm/yarn/pnpm 腳本 |
| `install_package` | 安裝套件 |
| `git_run` | 執行 Git 指令 |
| `detect_framework` | 偵測框架、版本、建置工具 |
| `read_package_json` | 解析 package.json |
| `scaffold_project` | 建立 Next.js、Vite、FastAPI 等骨架 |
| `check_port` | 確認 port 是否被佔用 |
| `read_env` | 讀取 .env 的 key 清單（不顯示值） |
| `write_env` | 安全寫入環境變數 |
| `lint_and_typecheck` | ESLint + TypeScript 型別檢查 |

---

## 安全機制

- **危險命令封鎖**：`rm -rf /`、`curl | bash` 等指令直接封鎖
- **刪除前確認**：所有刪除操作預設要求確認，加 `--yes` 自動確認
- **Git 指令白名單**：只允許常見安全的 Git 指令
- **工作目錄隔離**：Agent 只在 `workdir` 指定的目錄內操作
- **環境變數保護**：`read_env` 只顯示 key 名稱，不顯示值

---

## 記憶機制

每個 Agent 的對話歷史存在 `memory/<agent_name>_memory.json`，保留最近 20 輪對話，跨 session 有效。

```bash
# 繼續上次的討論（NOVA 記得之前說過的）
python synthex.py chat NOVA

# 清除記憶重新開始
python synthex.py clear NOVA
```

---

## 進階設定

預設工作目錄存在 `~/.synthex_config.json`：

```json
{
  "workdir": "/Users/you/projects/my-app"
}
```

Agent 使用的模型為 `claude-opus-4-5`。如需更換（例如用 `claude-sonnet-4-6` 降低成本），修改 `core/base_agent.py` 的 `self.model`。

---

## 關於交付品質的誠實說明

`/ship` 的輸出是「可以 demo 的起點」，不是「直接上 production 的成品」。

| 方式 | 代碼能跑起來 | 需要人力修復 | 適合場景 |
|------|------------|------------|---------|
| `/discover` + `/ship` | 約 40-60% | 半天到一天 | 快速產出骨架，再人工精修 |
| Claude Code + CLAUDE.md | 約 60-70% | 2-4 小時 | 你全程在場，即時糾正 |
| 兩者結合 | 最高 | 最少 | 先用 Synthex 規劃，再用 Claude Code 實作 |

**推薦工作流程：**

```
1. python synthex.py discover "模糊想法"
   → 產出 docs/DISCOVER.md

2. 讀一遍需求書，調整不符合你意圖的地方

3. cp CLAUDE.md ~/projects/my-app/ && claude
   → 在 Claude Code 裡帶著 DISCOVER.md 逐步開發

4. 遇到需要跑整個流程的，再切回 /ship
```

---

*SYNTHEX AI STUDIO · 24 Agents · 18 Tools · Built with Claude*

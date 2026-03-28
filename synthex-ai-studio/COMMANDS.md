# SYNTHEX AI STUDIO — 命令完整參考

> 所有命令的詳細說明、參數和範例。

---

## 目錄

- [快速索引](#快速索引)
- [核心開發命令](#核心開發命令)
- [Agent 直接操作](#agent-直接操作)
- [Project Brain 命令](#project-brain-命令)
- [系統管理命令](#系統管理命令)
- [品質評估命令](#品質評估命令)
- [全域選項](#全域選項)

---

## 快速索引

| 命令 | 說明 | 適用場景 |
|------|------|---------|
| `ship "需求"` | 完整 12-Phase 開發流水線 | 新功能、完整專案 |
| `discover "想法"` | 深度需求分析（6 Agent 協作）| 模糊想法轉清晰需求 |
| `feature "描述"` | 新增功能（跳過需求 Phase）| 現有專案加功能 |
| `fix "問題"` | 修復 Bug | 已知問題修復 |
| `investigate "問題"` | 深度除錯分析 | 複雜 Bug、效能問題 |
| `agent NEXUS "任務"` | 讓特定 Agent 執行任務 | 架構設計、程式碼審查 |
| `ask ARIA "問題"` | 快速諮詢（不修改檔案）| 技術問題、規劃建議 |
| `brain init` | 初始化記憶系統 | 新專案第一次 |
| `brain scan` | 考古掃描舊專案 | 接手舊專案 |
| `brain context "任務"` | 查看三層記憶注入內容 | 除錯 Brain 輸出 |

---

## 核心開發命令

### `ship` — 完整開發流水線

```bash
python synthex.py ship "需求描述" [選項]
```

**說明：** 觸發完整的 12-Phase 流水線，從需求確認到交付。

| Phase | Agent | 職責 |
|-------|-------|------|
| 1 | ARIA | 任務確認、範疇釐清 |
| 2 | ECHO | 撰寫完整 PRD（含 AC）|
| 3 | LUMI | 產品驗證（JTBD、RICE）|
| 4 | NEXUS | 技術架構設計 |
| 5 | SIGMA | 可行性評估 |
| 6 | FORGE | 環境準備（CI/CD、監控）|
| 7 | SPARK | UX 設計（線框、流程）|
| 8 | PRISM | UI 設計系統（token、組件）|
| 9+10 | BYTE + STACK | 前後端並行實作 |
| 11 | PROBE + TRACE | 測試策略 + 執行 |
| 12 | SHIELD + ARIA | 安全審查 + 交付總結 |

**選項：**

```
--workdir PATH    工作目錄（預設：上次設定的目錄）
--budget FLOAT    最高花費上限，USD（例如 --budget 3.0）
--force-full      強制執行所有 Phase（忽略動態路由）
--resume          從上次中斷的 Phase 繼續（預設行為）
--auto-confirm    跳過所有人工確認提示（CI 環境用）
--smart-route     啟用動態路由（根據需求類型跳過不必要 Phase）
```

**範例：**

```bash
# 完整電商功能
python synthex.py ship "電商平台：商品瀏覽、購物車、Stripe 結帳、訂單管理"

# 設定預算限制
python synthex.py ship "重構認證系統" --budget 2.0

# 指定工作目錄
python synthex.py ship "新增退款功能" --workdir ~/projects/my-shop

# 中途中斷後繼續
python synthex.py ship "上次的需求" --resume

# CI/CD 環境（自動確認所有提示）
python synthex.py ship "需求" --auto-confirm --budget 5.0
```

---

### `discover` — 深度需求分析

```bash
python synthex.py discover "模糊想法" [選項]
```

**說明：** 6 個 Agent 協作深挖需求（ARIA + ECHO + LUMI + SIGMA + NEXUS + NOVA），產出完整的 `docs/DISCOVER_FINAL.md`，可以直接複製到 `ship` 命令。

**最適合：** 還不確定要做什麼的早期探索階段。

```bash
# 從模糊想法開始
python synthex.py discover "我想做一個幫台灣小餐廳管理訂單的 SaaS"
# → 30 分鐘後產出：競品分析、目標用戶、核心功能、技術選型建議

# 分析競品和市場
python synthex.py discover "想做一個 AI 簡歷優化工具，類似 Rezi"

# 探索技術可行性
python synthex.py discover "用 AI 自動生成 UI 組件的工具"
```

---

### `feature` — 新增功能

```bash
python synthex.py feature "功能描述" [選項]
```

**說明：** 針對現有專案新增功能。自動跳過需求分析 Phase（2、3），直接從架構設計開始，比 `ship` 更快。

**Project Brain 自動介入：** 查詢相關踩坑記錄、業務規則、依賴關係。

```bash
python synthex.py feature "新增訂單退款功能，支援全額和部分退款"
python synthex.py feature "加入 Google OAuth 登入，保留現有帳號密碼登入"
python synthex.py feature "在後台新增用戶行為分析儀表板"
```

---

### `fix` — 修復 Bug

```bash
python synthex.py fix "問題描述" [選項]
```

**說明：** 集中於 Phase 9+10+11（實作 + 測試），跳過設計 Phase，快速修復已知問題。

```bash
python synthex.py fix "支付金額計算在邊界情況下出現浮點數錯誤"
python synthex.py fix "用戶登出後 Token 未正確失效，可以繼續使用"
python synthex.py fix "首頁在 Safari 上的 CSS 排版跑版"
```

---

### `investigate` — 深度除錯

```bash
python synthex.py investigate "問題描述" [選項]
```

**說明：** 多角色協作診斷複雜問題，產出根本原因分析報告和修復建議。

```bash
python synthex.py investigate "系統在高峰期（晚上 7-9 點）API 延遲突然飆高到 3 秒"
python synthex.py investigate "每次部署後前 5 分鐘的錯誤率上升到 15%"
python synthex.py investigate "某些用戶反映購物車商品會隨機消失"
```

---

### `webdev` — 快速 Web 開發

```bash
python synthex.py webdev "描述" [選項]
```

**說明：** 針對 Web 前端開發優化的流水線，著重 UI/UX 和前端實作。

```bash
python synthex.py webdev "響應式登入頁面，支援 Google / GitHub OAuth"
python synthex.py webdev "管理後台的資料表格組件，含排序、過濾、分頁"
```

---

## Agent 直接操作

### `agent` — 讓特定 Agent 執行任務（Agentic 模式）

```bash
python synthex.py agent AGENT_NAME "任務描述" [選項]
```

**說明：** Agent 以 Agentic 模式執行——可以讀寫檔案、執行命令、多輪工具調用。適合需要實際操作的任務。

```bash
# 架構師審查現有程式碼
python synthex.py agent NEXUS "分析現有 API 設計，找出不一致的地方並提出重構建議"

# 安全掃描
python synthex.py agent SHIELD "全面審查所有 API 端點的授權邏輯，列出漏洞清單"

# 測試策略
python synthex.py agent PROBE "為用戶認證模組設計完整的測試策略，涵蓋單元、整合和 E2E"

# 資料工程
python synthex.py agent ATLAS "設計用戶行為事件的 dbt 數據模型，支援 Funnel 分析"

# 效能分析
python synthex.py agent KERN "分析 API 的慢查詢，找出 N+1 問題並提供優化方案"
```

---

### `ask` — 快速諮詢（Chat 模式）

```bash
python synthex.py ask AGENT_NAME "問題" [選項]
```

**說明：** 純對話模式，不修改任何檔案。適合技術諮詢、方案比較、規劃建議。

```bash
python synthex.py ask ARIA "這個需求應該優先做哪個功能？"
python synthex.py ask NEXUS "PostgreSQL 還是 MongoDB，我的場景更適合哪個？"
python synthex.py ask SHIELD "JWT vs Session，各自的安全考量是什麼？"
python synthex.py ask NOVA "這個 RAG pipeline 有什麼改進空間？"
python synthex.py ask SIGMA "這個功能要多少開發成本，值得做嗎？"
```

---

### `do` — 直接執行任務（`agent` 的別名）

```bash
python synthex.py do AGENT_NAME "任務"
```

與 `agent` 相同，更短的別名。

---

### `chat` — 互動式對話

```bash
python synthex.py chat AGENT_NAME [--workdir PATH]
```

**說明：** 進入與指定 Agent 的持續對話模式，輸入 `quit` 退出。

```bash
python synthex.py chat NEXUS
# → 進入與 NEXUS 的對話，可以多輪討論架構問題
```

---

### `review` — 程式碼審查

```bash
python synthex.py review [AGENT_NAME] [選項]
```

**說明：** 讓 Agent 審查當前工作目錄的程式碼，產出審查報告。

```bash
python synthex.py review              # NEXUS 審查整體架構
python synthex.py review SHIELD       # SHIELD 進行安全審查
python synthex.py review BYTE         # BYTE 審查前端程式碼品質
```

---

### `dept` — 部門命令

```bash
python synthex.py dept DEPT_NAME "任務"
```

讓整個部門協作處理任務。

| 部門 | Agent 成員 | 適合任務 |
|------|-----------|---------|
| engineering | NEXUS, BYTE, STACK, FLUX, KERN, RIFT | 技術實作 |
| design | SPARK, PRISM | UX/UI 設計 |
| qa | PROBE, TRACE | 測試品質 |
| security | SHIELD, MEMO | 安全合規 |
| data | NOVA, QUANT, ATLAS | 資料分析 |
| infra | FORGE, RELAY | 部署維運 |
| biz | ECHO, VISTA, BRIDGE | 商業規劃 |
| hardware | BOLT, VOLT, WIRE, ATOM | 嵌入式系統 |

```bash
python synthex.py dept security "全面審計系統的資安狀況"
python synthex.py dept data "分析用戶留存率下降的原因"
```

---

## Project Brain 命令

### `brain init` — 初始化記憶系統

```bash
python synthex.py brain init [--name "專案名稱"]
```

建立 `.brain/` 目錄結構，設定 Git Hook，初始化三層記憶庫。每個新專案執行一次。

---

### `brain scan` — 考古掃描

```bash
python synthex.py brain scan
```

分析現有專案的 Git 歷史、程式碼文件、ADR 文件，重建知識圖譜。接手舊專案時使用，約需 3-10 分鐘。

---

### `brain context` — 測試 Context 注入

```bash
python synthex.py brain context "任務描述" [--file 當前檔案路徑]
```

顯示三層記憶系統會為這個任務注入哪些知識，用於除錯 Brain 輸出。

```bash
python synthex.py brain context "修復支付金額計算"
# 輸出：
# ## ⚡ 工作記憶（L1·本次任務）
# ...
# ## 🕰 時序決策（L2·Graphiti）
# ...
# ## 📚 語義知識（L3·Project Brain）
# ...
```

---

### `brain learn` — 手動學習

```bash
python synthex.py brain learn [--commit HASH]
```

從指定的 git commit 學習（預設 HEAD）。通常由 Git Hook 自動觸發，不需要手動執行。

---

### `brain status` — 查看狀態

```bash
python synthex.py brain status
```

顯示三層記憶系統的當前狀態：節點數量、信心分布、Graphiti 連線狀態。

---

### `brain add` — 手動加入知識

```bash
python synthex.py brain add "標題" --content "詳細說明" --kind Pitfall|Decision|Rule|ADR --tags tag1 tag2
```

手動記錄重要知識到 L2 + L3。

```bash
python synthex.py brain add "JWT RS256 密鑰格式" \
  --content "JWT RS256 必須使用 PKCS#8 格式的私鑰，PKCS#1 格式會驗簽失敗" \
  --kind Pitfall \
  --tags jwt security auth

python synthex.py brain add "金額以分儲存" \
  --content "所有金額一律以整數分（cent）儲存，顯示時除以 100" \
  --kind Rule \
  --tags payment amount
```

---

### `brain export` — 匯出圖譜

```bash
python synthex.py brain export
```

產生 Mermaid 格式的知識圖譜視覺化（輸出到 `docs/KNOWLEDGE_GRAPH.md`）。

---

### `brain validate` — 自主知識驗證（v4.0）

```bash
python synthex.py brain validate [--max-api-calls 20] [--dry-run]
```

AI 自動審查 L3 知識圖譜中的每筆知識是否仍然準確。

```bash
# 完整驗證（最多 20 次 API 呼叫）
python synthex.py brain validate

# 只報告，不更新
python synthex.py brain validate --dry-run

# 節省費用（只做本地規則和程式碼比對）
python synthex.py brain validate --max-api-calls 0
```

---

### `brain distill` — 知識蒸餾（v4.0）

```bash
python synthex.py brain distill [--layers context,prompts,lora]
```

把知識庫壓縮為可攜帶格式：

- `context`：生成 `SYNTHEX_KNOWLEDGE.md`（任何 LLM 可讀）
- `prompts`：為每個 Agent 角色生成 system prompt 片段
- `lora`：生成 LoRA 訓練數據（JSONL 格式）

---

### `brain share` — 匿名分享知識（v4.0）

```bash
python synthex.py brain share "標題" --content "內容" --kind Pitfall|Rule --visibility team|public
```

匿名化後分享到跨組織知識聯邦（差分隱私保護）。

---

## 系統管理命令

### `workdir` — 設定工作目錄

```bash
python synthex.py workdir /path/to/project
```

永久記住工作目錄（儲存在 `~/.synthex/config.json`）。

---

### `list` — 列出 Agent

```bash
python synthex.py list [--dept DEPT_NAME]
```

列出所有 28 個 Agent 和它們的部門。

---

### `clear` — 清除對話歷史

```bash
python synthex.py clear AGENT_NAME
```

清除指定 Agent 的對話歷史（`memory/` 目錄）。

---

### `retro` — 回顧分析

```bash
python synthex.py retro [--days 7]
```

分析最近 N 天的開發活動，產出回顧報告（什麼做得好、哪裡可以改進）。

---

### `qa-browser` — 瀏覽器 QA

```bash
python synthex.py qa-browser --url http://localhost:3000 [--agent TRACE]
```

讓 TRACE Agent 對運行中的 Web 應用進行瀏覽器自動化測試。

---

## 品質評估命令

```bash
# 執行測試套件
python -m core.evals run --suite prd_quality
python -m core.evals run --suite security_quality
python -m core.evals run --suite code_quality
python -m core.evals run --suite architecture_quality

# 只對特定 Agent 跑
python -m core.evals run --suite prd_quality --agent ECHO

# 不實際呼叫 API（測試配置）
python -m core.evals run --suite prd_quality --dry-run

# 比較兩次執行（偵測品質回退）
python -m core.evals compare --baseline abc12345 --current def67890
```

---

## 全域選項

以下選項適用於所有命令：

```
--workdir PATH     覆蓋工作目錄
--budget FLOAT     最高花費上限（USD）
--auto-confirm     跳過所有人工確認提示
--debug            顯示詳細的 API 呼叫日誌
```

---

## brain.py 獨立 CLI（不需要 SYNTHEX）

`brain.py` 是 Project Brain 的獨立入口點，指令更簡短，完全不依賴 SYNTHEX。

### 快速對照

| SYNTHEX 舊命令 | brain.py 新命令 | 說明 |
|----------------|----------------|------|
| `python synthex.py brain init` | `python brain.py init` | 初始化 |
| `python synthex.py brain status` | `python brain.py status` | 查看狀態 |
| `python synthex.py brain scan` | `python brain.py scan` | 考古掃描 |
| `python synthex.py brain add --title ...` | `python brain.py add --title ...` | 加入知識 |
| `python synthex.py brain distill` | `python brain.py distill` | 知識蒸餾 |
| `python synthex.py brain validate` | `python brain.py validate` | 知識驗證 |
| `python synthex.py brain webui` | `python brain.py webui` | Web UI |
| _(無)_ | `python brain.py serve` | OpenAI 相容 API |
| _(無)_ | `python brain.py export-rules` | 匯出到 LLM 規則文件 |

### brain.py 完整命令

```bash
# 初始化
python brain.py init [--workdir .] [--name "專案名稱"]

# 狀態
python brain.py status [--workdir .]

# 知識管理
python brain.py add --title "標題" --content "內容" --kind Pitfall [--tags tag1 tag2]
  # --kind 選項：Decision / Pitfall / Rule / ADR / Component
python brain.py scan   [--workdir .]   # AI 掃描 git 歷史（需要 ANTHROPIC_API_KEY）
python brain.py learn  [--commit HEAD] # 從指定 commit 學習

# 查詢
python brain.py context "實作支付退款功能"   # 查詢相關知識注入

# 蒸餾與匯出
python brain.py distill [--layers context prompts lora]
python brain.py export  # 匯出 Mermaid 圖譜

# 匯出到各種 LLM 工具
python brain.py export-rules --target cursorrules    # → .cursorrules（Cursor）
python brain.py export-rules --target claude         # → CLAUDE.md（Claude Code）
python brain.py export-rules --target system-prompt  # → 通用 Markdown
python brain.py export-rules --target openai-compat  # → JSON messages 格式

# API Server（OpenAI 相容）
python brain.py serve [--port 7891]
# 端點：
#   GET  /health                  服務健康
#   GET  /v1/knowledge            完整知識摘要（for system prompt）
#   GET  /v1/context?q=<任務>     精準知識查詢
#   POST /v1/messages             OpenAI 相容，自動注入知識
#   POST /v1/add                  新增知識（REST 方式）
#   GET  /v1/stats                知識庫統計

# 知識驗證
python brain.py validate [--max-api-calls 20] [--dry-run]

# 可視化
python brain.py webui [--port 7890]  # → http://localhost:7890
```

### 環境變數（省略 --workdir）

```bash
export BRAIN_WORKDIR=/your/project      # 預設工作目錄
export GRAPHITI_URL=redis://localhost:6379   # L2 FalkorDB
export ANTHROPIC_API_KEY=sk-ant-...         # AI 功能必填
```

### 整合各種 LLM 工具

**Cursor（自動讀取）：**
```bash
python brain.py export-rules --target cursorrules
# Cursor 在每次對話自動讀取 .cursorrules 中的知識
```

**Claude Code：**
```bash
python brain.py export-rules --target claude
# 知識注入 CLAUDE.md，Claude Code 啟動時自動讀取
```

**ChatGPT / Gemini（手動貼上）：**
```bash
python brain.py export-rules --target system-prompt
# 複製 .brain/system-prompt.md 的內容
# 貼到 ChatGPT "Custom Instructions" 或對話開頭
```

**Ollama / LM Studio（API 查詢）：**
```bash
# 啟動 Brain API Server
python brain.py serve --port 7891

# 取得 system prompt 內容
curl http://localhost:7891/v1/knowledge

# 在 LM Studio 的 System Prompt 欄位貼入上述結果
```

**任何 OpenAI SDK（自動注入）：**
```python
from openai import OpenAI

# 把 base_url 指向 Brain Server
client = OpenAI(
    base_url="http://localhost:7891",
    api_key="brain"   # 任意字串
)

# 所有請求會自動注入相關知識到 system message
response = client.chat.completions.create(
    model="gpt-4o",   # 實際模型由你的 LLM 決定
    messages=[{"role": "user", "content": "實作支付退款功能"}]
)
```

---

## 環境變數

| 變數 | 說明 | 範例 |
|------|------|------|
| `ANTHROPIC_API_KEY` | API Key（必要）| `sk-ant-...` |
| `SYNTHEX_WORKDIR` | 預設工作目錄 | `/home/user/projects` |
| `SYNTHEX_BUDGET` | 預設預算上限 USD | `5.0` |
| `GRAPHITI_URL` | Graphiti DB 連線 | `redis://localhost:6379` |
| `BRAIN_WORKDIR` | MCP Server 的工作目錄 | `/your/project` |
| `ANTHROPIC_LOG` | API 日誌級別 | `info` / `debug` |

---

## Brain 記憶調用驗證

如何確認 LLM 工具真的讀到了 Brain 建立的記憶：

```bash
# 1. 查詢任務相關知識（秒出）
python brain.py context "實作支付退款"
# 有輸出 → 命中  / 空白 → 知識庫為空

# 2. 三層狀態確認
python brain.py status
# L1 讀寫驗證 ✓ → Memory Tool 正常
# L2 ✓ 已連接  → FalkorDB 連通
# L3 節點 N 個 → 語義知識有內容

# 3. API 精準測試（需先 brain serve）
# GET  /v1/context?q=JWT       → found: true/false
# POST /v1/messages            → knowledge_injected: true/false

# 4. 放置標記知識後詢問 LLM
python brain.py add --title "測試標記 BRAIN-VERIFY" --content "測試" --kind Rule
# 問任何 LLM：「你知道 BRAIN-VERIFY 嗎？」
# 能描述 = 接口正常 / 不知道 = 重新確認接口設定
```

| LLM 工具 | 接口 | 讀取層 | 驗證 |
|----------|------|--------|------|
| Cursor | `.cursorrules` | L3 | 問 Cursor「你知道 BRAIN-VERIFY 嗎？」|
| Claude Code | CLAUDE.md / MCP | L3+L2 | 同上 |
| ChatGPT / Gemini | System Prompt | L3 | 同上 |
| Ollama / LM Studio | brain serve | L3 | 回應含知識關鍵字 |
| OpenAI SDK | brain serve | L1+L2+L3 | `knowledge_injected: true` |

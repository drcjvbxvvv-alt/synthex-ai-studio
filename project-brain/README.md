# Project Brain

> **為 AI Agent 設計的工程記憶基礎設施。**
> 讓每次對話都能承接上一次的決策、規則與踩坑。

[![Version](https://img.shields.io/badge/version-v0.1.0-blue.svg)](https://github.com/your-org/project-brain/releases)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![MCP Compatible](https://img.shields.io/badge/MCP-compatible-purple.svg)](https://modelcontextprotocol.io/)
[![Zero Dependencies](https://img.shields.io/badge/runtime_deps-flask_only-brightgreen.svg)]()

---

## 問題

每次開啟新的 AI 對話，Agent 對你的專案一無所知。

你六個月前踩過 Stripe Webhook 冪等性的坑，修好了，寫了 commit，但下一次 Agent 幫你實作退款時，它不知道。它會以完全一樣的方式，再踩一次。

這不是 Agent 不夠聰明，而是它沒有記憶。

Project Brain 解決這個問題：在你的專案裡建立一個可被 Agent 查詢的長期記憶庫，把踩坑記錄、架構決策、工程規則，轉化成 Agent 每次對話都能讀取的知識。

```
你說：「幫我實作支付退款功能」
         ↓
Agent 查詢 Brain：有支付相關的踩坑嗎？
         ↓
Brain 回傳：Stripe Webhook 重複觸發，必須用 idempotency_key（confidence=0.9）
         ↓
Agent 帶著這個知識寫程式，不再踩坑
```

---

## 為什麼 AI 時代需要這個

### AI Agent 的 commit 比人類更值得提取

傳統知識管理工具的假設是「人類寫 commit，人類記錄決策」——commit message 品質參差不齊，知識提取雜訊高。

AI 時代翻轉了這個假設：

| | 人類 commit | AI Agent commit |
|---|---|---|
| 格式 | 隨意（"fix bug"、"wip"、"ok"）| 結構化（Conventional Commits：`feat:`、`fix:`、`refactor:`）|
| 意圖表達 | 往往隱含、省略 | 明確、完整，直接來自任務描述 |
| 一致性 | 因人而異 | 穩定，由 Prompt 決定風格 |
| 頻率 | 人工驅動，不定期 | 任務完成即 commit，高頻且系統化 |

**結論**：AI Agent 寫的 commit 是第一等的知識素材。Brain 的 git hook 在 AI coding 工作流中自動形成一個正向閉環：

```
Agent 完成任務 → 結構化 commit
                         ↓
              Brain 提取決策與踩坑
                         ↓
              下次 Agent 啟動時即知道
                         ↓
              Agent 不重複踩坑，寫更好的 commit
```

這個閉環在純人工協作中摩擦高、難以維持；在 Agent 工作流中**自然運轉，無需額外成本**。

---

## 設計理念

### 記憶是工程團隊的基礎設施

程式碼是資產，測試是安全網，記憶是讓兩者保持有效的土壤。

一個沒有記憶的開發流程，每一次引入 AI Agent 都等於引入一個第一天上班的工程師——聰明，但對這個專案一無所知。Project Brain 的目標，是讓 Agent 在每次對話開始時，都能以「老員工」的視角理解這個專案。

### 對抗遺忘，而非追求全知

Project Brain 不試圖記住一切，而是記住**值得記住的**：

- 踩過的坑（Pitfall）— 防止重蹈覆轍
- 做過的決策（Decision）— 理解為什麼事情是現在這個樣子
- 工程規則（Rule）— 讓 Agent 自動遵守隱性約定
- 架構記錄（ADR）— 保留重大選擇的脈絡

不記住：臨時筆記、一次性的任務、已完成的 TODO。

### 誠實的邊界

任何號稱「完美無缺」的系統都是在實驗室裡的玩具。Project Brain 在設計上對自己的邊界有明確的認知：

- 語意召回率上限約 75%（Ontology 是研究問題，不是工程問題）
- 只能記錄人類已意識到值得記錄的事
- 對「隱性知識」（你覺得理所當然而沒有寫下來的）無能為力

承認這些邊界，是走向真正有用的工具的開始。

---

## 工程哲學

### 1. 零依賴優先（Zero External Dependency by Default）

核心功能只依賴 Python 標準函式庫與 SQLite。不需要 Docker、不需要 Redis、不需要向量資料庫，安裝後立刻可用。

進階功能（向量語意搜尋、MCP Server、本地 LLM）以 optional dependency 形式提供，按需安裝。

```
brain setup   ← 一行指令，無需配置任何外部服務
```

### 2. 單一文件，備份即複製（Single File, Backup is Copy）

所有記憶存在 `.brain/brain.db`，一個標準 SQLite 文件。

備份方案：`cp .brain/brain.db .brain/brain.db.bak`
遷移方案：複製文件到新機器
版本控制：可選擇 git track，也可以 gitignore

不需要備份腳本，不需要 export/import 工具，不需要管理員介入。

### 3. 降級永遠可用（Graceful Degradation）

| 情境 | Brain 的行為 |
|------|-------------|
| 無 API Key | 跳過 LLM 提取，仍記錄 commit 基本資訊 |
| 無向量索引 | 降級為 FTS5 關鍵字搜尋 |
| MCP 連線失敗 | CLAUDE.md 提示 Agent 主動查詢 |
| 知識庫為空 | 回傳空字串，不阻擋 Agent 運作 |

Brain 的故障模式是「靜默降級」，而不是「阻斷流程」。

### 4. 信心分級，而非二元判斷（Confidence Spectrum）

知識不是「對」或「錯」，而是有不同程度的可信度：

| 來源 | 信心分數 | 意義 |
|------|---------|------|
| 人工驗證後加入 | 0.9 | 確認正確 |
| 人工直接加入 | 0.8 | 信任但未驗證 |
| Agent 自動發現 | 0.6 | 可能正確 |
| git commit 提取 | 0.5 | 一般品質 |
| fix/wip commit | 0.2 | 低品質，待淘汰 |

信心分數會隨時間衰減，被查詢越多的知識衰減越慢（因為使用頻率代表仍然有效）。

### 5. 人機協作，而非全自動（Human-in-the-Loop）

自動化降低摩擦，但不替代判斷。

`brain sync`（git hook）自動記錄每次 commit，提供原始素材。真正有價值的知識，仍然需要工程師主動用 `brain add` 確認和補充。這不是設計缺陷，是刻意的選擇——全自動提取的知識品質不足以直接信任。

---

## 工程思想

### 記憶的 Atkinson-Shiffrin 模型

Project Brain 的架構對應認知科學的多儲存記憶模型：

```
L1a  工作記憶（Working Memory）
     ↳ 當前任務的即時注意力
     ↳ 對話結束後自動清除
     ↳ 存儲：今日筆記、當前任務脈絡

L2   情節記憶（Episodic Memory）
     ↳ 「那次 JWT 事件是什麼時候？」
     ↳ 對應：git commit 歷史、事件序列
     ↳ 支援時光機查詢（temporal_query）

L3   語意記憶（Semantic Memory）
     ↳ 「JWT 必須用 RS256」— 不是事件，是規律
     ↳ 精煉自 L2 的長期知識
     ↳ 支援知識圖譜關係（PREVENTS / CAUSES / REQUIRES）
```

三層記憶各司其職，`get_context` 統一讀取並融合輸出。

### 知識衰減的多因子模型

知識不會永遠有效。Brain 使用七個因子計算每個知識節點的動態信心：

| 因子 | 效果 |
|------|------|
| F1 時間衰減 | 越舊的知識，信心越低（基礎日衰減率 0.003）|
| F2 技術版本落差 | 知識提到 React 16，現在是 React 18 → 懲罰 |
| F3 程式碼活動信號 | 相關檔案近 30 天有修改 → 加分 |
| F4 矛盾偵測 | 兩條知識互相矛盾 → 雙方懲罰 |
| F5 程式碼引用確認 | 知識中提到的類別仍存在於 codebase → 加分 |
| F7 使用頻率 | 被 Agent 查詢越多次 → 衰減越慢 |

信心低於 0.20 自動標記為過時。衰減不刪除知識，只降低可見度。

### 空間作用域隔離（Spatial Scoping）

不同模組的知識應該互不干擾：

```bash
brain add "Transaction Lock 規則" --scope payment_service
brain add "React Hook 規則"       --scope user_profile
```

查詢時自動過濾：Agent 在 `user_profile` 上下文查詢，不會看到 `payment_service` 的規則。未指定 scope 的知識歸屬 `global`，所有查詢都可見。

---

## 架構概覽

```
.brain/
├── brain.db              主記憶庫（SQLite）
│   ├── nodes             L3 語意記憶（Rule/Decision/Pitfall/ADR）
│   ├── edges             因果關係邊（PREVENTS/CAUSES/REQUIRES）
│   ├── episodes          L2 情節記憶（git commits）
│   ├── temporal_edges    時序關係（時光機查詢）
│   └── sessions          L1a 工作記憶（當前任務）
├── review_board.db       KRB 暫存區（自動提取的候選知識）
└── config.json           Brain 設定
```

```
┌──────────────────────────────────────────────────┐
│                   AI Agent                        │
│              (Claude / Cursor / 任何 MCP 工具)    │
└──────────────┬───────────────────────────────────┘
               │  MCP / REST API / Python SDK
┌──────────────▼───────────────────────────────────┐
│              Project Brain                        │
│                                                   │
│  ┌──────────┐  ┌──────────┐  ┌─────────────────┐ │
│  │ L1a      │  │ L2       │  │ L3              │ │
│  │ Working  │  │ Episodic │  │ Semantic        │ │
│  │ Memory   │  │ Memory   │  │ Memory          │ │
│  └──────────┘  └──────────┘  └─────────────────┘ │
│                      ↑                            │
│              DecayEngine（每 7 天）                │
└──────────────────────────────────────────────────┘
               ↑
    git hook（自動）+ brain add（手動）
```

---

## 快速開始

### 安裝

```bash
pip install project-brain
```

**進階安裝（含 MCP Server 與語意搜尋）：**

```bash
pip install "project-brain[mcp]"
```

### 初始化

```bash
cd /your/project
brain setup
```

`brain setup` 自動完成：
1. 建立 `.brain/brain.db`
2. 安裝 git `post-commit` hook（每次 commit 自動學習）
3. 偵測 Claude Code / Cursor 並輸出 MCP 設定範例

### 第一步：加入知識

```bash
# 快速模式
brain add "JWT 必須使用 RS256，使用 HS256 會在 load balancer 後驗證失敗"

# 完整模式
brain add \
  --title "Stripe Webhook 冪等性" \
  --content "重複觸發時必須用 idempotency_key，否則會雙扣款" \
  --kind Pitfall \
  --scope payment_service \
  --confidence 0.9
```

### 第二步：驗證可以查到

```bash
brain ask "JWT 設定"
brain ask "支付退款"
```

### 第三步：連接 Agent（Claude Code）

```json
// .claude/settings.json
{
  "mcpServers": {
    "project-brain": {
      "command": "python",
      "args": ["-m", "project_brain.mcp_server"],
      "env": {
        "BRAIN_WORKDIR": "/your/project"
      }
    }
  }
}
```

在 `.claude/CLAUDE.md` 加入：

```markdown
At the start of every task, call the `get_context` MCP tool with the task description.
If Brain returns nudges or warnings, treat them as hard constraints.
```

---

## CLI 命令參考

| 命令 | 說明 | 範例 |
|------|------|------|
| `brain setup` | 一鍵初始化 | `brain setup` |
| `brain add` | 加入知識（手動）| `brain add "規則" --kind Rule` |
| `brain ask` | 查詢知識 | `brain ask "JWT 怎麼設定"` |
| `brain status` | 記憶庫狀態 | `brain status` |
| `brain sync` | 從最新 commit 學習 | `brain sync --quiet` |
| `brain serve` | 啟動 REST API | `brain serve --port 7891` |
| `brain serve --mcp` | 啟動 MCP Server | `brain serve --mcp` |
| `brain webui` | D3.js 視覺化 | `brain webui --port 7890` |

### 知識類型（--kind）

| 類型 | 意義 | 使用場景 |
|------|------|---------|
| `Pitfall` | 踩坑記錄 | 曾經犯過的錯誤、隱藏的陷阱 |
| `Decision` | 架構決策 | 為什麼選 A 而不選 B |
| `Rule` | 工程規則 | 必須遵守的技術約定 |
| `ADR` | 架構決策記錄 | 正式的架構決策文件 |
| `Note` | 一般筆記 | 其他值得記住的資訊 |

---

## Agent 整合

### MCP（推薦，適用 Claude Code / Cursor）

```bash
brain serve --mcp
```

可用 MCP 工具：

| 工具 | 說明 |
|------|------|
| `get_context(task, current_file, scope)` | 取得任務相關知識（含因果鏈 + 主動警告）|
| `add_knowledge(title, content, kind, scope, confidence)` | Agent 寫入新知識 |
| `search_knowledge(query)` | 直接語意搜尋 |
| `temporal_query(at_time, git_branch)` | 時光機——讀取指定時間點的知識狀態 |
| `brain_status()` | 記憶庫統計 |

### Python SDK

```python
from project_brain import Brain

b = Brain("/your/project")

# 結構化查詢（推薦）
result = b.query("JWT 認證問題", scope="auth")
if result:
    print(f"找到 {result.source_count} 筆，信心 {result.confidence:.2f}")
    prompt = result.to_prompt() + "\n\nUser task: ..."

# 向後相容（回傳字串）
ctx = b.get_context("JWT 認證問題")
```

### REST API

```bash
brain serve --port 7891
```

```http
GET  /v1/context?q=JWT&scope=auth
POST /v1/add
     {"title": "JWT 規則", "content": "...", "kind": "Rule", "scope": "auth"}
GET  /v1/stats
GET  /health
```

---

## 自動學習（Git Hook）

`brain setup` 安裝 `post-commit` hook，每次 commit 自動記錄：

```bash
git commit -m "fix: validate JWT exp field to prevent token hijacking"
# → Brain 自動記錄 (confidence=0.5)
# → 下次 Agent 查詢 JWT，此記錄會出現
```

**AI Agent 的 commit 質量遠高於人類隨意的提交。** Conventional Commits 格式（`feat:`、`fix:`、`refactor:`）加上完整的任務描述，讓 Brain 的 LLM 提取器能準確識別決策類型，幾乎不需要人工校正。

**信心分數說明：**
- `fix:` / `feat:` / `refactor:` prefix → confidence 0.5
- `wip` / 無 prefix → confidence 0.2
- 人工 `brain add` → confidence 0.8（預設）
- 人工審核通過 KRB → confidence 0.9

---

## Memory Synthesizer（進階）

預設狀態下，`get_context` 回傳三層原始資料的拼接。啟用 Memory Synthesizer 後，由 LLM 將三層融合成一份精簡的「戰術摘要」：

```bash
export BRAIN_SYNTHESIZE=1
```

**不啟用（預設）：**
```
## L2 Episodic
- 3 months ago: switched JWT from HS256 to RS256

## L3 Semantic Rules
- JWT must use RS256
```

**啟用後：**
```
## 🧠 Brain Tactical Brief
• [WARNING] JWT must use RS256 — previously used HS256 in testing (corrected 3mo ago)
• [RULE] Validate exp field in every token handler
```

費用：每次 `get_context` 約一次 LLM call（haiku 約 $0.0002，Ollama 免費）。

---

## 環境變數

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `BRAIN_WORKDIR` | 當前目錄 | 專案目錄（省略 `--workdir`）|
| `ANTHROPIC_API_KEY` | — | Anthropic API（AI 提取功能）|
| `BRAIN_LLM_PROVIDER` | `anthropic` | `openai` 使用 Ollama / LM Studio |
| `BRAIN_LLM_BASE_URL` | `http://localhost:11434/v1` | 本地 LLM 端點 |
| `BRAIN_LLM_MODEL` | `claude-haiku-4-5-20251001` | 模型名稱 |
| `BRAIN_SYNTHESIZE` | `0` | `1` 啟用 Memory Synthesizer |
| `BRAIN_API_KEY` | — | `brain serve` 的 API 認證 |

### 本地 LLM（Ollama）

```bash
export BRAIN_LLM_PROVIDER=openai
export BRAIN_LLM_BASE_URL=http://localhost:11434/v1
export BRAIN_LLM_MODEL=llama3.2:3b
```

---

## 多專案支援

`brain` 自動從當前目錄往上搜尋 `.brain/`，類似 git 的 `.git/` 偵測邏輯：

```bash
cd ~/projects/payment-service
brain ask "退款邏輯"   # ← 使用 payment-service/.brain/

cd ~/projects/auth-service
brain ask "JWT 設定"   # ← 使用 auth-service/.brain/
```

每個專案擁有獨立的記憶庫，互不干擾。

---

## 學術定位與研究對比

### 理論基礎

Project Brain 的三層架構直接對應認知科學的 **Atkinson-Shiffrin 多儲存記憶模型**（1968），並參考 **CoALA: Cognitive Architectures for Language Agents**（arXiv:2309.02427，TMLR 2024）對 AI Agent 記憶的系統化分類框架。

### 與同期學術研究的對比

2026 年初，「從工程歷史自動提取結構化知識」成為熱門研究方向：

| 論文 | 核心貢獻 | Project Brain 的差異 |
|------|---------|---------------------|
| **Lore**（arXiv:2603.15566，2026/03）| 將 git commit message 重新設計為結構化知識協議 | Lore 改變寫法；Brain 從現有 commit 中提取，無需改變工作流 |
| **MemCoder**（arXiv:2603.13258，2026/03）| 從 commit history 提取 intent-to-code mapping | MemCoder 不分類；Brain 分類為 Pitfall/Decision/Rule，並接衰減管理 |
| **MemGovern**（arXiv:2601.06789，2026/01）| 從 GitHub Issues 提取 governed experience cards | MemGovern 的 quality gate 最接近 KRB；Brain 增加了 KG 持久化與衰減 |
| **Codified Context**（arXiv:2602.20478，2026/02）| 為複雜 codebase 設計階層化 Agent context 架構 | Codified Context 是靜態文件；Brain 是動態知識圖譜，有衰減與更新 |

### 核心技術差異化

以下三個技術組合在現有論文與開源系統中**均無直接先例**：

**1. 工程特化知識圖譜 Schema**

```
節點類型：Pitfall / Decision / Rule / ADR / Note
邊類型：  PREVENTS / CAUSES / REQUIRES / BLOCKS
```

現有系統（GraphRAG、Zep Graphiti）使用通用實體與關係。Project Brain 的 schema 專為「工程決策知識」設計，邊的語義（PREVENTS）直接映射因果推理，讓 Agent 在任務開始前即可得到預先推導的結論。

**2. 六因子 Git-Grounded 衰減公式**

```
信心 = F1(時間衰減) × F2(版本差距) × F3(git活動) × F4(矛盾懲罰) × F5(程式碼引用) + F7(查詢頻率)
```

- **F2（版本差距）**：知識提到 React 16，現在是 React 18 → 自動降分。無論 MemOS、MemoryBank、SAGE 均無此機制。
- **F3（git 活動反衰減）**：知識相關的程式碼近 30 天有 commit → 加分。知識的有效性由 git 歷史決定，而非 AI 自判。
- **F5（程式碼引用確認）**：grep 確認知識中提到的類別仍存在於 codebase → 加分。

這是「以 git 作為知識有效性真值來源」的設計哲學，在現有 AI 記憶研究中未見。

**3. 自動提取 → 審核閘道 → 知識圖譜 → 衰減管理的完整閉環**

```
git commit (Agent 寫)
      ↓ [post-commit hook]
 KnowledgeExtractor (LLM 分類)
      ↓
 KnowledgeReviewBoard (staging)
      ↓ [brain review approve]
 L3 KnowledgeGraph
      ↓ [weekly]
 DecayEngine (六因子重算)
```

MemGovern 有 quality gate，MemCoder 有 commit 提取，但沒有任何系統完成這條完整的閉環管線。

### 競爭對手功能矩陣

| 功能 | Project Brain | Mem0 | Zep/Graphiti | MemGPT/Letta | MemCoder | MemGovern |
|------|:---:|:---:|:---:|:---:|:---:|:---:|
| 工程特化 KG Schema | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| 多因子知識衰減（6+）| ✓ | 單維 | ✗ | ✗ | ✗ | ✗ |
| 版本差距衰減 (F2) | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| git 活動反衰減 (F3) | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| 程式碼引用確認 (F5) | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| git commit 知識提取 | ✓ | ✗ | ✗ | ✗ | ✓ | ✗ |
| 人工審核閘道 | ✓ KRB | ✗ | ✗ | ✗ | ✓ | ✓ |
| 主動風險提醒 (NudgeEngine) | ✓ 零成本 | ✗ | ✗ | ✗ | ✗ | ✗ |
| 條件失效監控 | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| 零外部依賴 | ✓ 純 SQLite | ✗ | 需 Redis | ✗ | ✗ | ✗ |
| Temporal Query | ✓ | ✗ | ✓（更完整）| ✗ | ✗ | ✗ |

---

## 已知限制與設計邊界

誠實地列出這個版本的邊界，是對使用者的基本尊重。

| 限制 | 說明 | 計劃 |
|------|------|------|
| 語意召回率 ~75% | FTS5 關鍵字搜尋對語意相近但用詞不同的查詢效果有限 | Phase 1：向量語意搜尋 |
| 三層記憶輸出可能重複 | L2 episode 與 L3 node 可能說同一件事 | Phase 4：自動建立 DERIVES_FROM 邊 |
| scope 需手動指定 | 忘記加 `--scope` 知識會變成全域污染 | Phase 5：從目錄自動推導 |
| 無法捕捉隱性知識 | 只能記錄已被意識到的決策，無法捕捉「不言而喻的約定」| 設計邊界，不修 |

---

## 目錄結構

```
project-brain/
├── project_brain/          核心套件
│   ├── brain_db.py         統一資料庫入口（BrainDB）
│   ├── graph.py            L3 知識圖譜（KnowledgeGraph）
│   ├── context.py          Context 組裝引擎
│   ├── engine.py           ProjectBrain 主引擎
│   ├── extractor.py        LLM 知識提取
│   ├── decay_engine.py     多因子知識衰減
│   ├── consolidation.py    L1a → L3 記憶整合
│   ├── memory_synthesizer.py  三層融合（opt-in）
│   ├── review_board.py     KRB 人工審查委員會
│   ├── nudge_engine.py     主動警告引擎
│   ├── session_store.py    L1a 工作記憶
│   ├── mcp_server.py       MCP Server
│   ├── api_server.py       REST API（Flask）
│   └── cli.py              CLI 入口
├── docs/
│   ├── BRAIN_MASTER.md     設計主文件（唯一事實來源）
│   └── BRAIN_INTEGRATION.md  整合指南
├── tests/
│   ├── unit/               單元測試
│   ├── integration/        整合測試
│   └── chaos/              壓力測試
└── pyproject.toml
```

---

## 安裝選項

```bash
# 最小安裝（核心功能）
pip install project-brain

# 含 MCP Server（Claude Code / Cursor）
pip install "project-brain[mcp]"

# 含 Anthropic SDK（AI 提取）
pip install "project-brain[anthropic]"

# 含語意去重
pip install "project-brain[dedup]"

# 完整安裝
pip install "project-brain[all]"
```

**系統需求：** Python 3.10+，無需外部服務

---

## 貢獻

詳見 [CONTRIBUTING.md](CONTRIBUTING.md)。

提交 issue 前，請先確認：
1. `brain status` 的輸出
2. Python 版本（`python --version`）
3. 重現步驟

核心設計問題、架構討論，請直接開 Discussion。

---

## 設計文件

| 文件 | 說明 |
|------|------|
| [docs/BRAIN_MASTER.md](docs/BRAIN_MASTER.md) | 唯一設計主文件：架構、缺陷清單、路線圖 |
| [docs/BRAIN_INTEGRATION.md](docs/BRAIN_INTEGRATION.md) | 整合指南（SDK / API / MCP 詳細說明）|
| [INSTALL.md](INSTALL.md) | 安裝與驗證步驟 |

---

## License

MIT License — 詳見 [LICENSE](LICENSE)

---

*v0.1.0 · Project Brain · 為 AI Agent 設計的工程記憶基礎設施*

*相關學術文獻：CoALA (arXiv:2309.02427) · MemCoder (arXiv:2603.13258) · MemGovern (arXiv:2601.06789) · Lore (arXiv:2603.15566)*

# Phase E — 團隊共享腦：技術規劃文件 v3.0

> **狀態**：待 Review
> **日期**：2026-04-27
> **基準版本**：v0.45.0（E-01 HTTP MCP Transport 已完成）
> **核心架構**：Brain MCP Server + 小龍蝦（OpenClaw）Agent + Telegram

---

## 目錄

1. [架構總覽](#1-架構總覽)
2. [Phase E 項目總覽](#2-phase-e-項目總覽)
3. [E-DEPLOY 部署與對接](#3-e-deploy-部署與對接)
4. [E-02 多用戶寫入安全](#4-e-02-多用戶寫入安全)
5. [E-VERIFY 連接驗證測試](#5-e-verify-連接驗證測試)
6. [E-03~E-06 後續項目](#6-e-03e-06-後續項目)
7. [實作順序與依賴](#7-實作順序與依賴)
8. [品質門檻](#8-品質門檻)

---

## 1. 架構總覽

### 1.1 部署拓撲

```
┌─── 公司實體機（同一台）──────────────────────────────────────────┐
│                                                                 │
│  ┌─────────────────────┐      ┌─────────────────────────────┐  │
│  │  小龍蝦 主 Agent      │      │  Brain MCP Server            │  │
│  │  (OpenClaw)          │      │  (project-brain)             │  │
│  │                      │      │                              │  │
│  │  - 已綁定 Telegram    │ MCP  │  - 22 個 MCP tools           │  │
│  │  - AI Agent 推理     │─────▶│  - brain.db（知識庫）          │  │
│  │  - 文件解析          │      │  - Auth + Rate Limit         │  │
│  │  - 知識提取          │      │  - 衰減/Pipeline/KRB         │  │
│  └──────────┬───────────┘      └──────────────────────────────┘  │
│             │                                                    │
│             │ Telegram API（往外連，不需開 port）                    │
│             ▼                                                    │
└─────────────────────────────────────────────────────────────────┘
              │
     ┌────────┴────────┐
     │   Telegram 群組   │
     │                  │
     │  同事 A（上傳文件）│
     │  同事 B（查詢知識）│
     │  同事 C（審查知識）│
     └─────────────────┘
```

### 1.2 職責分離

| 元件 | 負責 | 不負責 |
|------|------|--------|
| **小龍蝦 Agent** | Telegram 介面、AI 推理、文件解析、知識提取 | 知識儲存、搜尋、衰減 |
| **Brain MCP Server** | 知識儲存、FTS5 搜尋、向量搜尋、衰減、KRB 審查 | Telegram、文件解析、LLM 推理 |

### 1.3 資料流：文件上傳 → 知識入庫

```
同事上傳 auth-spec.md
         │
         ▼
小龍蝦（AI Agent）
  1. Telegram API 收到文件 → 下載到本地
  2. LLM 讀取文件內容
  3. LLM 提取知識點：
     - [Rule] JWT 必須用 RS256
     - [Decision] 選用 OAuth2
     - [Rule] Token 過期 15 分鐘
  4. 呼叫 Brain MCP tools：
     ┌──────────────────────────────────────────────────┐
     │ add_knowledge(                                   │
     │   title="JWT 必須用 RS256",                       │
     │   kind="Rule",                                   │
     │   content="多服務環境需使用非對稱簽名",              │
     │   confidence=0.85,                               │
     │   workdir="/path/to/project"                     │
     │ )                                                │
     │                                                  │
     │ add_knowledge(                                   │
     │   title="選用 OAuth2 而非自建 auth",               │
     │   kind="Decision",                               │
     │   content="團隊已有 OAuth2 經驗，減少開發成本",      │
     │   confidence=0.85,                               │
     │   workdir="/path/to/project"                     │
     │ )                                                │
     └──────────────────────────────────────────────────┘
  5. 回覆同事：「已從 auth-spec.md 提取 3 條知識」
```

### 1.4 資料流：同事查詢知識

```
同事：「JWT 怎麼設定？」
         │
         ▼
小龍蝦（AI Agent）
  1. LLM 判斷意圖 → 需要查詢知識庫
  2. 呼叫 Brain MCP tool：
     ┌───────────────────────────────────────┐
     │ get_context(                          │
     │   task="JWT 設定",                    │
     │   workdir="/path/to/project"          │
     │ )                                     │
     │ → 回傳：3 條相關知識（Rule + Pitfall） │
     └───────────────────────────────────────┘
  3. LLM 摘要回覆同事
```

### 1.5 MCP 連接方式

小龍蝦與 Brain 同機運行，有兩種連接方式：

| 方式 | 設定 | 延遲 | 適用 |
|------|------|------|------|
| **stdio**（推薦） | command + args | ~0ms | 同機，最簡單 |
| HTTP localhost | url: `http://localhost:3000/mcp` | ~1ms | 同機，需啟動 server |

#### stdio 連接（推薦）

小龍蝦的 MCP 設定：
```json
{
  "mcpServers": {
    "project-brain": {
      "command": "python",
      "args": ["-m", "project_brain.mcp_server", "--workdir", "/path/to/project"],
      "env": {
        "BRAIN_WORKDIR": "/path/to/project"
      }
    }
  }
}
```

#### HTTP 連接（備用，或未來遠端存取）

```bash
# 先啟動 Brain MCP Server
brain serve --mcp --auth-key $BRAIN_API_KEY --port 3000
```

小龍蝦的 MCP 設定：
```json
{
  "mcpServers": {
    "project-brain": {
      "url": "http://localhost:3000/mcp",
      "headers": {
        "Authorization": "Bearer ${BRAIN_API_KEY}"
      }
    }
  }
}
```

---

## 2. Phase E 項目總覽

| ID | 項目 | 優先 | 狀態 | 預估 | 說明 |
|----|------|------|------|------|------|
| E-01 | HTTP MCP Transport | — | **✅ v0.45.0** | — | Auth + RateLimit + CORS |
| **E-DEPLOY** | **部署與對接** | **P0** | **待做** | **4h** | **Brain 初始化 + 小龍蝦 MCP 設定** |
| **E-02** | **多用戶寫入安全** | **P1** | **待做** | **10h** | **並發安全 + author 歸屬** |
| **E-VERIFY** | **連接驗證測試** | **P1** | **待做** | **6h** | **22 個 MCP tools 端到端測試** |
| E-03 | Client Connect 疊加 | P3 | 規劃中 | — | overlay 本地+集中（需 VPN） |
| E-04 | Ingestion Pipeline | P3 | 規劃中 | — | CLI 批次匯入（可選） |
| E-05 | Push to Central | P3 | 規劃中 | — | 個人知識推送 |
| E-06 | 運維 Agent 整合 | P3 | 規劃中 | — | Admin dashboard |

**核心觀察**：小龍蝦（OpenClaw）已解決 Telegram 介面 + AI Agent 推理，Brain 只需要確保 MCP Server 穩定運作。Phase E 從「開發 Telegram Bot」變成「部署 + 對接 + 確保多用戶安全」。

---

## 3. E-DEPLOY 部署與對接

> **目標**：在公司實體機上讓 Brain MCP Server + 小龍蝦 跑通
> **預估**：4h

### 3.1 前提條件

| 項目 | 需求 |
|------|------|
| Python | ≥ 3.10 |
| 小龍蝦 | 已安裝、已綁定 Telegram、能呼叫 MCP |
| 磁碟 | brain.db 預估 ≤ 100MB（5000 nodes） |
| 網路 | 能往外連 Telegram API（出站 443） |

### 3.2 Brain 安裝與初始化

```bash
# 步驟 1：安裝 project-brain
pip install "project-brain[mcp]"

# 步驟 2：初始化知識庫
cd /path/to/company/project
brain setup
# → 建立 .brain/brain.db
# → 安裝 git post-commit hook（可選）

# 步驟 3：驗證安裝
brain health
# 預期：all [OK]

brain status
# 預期：顯示空知識庫統計
```

### 3.3 小龍蝦 MCP 設定

#### 方案 A：stdio 連接（推薦，同機）

在小龍蝦的 MCP 設定檔中加入：

```json
{
  "mcpServers": {
    "project-brain": {
      "command": "python",
      "args": [
        "-m", "project_brain.mcp_server",
        "--workdir", "/path/to/company/project"
      ]
    }
  }
}
```

**驗證**：小龍蝦啟動後，確認能呼叫 `brain_status` tool。

#### 方案 B：HTTP 連接（備用）

```bash
# 終端 1：啟動 Brain MCP Server
export BRAIN_API_KEY="your-secret-key-here"
brain serve --mcp --auth-key $BRAIN_API_KEY --port 3000

# 驗證 server 啟動
curl http://localhost:3000/health
# → {"status": "ok", "version": "0.45.0", "transport": "streamable-http"}
```

小龍蝦 MCP 設定：
```json
{
  "mcpServers": {
    "project-brain": {
      "url": "http://localhost:3000/mcp",
      "headers": {
        "Authorization": "Bearer your-secret-key-here"
      }
    }
  }
}
```

### 3.4 初始知識匯入

Brain 知識庫建好後，讓同事透過小龍蝦上傳公司文件：

```
同事 → Telegram 上傳 design-doc.md
        → 小龍蝦讀取 + LLM 提取知識
        → 呼叫 add_knowledge / batch_add_knowledge
        → brain.db 寫入

同事 → Telegram 上傳 postmortem-report.pdf
        → 小龍蝦讀取 + 提取 Pitfall
        → 呼叫 add_knowledge(kind="Pitfall", ...)
        → brain.db 寫入
```

Brain 不需要知道文件格式——小龍蝦負責解析，Brain 只負責存知識。

### 3.5 小龍蝦 System Prompt 建議

在小龍蝦的 system prompt 中加入 Brain 使用指引：

```markdown
## 知識庫整合

你連接了 Project Brain 知識庫（MCP Server）。

### 查詢知識
- 使用者問問題時，先呼叫 `get_context` 或 `search_knowledge` 查詢知識庫
- 如果有相關知識，引用知識回答並附上信心度
- 如果沒有相關知識，直接說「知識庫中沒有找到」

### 加入知識
- 使用者上傳文件時，提取知識點並呼叫 `add_knowledge`
- kind 分類：Rule（規則）、Decision（決策）、Pitfall（踩坑）、Note（筆記）
- confidence 設 0.85（來自文件的知識）

### 審查知識
- 使用者要求審查時，呼叫 `krb_pre_screen` 列出待審知識
- 核准/駁回後告知使用者結果

### 注意
- 所有 Brain MCP tool 都需要 workdir 參數，使用："/path/to/company/project"
- add_knowledge 的 source 參數填入使用者識別（例："telegram:@alice"）
```

### 3.6 實作步驟

| 步驟 | 內容 | 預估 |
|------|------|------|
| DEPLOY-1 | 在實體機安裝 project-brain + brain setup | 0.5h |
| DEPLOY-2 | 設定小龍蝦 MCP 連接（stdio 或 HTTP） | 1h |
| DEPLOY-3 | 驗證 `brain_status` tool 可呼叫 | 0.5h |
| DEPLOY-4 | 撰寫小龍蝦 system prompt（Brain 使用指引） | 1h |
| DEPLOY-5 | 首次文件上傳測試（上傳一份文件 → 知識入庫） | 0.5h |
| DEPLOY-6 | 撰寫部署文件（`docs/DEPLOY_GUIDE.md`） | 0.5h |

---

## 4. E-02 多用戶寫入安全

> **目標**：多位同事同時透過小龍蝦操作，不丟資料、可追溯
> **預估**：10h

### 4.1 問題分析

```
同事 A 上傳 auth-spec.md  ──▶ 小龍蝦 ──▶ add_knowledge() ──▶ brain.db
同事 B 上傳 deploy-guide.md ──▶ 小龍蝦 ──▶ add_knowledge() ──▶ brain.db
                                                               ▲
                                                          同時寫入？
```

**已有基礎**：
- A-09 `_execute_write()` 統一入口 + `threading.Lock` → 同進程內序列化
- SQLite WAL 模式 + `busy_timeout=3000` → 多進程安全
- CAS 樂觀鎖（A-07）→ 同 node 並發更新偵測

**需要補的**：
1. author 歸屬 — 從 MCP 呼叫追溯到是哪位同事加入的
2. 高並發驗證 — 確認 10+ 同時寫入不丟資料
3. 衝突偵測 — 兩人加入語意相似的知識時通知

### 4.2 設計

#### 4.2.1 author 歸屬

`add_knowledge` MCP tool 已有 `source` 參數，小龍蝦可以傳入使用者識別：

```python
# 小龍蝦呼叫 Brain MCP tool 時
add_knowledge(
    title="JWT 必須用 RS256",
    kind="Rule",
    source="telegram:@alice",    # ← 追溯到同事 A
    workdir="/path/to/project",
)
```

**需要做的**：
- 確認 `source` 欄位正確寫入 `nodes` 表
- `search_knowledge` 結果包含 `source` 欄位
- 新增 `author` 參數到 `search_knowledge`，可按 author 過濾

#### 4.2.2 並發寫入安全

```
MCP Server 收到 add_knowledge 請求
    │
    ▼
BrainServer.rate_check()         ← 限流
    │
    ▼
brain.add_knowledge()
    │
    ▼
graph.add_node()
    │
    ▼
brain_db._execute_write()        ← threading.Lock 序列化
    │
    ▼
SQLite WAL commit
```

同進程（stdio MCP）：`_execute_write` 的 Lock 保證序列化。
多進程（HTTP MCP，多 worker）：SQLite WAL + busy_timeout 保證安全。

**需要做的**：寫測試驗證，不需要改程式碼。

#### 4.2.3 語意衝突偵測

兩個同事可能加入語意相近的知識：
- 同事 A：「JWT 必須用 RS256」
- 同事 B：「JWT 簽名演算法用 RS256」

`add_knowledge` 呼叫後，Brain 內部已有 near-duplicate 偵測（Jaccard 相似度）。
若偵測到重複，`brain.db.emit("near_duplicate", {...})` 會記錄事件。

**需要做的**：
- 確認 near-duplicate 偵測在高頻寫入下正常運作
- 考慮是否需要在 MCP tool 回傳中提示「已有相似知識」

### 4.3 實作步驟

| 步驟 | 內容 | 產出 | 預估 |
|------|------|------|------|
| E02-1 | 確認 `source` 欄位在 `add_knowledge` → `nodes` 表寫入正確 | 驗證 + 修復（如有） | 1h |
| E02-2 | `search_knowledge` MCP tool 結果包含 `source` 欄位 | mcp_server.py 調整 | 1h |
| E02-3 | 新增 `author` 過濾參數到 `search_knowledge` | mcp_server.py + brain_db.py | 2h |
| E02-4 | 並發寫入測試：10 threads × 10 writes = 100 條 | test_multi_user_writes.py | 2h |
| E02-5 | 並發寫入測試：batch_add_knowledge 同時呼叫 | 同上 | 1h |
| E02-6 | near-duplicate 偵測在並發下的正確性 | 同上 | 1h |
| E02-7 | 文件更新：CHANGELOG + ROADMAP | docs | 1h |
| E02-8 | 版本升級 + 全量回歸 | pyproject.toml | 1h |

### 4.4 測試計劃

```
tests/unit/test_multi_user_writes.py

class TestAuthorAttribution:
    """author 歸屬追蹤"""

    def test_add_knowledge_records_source(self, tmp_path):
        """add_knowledge(source="telegram:@alice") → nodes.source 有值"""

    def test_search_results_include_source(self, tmp_path):
        """search_knowledge 結果的每個節點包含 source 欄位"""

    def test_search_filter_by_author(self, tmp_path):
        """search_knowledge(author="telegram:@alice") → 只回傳 alice 的知識"""

    def test_different_authors_coexist(self, tmp_path):
        """兩個 author 各加 5 條 → 共 10 條，各自可過濾"""

    def test_empty_source_defaults_to_manual(self, tmp_path):
        """未提供 source → 預設 "manual" """


class TestConcurrentWrites:
    """多用戶並發寫入安全"""

    def test_10_threads_10_writes_no_data_loss(self, tmp_path):
        """10 threads 各寫 10 條 → brain.db 有 100 條，0 丟失"""

    def test_concurrent_batch_add(self, tmp_path):
        """5 threads 各 batch_add 20 條 → 共 100 條"""

    def test_concurrent_add_and_search(self, tmp_path):
        """5 threads 寫入 + 5 threads 查詢 → 寫入全成功，查詢不 crash"""

    def test_concurrent_writes_all_have_correct_source(self, tmp_path):
        """並發寫入的每條知識 source 欄位正確（不會串到別的 author）"""


class TestNearDuplicateDetection:
    """語意衝突偵測"""

    def test_similar_titles_detected(self, tmp_path):
        """標題相似度 > 0.85 → emit near_duplicate 事件"""

    def test_different_titles_not_flagged(self, tmp_path):
        """標題完全不同 → 不觸發 near_duplicate"""

    def test_near_duplicate_under_concurrent_writes(self, tmp_path):
        """並發加入相似知識 → 偵測正常，不 crash"""
```

**預期測試數**：≥ 13 tests

### 4.5 驗收條件

- [ ] `add_knowledge(source="telegram:@alice")` → `nodes.source` = `"telegram:@alice"`
- [ ] `search_knowledge` 結果包含 `source` 欄位
- [ ] 10 threads × 10 writes = 100 條全部寫入（0 丟失）
- [ ] 並發寫入的 `source` 不會串到其他 author
- [ ] near-duplicate 偵測在並發下正常運作
- [ ] 全量回歸 0 regression

---

## 5. E-VERIFY 連接驗證測試

> **目標**：確認小龍蝦能正確呼叫所有 Brain MCP tools
> **預估**：6h

### 5.1 為什麼需要

Brain 的 22 個 MCP tools 是為 Claude Code（stdio）設計的。透過 HTTP transport 或被小龍蝦呼叫時，需要驗證：
- 參數傳遞正確（JSON 序列化/反序列化）
- 回傳值格式正確
- 錯誤處理正常（無效參數不 crash）
- 長文本不截斷

### 5.2 MCP Tools 清單與測試範圍

| # | Tool | 小龍蝦常用 | 測試重點 |
|---|------|-----------|---------|
| 1 | `get_context` | ✅ 高頻 | 回傳 Markdown 格式、空知識庫不 crash |
| 2 | `search_knowledge` | ✅ 高頻 | 回傳 list[dict]、limit 參數生效 |
| 3 | `add_knowledge` | ✅ 高頻 | source 寫入、kind 驗證、回傳 node_id |
| 4 | `batch_add_knowledge` | ✅ 高頻 | 50 條批次、部分失敗處理 |
| 5 | `brain_status` | ✅ 中頻 | 回傳完整統計 |
| 6 | `complete_task` | ✅ 中頻 | decisions/lessons/pitfalls 寫入 |
| 7 | `report_knowledge_outcome` | ✅ 中頻 | node_id 驗證、信心調整 |
| 8 | `krb_pre_screen` | ✅ 中頻 | 回傳待審列表 |
| 9 | `impact_analysis` | ○ 低頻 | component 不存在時 graceful |
| 10 | `temporal_query` | ○ 低頻 | 時間格式解析 |
| 11 | `mark_helpful` | ○ 低頻 | 正面/負面回饋 |
| 12 | `reasoning_chain` | ○ 低頻 | 空知識庫不 crash |
| 13 | `auto_resolve_knowledge` | ○ 低頻 | 需 LLM 時 graceful 降級 |
| 14 | `generate_questions` | ○ 低頻 | threshold 參數 |
| 15 | `answer_question` | ○ 低頻 | 需 LLM 時 graceful 降級 |
| 16 | `multi_brain_query` | ○ 低頻 | 額外 brain dir |
| 17 | `federation_sync` | ○ 低頻 | dry_run 模式 |

### 5.3 測試設計

每個高頻 tool 寫 3-5 個測試 case，低頻 tool 寫 1-2 個：

```
tests/integration/test_mcp_tools_e2e.py

class TestHighFrequencyTools:
    """小龍蝦最常呼叫的 tools"""

    # ── get_context ──
    def test_get_context_returns_string(self, brain): ...
    def test_get_context_empty_brain(self, brain): ...
    def test_get_context_with_workdir(self, brain): ...

    # ── search_knowledge ──
    def test_search_returns_list(self, brain): ...
    def test_search_with_limit(self, brain): ...
    def test_search_no_results(self, brain): ...

    # ── add_knowledge ──
    def test_add_returns_node_id(self, brain): ...
    def test_add_with_source_author(self, brain): ...
    def test_add_invalid_kind_handled(self, brain): ...
    def test_add_then_search_finds_it(self, brain): ...

    # ── batch_add_knowledge ──
    def test_batch_add_multiple(self, brain): ...
    def test_batch_add_empty_list(self, brain): ...
    def test_batch_add_50_items(self, brain): ...

    # ── brain_status ──
    def test_status_returns_string(self, brain): ...

    # ── complete_task ──
    def test_complete_task_creates_nodes(self, brain): ...
    def test_complete_task_with_pitfalls(self, brain): ...

    # ── krb_pre_screen ──
    def test_krb_pre_screen_returns_list(self, brain): ...


class TestLowFrequencyTools:
    """不常用但需確保不 crash"""

    def test_impact_analysis_unknown_component(self, brain): ...
    def test_temporal_query_default_params(self, brain): ...
    def test_mark_helpful_positive(self, brain): ...
    def test_reasoning_chain_empty_brain(self, brain): ...
    def test_federation_sync_dry_run(self, brain): ...
```

**預期測試數**：≥ 22 tests

### 5.4 實作步驟

| 步驟 | 內容 | 預估 |
|------|------|------|
| VER-1 | 建立 test fixture：BrainServer + 預填知識 | 1h |
| VER-2 | 高頻 tools 測試（get_context, search, add, batch, status） | 2h |
| VER-3 | 中頻 tools 測試（complete_task, krb, report_outcome） | 1h |
| VER-4 | 低頻 tools 測試（impact, temporal, reasoning 等） | 1h |
| VER-5 | 文件更新 | 0.5h |
| VER-6 | 全量回歸 | 0.5h |

### 5.5 驗收條件

- [ ] 22 個 MCP tools 全部測試通過
- [ ] `add_knowledge` → `search_knowledge` 端到端可找到
- [ ] `batch_add_knowledge` 50 條不失敗
- [ ] 空知識庫呼叫任何 tool 不 crash
- [ ] 全量回歸 0 regression

---

## 6. E-03~E-06 後續項目

這些項目保持原 ROADMAP 設計，按需啟動。

| ID | 項目 | 何時需要 | 依賴 |
|----|------|---------|------|
| E-03 | Client Connect 疊加 | 有 VPN 後，Claude Code 直連 + 本地 overlay | E-01 + E-02 |
| E-04 | Ingestion Pipeline | 想從 CLI 批次匯入 GitHub Issues / Markdown | E-02 |
| E-05 | Push to Central | 個人知識推送到集中庫 | E-02 + E-03 |
| E-06 | 運維 Agent 整合 | 團隊擴大，需 admin dashboard | E-01~E-05 |

**注意**：E-04（Ingestion）在小龍蝦架構下可能不需要——小龍蝦本身就能解析文件並呼叫 `add_knowledge`。只有需要 CLI 批次匯入（無人值守）時才需要 E-04。

---

## 7. 實作順序與依賴

```
E-01 HTTP MCP Transport     ✅ DONE v0.45.0
     │
     ├──▶ E-DEPLOY 部署對接（P0，最先做）
     │         │
     │         ├──▶ E-02 多用戶安全（P1）
     │         │         │
     │         │         └──▶ E-04 Ingestion（按需，小龍蝦可替代）
     │         │
     │         └──▶ E-VERIFY 連接驗證（P1，與 E-02 並行）
     │
     └──▶ E-03 Client Connect（需 VPN 後）
               └──▶ E-05 / E-06（按需）
```

**推薦順序**：

| 順序 | 項目 | 做完後的狀態 |
|------|------|------------|
| 1 | **E-DEPLOY** | 小龍蝦連上 Brain，同事可以開始用 |
| 2 | **E-02 + E-VERIFY**（並行） | 多人並發安全 + 所有 tools 驗證 |
| 3 | 按需 | E-03/E-04/E-05/E-06 |

---

## 8. 品質門檻

| 指標 | E-DEPLOY 後 | E-02 + E-VERIFY 後 |
|------|------------|-------------------|
| 總測試數 | ≥ 1167（不變） | ≥ 1200（+35 新增） |
| 新增測試 | 0（部署不需要） | ≥ 35（E-02: 13 + E-VERIFY: 22） |
| 覆蓋率 | ≥ 47% | ≥ 48% |
| 0 regression | ✅ | ✅ |
| 並發安全 | — | 10 threads × 10 writes |
| author 追蹤 | — | source 欄位正確 |
| MCP tools | 手動驗證 | 22 個自動化測試 |

---

## 附錄 A：Brain MCP Tools 完整清單

供小龍蝦 system prompt 參考：

| Tool | 用途 | 參數 |
|------|------|------|
| `get_context` | 取得任務相關知識（智慧匹配） | task, workdir |
| `search_knowledge` | FTS5 全文搜尋 | query, scope, workdir |
| `add_knowledge` | 加入單條知識 | title, kind, content, confidence, source, workdir |
| `batch_add_knowledge` | 批次加入（≤50 條） | items[], workdir |
| `brain_status` | 知識庫統計 | workdir |
| `complete_task` | 記錄任務完成 + 學習 | task_description, decisions[], lessons[], pitfalls[] |
| `report_knowledge_outcome` | 回饋知識是否有用 | node_id, was_useful, notes |
| `krb_pre_screen` | AI 預審待審知識 | limit, workdir |
| `mark_helpful` | 標記知識有用/無用 | node_id, helpful |
| `impact_analysis` | 分析元件影響範圍 | component |
| `temporal_query` | 時間點查詢 | at_time, limit |
| `reasoning_chain` | 知識圖譜推理鏈 | task, workdir |
| `auto_resolve_knowledge` | AI 輔助解決低信心知識 | task, workdir |
| `generate_questions` | 列出需確認的知識 | task, threshold |
| `answer_question` | AI 自動回答確認 | node_id, answer |
| `multi_brain_query` | 跨知識庫查詢 | task, extra_brain_dirs[] |
| `federation_sync` | 跨專案同步 | dry_run, direction |

## 附錄 B：文件上傳知識提取的建議 Prompt

給小龍蝦的知識提取 prompt 範本：

```
使用者上傳了一份文件。請閱讀以下內容，提取其中值得團隊長期記住的知識點。

每條知識請分類：
- Rule：必須遵守的規則或規範
- Decision：架構或技術決策及其理由
- Pitfall：曾經踩過的坑或要避免的錯誤
- Note：一般筆記或備忘

對每條知識，呼叫 add_knowledge tool：
- title：一句話標題
- kind：Rule / Decision / Pitfall / Note
- content：詳細說明（2-3 句）
- confidence：0.85（來自文件的知識）
- source："telegram:@{username}"

如果文件內容不包含值得記住的知識（例如純格式模板），回覆：
「這份文件沒有找到需要記錄的知識點。」
```
